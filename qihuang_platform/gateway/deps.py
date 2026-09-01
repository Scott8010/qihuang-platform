"""
API Gateway - FastAPI 依赖注入
get_current_user / get_api_key / get_tenant_info
"""
import json
from typing import Optional

from fastapi import Depends, Header, Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from qihuang_platform.gateway.auth import (
    verify_token, verify_api_key, get_user, get_api_key_info,
)
from qihuang_platform.gateway.ratelimit import rate_limiter
from qihuang_platform.gateway.response import error

security = HTTPBearer(auto_error=False)

# 管理端角色白名单（#6 打通 tenant_admin/org_admin 进控制台；与 gateway/router.py:429 保持一致）
ADMIN_ROLE_WHITELIST = {"super_admin", "tenant_admin", "org_admin", "admin"}


# ========== JWT Token 鉴权 ==========

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """从 Bearer Token 提取当前用户信息（/api/v1/*, /admin/v1/*）

    #5 全局租户隔离：token 内的 tenant_id 由 JWT 签名保证可信；任何借
    X-Tenant-Id 头切换租户上下文的行为，仅 super_admin 允许（运营/排障用），
    其余角色跨租户一律 403 拒绝。无 X-Tenant-Id 时使用 token 自带租户。
    """
    if not credentials:
        raise HTTPException(status_code=401, detail=error("UNAUTHORIZED", "缺少认证Token"))

    payload = verify_token(credentials.credentials, token_type="access")
    if not payload:
        raise HTTPException(status_code=401, detail=error("TOKEN_EXPIRED"))

    user = get_user(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail=error("TOKEN_INVALID", "用户不存在"))

    roles = payload.get("roles", []) or []
    token_tenant = payload.get("tenant_id")
    is_super = "super_admin" in roles

    header_tenant = request.headers.get("X-Tenant-Id")
    if header_tenant:
        if header_tenant != token_tenant and not is_super:
            raise HTTPException(
                status_code=403,
                detail=error("FORBIDDEN", "禁止跨租户访问（租户上下文不匹配）"),
            )
        effective_tenant = header_tenant
    else:
        effective_tenant = token_tenant

    # 注入到 request.state 供后续使用
    request.state.user_id = payload["sub"]
    request.state.tenant_id = effective_tenant
    request.state.org_id = payload.get("org_id")
    request.state.roles = roles

    return user


async def require_capability_access(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """capability 核心接口门控（#4）：租户须有有效订阅 + 配额未耗尽，否则拒绝。

    内部已依赖 get_current_user（故会注入 tenant_id 等上下文），直接在端点上
    用 Depends(require_capability_access) 替代 Depends(get_current_user) 即可同时
    完成鉴权 + 套餐/配额校验。
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail=error("FORBIDDEN", "无租户上下文，拒绝访问核心能力"),
        )
    from qihuang_platform.billing.quota import check_quota
    res = check_quota(tenant_id)
    if res.get("code") != 0:
        raise HTTPException(
            status_code=403,
            detail=error("FORBIDDEN", "租户无有效订阅，无法使用核心能力"),
        )
    if (res.get("data") or {}).get("is_exceeded"):
        raise HTTPException(
            status_code=402,
            detail=error("QUOTA_EXCEEDED", "本月调用配额已用尽"),
        )
    return user


# ========== API Key 签名鉴权 ==========

async def get_current_api_key(
    request: Request,
    x_app_key: Optional[str] = Header(None, alias="X-App-Key"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
) -> dict:
    """验证 API Key 签名（/open/v1/*）"""
    if not all([x_app_key, x_signature, x_timestamp, x_nonce]):
        raise HTTPException(status_code=401, detail=error("API_KEY_INVALID", "缺少签名参数"))

    # 获取请求体
    body = ""
    try:
        body_bytes = await request.body()
        body = body_bytes.decode("utf-8") if body_bytes else ""
    except Exception:
        body = ""

    key_info = verify_api_key(
        app_key=x_app_key,
        signature=x_signature,
        method=request.method,
        path=request.url.path,
        timestamp=x_timestamp,
        nonce=x_nonce,
        body=body,
    )

    if not key_info:
        raise HTTPException(status_code=401, detail=error("SIGNATURE_MISMATCH"))

    # 注入到 request.state
    request.state.app_key = x_app_key
    request.state.tenant_id = key_info["tenant_id"]
    request.state.is_api_key = True

    return key_info


# ========== 双鉴权（JWT + API Key） ==========

async def get_current_principal(
    request: Request,
    x_app_key: Optional[str] = Header(None, alias="X-App-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
) -> dict:
    """双鉴权入口：API Key 签名优先，否则回退 JWT。

    两种鉴权均向 request.state 注入 tenant_id（API Key 仅注入 tenant_id），
    供下游 require_agent_in_plan 等依赖统一消费。使 /api/v1/agent/* 既能用
    JWT 登录态、也能用 API Key 签名调用（支撑颐掌柜 HB A2 接入）。
    """
    if x_app_key:
        return await get_current_api_key(
            request, x_app_key, x_signature, x_timestamp, x_nonce
        )
    return await get_current_user(request, credentials)


# ========== 管理端增强鉴权 ==========

async def get_current_admin(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """管理端鉴权：Token + 管理员角色白名单（#6 打通 tenant_admin/org_admin 进控制台）

    super_admin 同时保留跨租户能力（经由 get_current_user 的 X-Tenant-Id 切换）。
    """
    roles = request.state.roles or []
    if not (set(roles) & ADMIN_ROLE_WHITELIST):
        raise HTTPException(status_code=403, detail=error("FORBIDDEN", "需要管理员权限"))
    return user


# 别名：兼容子模块 import admin_required
admin_required = get_current_admin


# ========== 限流依赖 ==========

class RateLimit:
    """限流依赖工厂"""
    def __init__(self, rate: float = None, capacity: int = None):
        self.rate = rate
        self.capacity = capacity

    async def __call__(self, request: Request):
        identity = getattr(request.state, "tenant_id", None) or "anonymous"
        endpoint = request.url.path

        allowed, info = rate_limiter.check(
            identity=identity,
            endpoint=endpoint,
            rate=self.rate,
            capacity=self.capacity,
        )

        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=error("RATE_LIMITED"),
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset"]),
                }
            )

        return info
