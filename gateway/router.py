"""
API Gateway - 路由层
/auth/* 认证端点 + 受保护资源示例 + 限流测试端点
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from qihuang_platform.gateway.auth import (
    create_access_token, create_refresh_token, verify_token,
    register_user, get_user, revoke_token, register_api_key,
)
from qihuang_platform.gateway.deps import (
    get_current_user, get_current_api_key, get_current_admin, RateLimit,
)
from qihuang_platform.gateway.response import success, error

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])

# ========== 请求/响应模型 ==========

class LoginRequest(BaseModel):
    """登录请求"""
    login_type: str = "wechat"  # wechat / sms / phone
    code: Optional[str] = None  # 微信授权码
    phone: Optional[str] = None
    sms_code: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 7200  # 2小时

class RefreshRequest(BaseModel):
    refresh_token: str

class UserProfile(BaseModel):
    user_id: str
    tenant_id: str
    org_id: str
    roles: List[str]
    extra: dict = {}


# ========== 认证端点 ==========

@router.post("/login")
async def login(req: LoginRequest):
    """
    微信登录 / 短信验证码 / 手机号登录
    开发阶段：mock 登录，接受 code="mock_test_code" 直接登录
    """
    # Mock 登录逻辑（生产替换为微信 OAuth / 短信验证）
    if req.login_type == "wechat":
        if not req.code:
            return error("MISSING_PARAM", "缺少微信授权码")
        # Mock: 用 code 作为 user_id 的 hash
        user_id = f"wx_user_{hash(req.code) % 100000:05d}"
        tenant_id = "tenant_demo"
        org_id = "org_default"
        roles = ["user"]
    elif req.login_type == "sms":
        if not req.phone or not req.sms_code:
            return error("MISSING_PARAM", "缺少手机号或验证码")
        if req.sms_code != "888888":  # Mock 验证码
            return error("INVALID_PARAM", "验证码错误")
        user_id = f"phone_{req.phone}"
        tenant_id = "tenant_demo"
        org_id = "org_default"
        roles = ["user"]
    else:
        return error("INVALID_PARAM", f"不支持的登录方式: {req.login_type}")

    # 注册/更新用户
    register_user(user_id, tenant_id, org_id, roles)

    # 签发 token
    access_token = create_access_token(user_id, tenant_id, org_id, roles)
    refresh_token_str = create_refresh_token(user_id, "login")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": 7200,
    })


@router.post("/refresh")
async def refresh_token(req: RefreshRequest):
    """刷新 access_token"""
    payload = verify_token(req.refresh_token, token_type="refresh")
    if not payload:
        return error("TOKEN_EXPIRED")

    user = get_user(payload["sub"])
    if not user:
        return error("TOKEN_INVALID", "用户不存在")

    # 签发新 token
    access_token = create_access_token(
        user["user_id"], user["tenant_id"], user["org_id"], user["roles"]
    )
    refresh_token_str = create_refresh_token(user["user_id"], payload.get("bound_access_jti", ""))

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": 7200,
    })


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return success({
        "user_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "org_id": user["org_id"],
        "roles": user["roles"],
        "extra": user.get("extra", {}),
        "created_at": user.get("created_at"),
    })


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """登出：撤销当前 access_token"""
    # 从 Authorization header 提取 token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = verify_token(token, "access")
            if payload:
                revoke_token(payload.get("jti", ""))
        except Exception:
            pass
    return success(message="已登出")


@router.get("/usage")
async def get_usage(user: dict = Depends(get_current_user)):
    """获取当前用户用量信息"""
    # 开发阶段返回 mock 数据
    return success({
        "daily_calls": 15,
        "daily_limit": 50,
        "monthly_calls": 230,
        "monthly_limit": 2000,
        "remaining_quota": 1770,
        "plan": "standard",
    })


# ========== 受保护资源示例端点 ==========

resource_router = APIRouter(prefix="/api/v1", tags=["受保护资源"])

@resource_router.get("/protected/hello")
async def protected_hello(user: dict = Depends(get_current_user)):
    """需要认证的示例端点"""
    return success({
        "message": f"你好, {user['user_id']}!",
        "tenant_id": user["tenant_id"],
        "roles": user["roles"],
    })


@resource_router.get("/protected/admin-only")
async def admin_only(user: dict = Depends(get_current_admin)):
    """管理员专属端点"""
    return success({"message": "管理员权限验证通过"})


# ========== 限流测试端点 ==========

rate_limit_test = APIRouter(prefix="/api/v1/test", tags=["限流测试"])

@rate_limit_test.get("/ratelimited")
async def rate_limited_endpoint(
    user: dict = Depends(get_current_user),
    rate_info: dict = Depends(RateLimit(rate=5.0, capacity=5)),
):
    """限流测试端点：5 QPS"""
    return success({"message": "请求通过", "rate_info": rate_info})


# ========== API Key 受保护端点示例 ==========

open_router = APIRouter(prefix="/open/v1", tags=["开放API"])

@open_router.get("/graph/query")
async def open_graph_query(key_info: dict = Depends(get_current_api_key)):
    """开放API示例：图谱查询（需 API Key 签名）"""
    return success({
        "message": "API Key 验证通过",
        "tenant_id": key_info["tenant_id"],
        "plan": key_info["plan"],
    })


# ========== 开发者 API Key 管理（控制端） ==========

api_key_router = APIRouter(prefix="/admin/v1/api-keys", tags=["API Key管理"])

class CreateAPIKeyRequest(BaseModel):
    tenant_id: str
    plan: str = "standard"

@api_key_router.post("/")
async def create_api_key(
    req: CreateAPIKeyRequest,
    user: dict = Depends(get_current_admin),
):
    """签发新 API Key（需要管理员）"""
    import uuid
    app_key = f"ak_{uuid.uuid4().hex[:16]}"
    app_secret = f"sk_{uuid.uuid4().hex[:32]}"

    key_info = register_api_key(
        app_key=app_key,
        app_secret=app_secret,
        tenant_id=req.tenant_id,
        plan=req.plan,
    )

    return success({
        "app_key": app_key,
        "app_secret": app_secret,
        "tenant_id": req.tenant_id,
        "plan": req.plan,
        "status": key_info["status"],
    })


@api_key_router.get("/")
async def list_api_keys_endpoint(user: dict = Depends(get_current_admin)):
    """列出所有 API Key（需要管理员）"""
    from qihuang_platform.gateway.auth import list_api_keys
    keys = list_api_keys()
    return success({"total": len(keys), "items": keys})


@api_key_router.delete("/{key_id}")
async def revoke_api_key(key_id: str, user: dict = Depends(get_current_admin)):
    """吊销 API Key（需要管理员）"""
    from qihuang_platform.gateway.auth import delete_api_key
    if delete_api_key(key_id):
        return success({"message": "已吊销", "key_id": key_id})
    raise HTTPException(404, detail=error("NOT_FOUND", "密钥不存在"))


# ========== 开发辅助端点（仅开发环境） ==========

dev_router = APIRouter(prefix="/dev", tags=["开发辅助"])

class DevRegisterAPIKeyRequest(BaseModel):
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    tenant_id: str = "dev_tenant"
    plan: str = "standard"
    note: Optional[str] = None

@dev_router.post("/register-api-key")
async def dev_register_api_key(req: DevRegisterAPIKeyRequest):
    """开发环境：直接注册 API Key（跳过签名验证）。支持自动生成或手动指定"""
    import uuid
    app_key = req.app_key or f"ak_{uuid.uuid4().hex[:16]}"
    app_secret = req.app_secret or f"sk_{uuid.uuid4().hex[:32]}"
    note = req.note or app_key

    key_info = register_api_key(
        app_key=app_key,
        app_secret=app_secret,
        tenant_id=req.tenant_id,
        plan=req.plan,
        extra={"note": note},
    )
    return success({
        "id": app_key,
        "app_key": app_key,
        "app_secret": app_secret,
        "api_key": app_key,
        "tenant_id": req.tenant_id,
        "plan": req.plan,
        "note": note,
        "status": key_info["status"],
    })


@dev_router.post("/admin-login")
async def dev_admin_login():
    """开发环境：直接获取管理员JWT（跳过OAuth）"""
    user_id = "dev_admin"
    tenant_id = "tenant_default"
    org_id = "org_default"
    roles = ["user", "admin", "super_admin"]

    register_user(user_id, tenant_id, org_id, roles)

    access_token = create_access_token(user_id, tenant_id, org_id, roles)
    refresh_token_str = create_refresh_token(user_id, "dev_admin")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": 7200,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
    })


@dev_router.get("/metering/stats")
async def dev_metering_stats(tenant_id: str = None):
    """开发环境：查询计量统计（从服务器进程内获取）"""
    from qihuang_platform.gateway.metering import metering_store
    stats = metering_store.stats(tenant_id=tenant_id)
    logs = metering_store.query(limit=10)
    return success({
        "stats": stats,
        "recent_logs": [
            {"endpoint": l.endpoint, "method": l.method, "status_code": l.status_code,
             "latency_ms": l.latency_ms, "tenant_id": l.tenant_id}
            for l in logs
        ]
    })
