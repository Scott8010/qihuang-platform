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


# ========== JWT Token 鉴权 ==========

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """从 Bearer Token 提取当前用户信息（/api/v1/*, /admin/v1/*）"""
    if not credentials:
        raise HTTPException(status_code=401, detail=error("UNAUTHORIZED", "缺少认证Token"))

    payload = verify_token(credentials.credentials, token_type="access")
    if not payload:
        raise HTTPException(status_code=401, detail=error("TOKEN_EXPIRED"))

    user = get_user(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail=error("TOKEN_INVALID", "用户不存在"))

    # 注入到 request.state 供后续使用
    request.state.user_id = payload["sub"]
    request.state.tenant_id = payload["tenant_id"]
    request.state.org_id = payload["org_id"]
    request.state.roles = payload["roles"]

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


# ========== 控制端增强鉴权 ==========

async def get_current_admin(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """控制端鉴权：Token + 管理员角色"""
    roles = request.state.roles
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(status_code=403, detail=error("FORBIDDEN", "需要管理员权限"))
    return user


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
