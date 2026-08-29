"""
API Gateway - 路由层
/auth/* 认证端点 + 受保护资源示例 + 限流测试端点
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import os

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
    login_type: str = "wechat"  # wechat / sms / phone / password
    code: Optional[str] = None  # 微信授权码
    phone: Optional[str] = None
    sms_code: Optional[str] = None
    username: Optional[str] = None  # password 登录用户名
    password: Optional[str] = None  # password 登录密码

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



# ========== 试点 password 白名单登录（仅白名单租户可走真实用户态） ==========
_PILOT_TENANT_IDS = (
    set(os.getenv("QH_PILOT_TENANT_IDS").split(","))
    if os.getenv("QH_PILOT_TENANT_IDS") else {
        "b4514735-daeb-4faf-bb93-37478746c0ef",  # edu-pilot
        "4a371e2e-047f-4607-8fa3-c401f9f91a2c",  # med-pilot
    }
)
# 默认关闭(fail-closed): password 登录仅试点期开放, 需显式设置 QH_PASSWORD_LOGIN_ENABLED=true 才启用
_PASSWORD_LOGIN_ENABLED = os.getenv("QH_PASSWORD_LOGIN_ENABLED", "false").lower() in ("1", "true", "yes", "on")

def _db_password_login(req: LoginRequest):
    """试点期 password 登录：查真实用户 + bcrypt 校验 + 返回真实租户/机构/角色"""
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import User
    from qihuang_platform.rbac.service import RBACService
    if not _PASSWORD_LOGIN_ENABLED:
        return {"error": "LOGIN_DISABLED", "msg": "password 登录已关闭"}
    if not req.username or not req.password:
        return {"error": "MISSING_PARAM", "msg": "缺少用户名或密码"}
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=req.username).first()
        if not user:
            return {"error": "USER_NOT_FOUND", "msg": "用户不存在"}
        if user.status != "active":
            return {"error": "USER_DISABLED", "msg": "用户已禁用"}
        rbac = RBACService(db)
        if not rbac.verify_password(user, req.password):
            return {"error": "INVALID_CREDENTIAL", "msg": "用户名或密码错误"}
        if not user.tenant_id or user.tenant_id not in _PILOT_TENANT_IDS:
            return {"error": "NOT_IN_PILOT", "msg": "不在试点白名单"}
        roles = rbac.get_user_effective_roles(user.id, user.org_id) or ["user"]
        return (user.id, user.tenant_id, user.org_id, roles)
    finally:
        db.close()

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
    elif req.login_type == "password":
        res = _db_password_login(req)
        if isinstance(res, dict) and "error" in res:
            return error(res["error"], res.get("msg", ""))
        user_id, tenant_id, org_id, roles = res
    else:
        return error("INVALID_PARAM", f"不支持的登录方式: {req.login_type}")

    # 注册/更新用户态（真实用户也写入内存身份缓存，供 profile / 受保护接口 get_user 使用）
    register_user(user_id, tenant_id, org_id, roles)

    # 签发 token
    access_token = create_access_token(user_id, tenant_id, org_id, roles)
    refresh_token_str = create_refresh_token(user_id, "login")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": 7200,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "roles": roles,
        "auth_source": req.login_type,
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


# ========== 开发者 API Key 管理（管理端） ==========

api_key_router = APIRouter(prefix="/admin/v1/api-keys", tags=["API Key管理"])

class CreateAPIKeyRequest(BaseModel):
    tenant_id: str
    plan: str = "standard"

@api_key_router.post("/")
async def create_api_key(
    req: CreateAPIKeyRequest,
    user: dict = Depends(get_current_admin),
):
    """签发新 API Key（需要管理员）。

    修复 #594：
    - 签发前先校验 tenant_id 在 Tenant 表存在（fail-fast），避免外键失败被静默吞成「假成功」；
    - 双写顺序改为「先写数据库（真值源）成功后再注册内存鉴权表」，杜绝「内存有、DB 无」导致列表看不到；
    - DB 写入异常显式返回错误，不再 except 静默吞。
    """
    import uuid
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Plan, ApiKey as DBApiKey, Tenant

    # 1) 校验租户存在（fail-fast）
    db_t = SessionLocal()
    try:
        tenant = db_t.query(Tenant).filter_by(id=req.tenant_id).first()
        if not tenant:
            return error(
                "TENANT_NOT_FOUND",
                message=f"租户不存在：{req.tenant_id}。请到「租户管理」复制正确的 tenant_id，或先完成开户后再签发。",
                http_status=404,
            )
    finally:
        db_t.close()

    # 2) 查找 plan_id
    db_plan = SessionLocal()
    try:
        plan = db_plan.query(Plan).filter_by(plan_name=req.plan).first()
        plan_id = plan.id if plan else None
    finally:
        db_plan.close()

    app_key = f"ak_{uuid.uuid4().hex[:16]}"
    app_secret = f"sk_{uuid.uuid4().hex[:32]}"

    # 3) 先写数据库（真值源），成功后再注册内存鉴权表
    key_info = None
    db = SessionLocal()
    try:
        db_key = DBApiKey(
            tenant_id=req.tenant_id,
            app_key=app_key,
            app_secret=app_secret,
            plan_id=plan_id,
            status="active",
            extra={"note": app_key, "purpose": "PROD", "qps": 10},
        )
        db.add(db_key)
        db.commit()
        # 写库成功后再注册内存鉴权（双写顺序修正：DB 为先）
        key_info = register_api_key(
            app_key=app_key,
            app_secret=app_secret,
            tenant_id=req.tenant_id,
            plan=req.plan,
        )
    except Exception as e:
        db.rollback()
        return error(
            "INTERNAL_ERROR",
            message=f"密钥落库失败：{e}",
            http_status=500,
        )
    finally:
        db.close()

    return success({
        "app_key": app_key,
        "app_secret": app_secret,
        "tenant_id": req.tenant_id,
        "plan": req.plan,
        "status": key_info["status"] if key_info else "active",
    })


@api_key_router.get("/")
async def list_api_keys_endpoint(
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_admin),
):
    """列出所有 API Key（需要管理员）—— 优先从 DB 读取，内存作为降级"""
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import ApiKey as DBApiKey, Tenant
        db = SessionLocal()
        try:
            q = db.query(DBApiKey)
            if tenant_id:
                q = q.filter(DBApiKey.tenant_id == tenant_id)
            keys = q.order_by(DBApiKey.created_at.desc()).all()
            items = []
            for k in keys:
                tenant = db.query(Tenant).filter_by(id=k.tenant_id).first()
                extra = k.extra or {}
                items.append({
                    "id": k.id,
                    "app_key": k.app_key,
                    "tenant_id": k.tenant_id,
                    "tenant_name": tenant.display_name if tenant else "",
                    "plan_id": k.plan_id,
                    "status": k.status,
                    "purpose": extra.get("purpose", "PROD"),
                    "qps": extra.get("qps", 10),
                    "expires": extra.get("expires", ""),
                    "ip_whitelist": extra.get("ip_whitelist", []),
                    "note": extra.get("note", ""),
                    "used_calls": 0,
                    "created_at": k.created_at.isoformat() if k.created_at else "",
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else "",
                })
            return success({"total": len(items), "items": items})
        finally:
            db.close()
    except Exception:
        # DB不可用时降级到内存
        from qihuang_platform.gateway.auth import list_api_keys
        keys = list_api_keys()
        return success({"total": len(keys), "items": keys})


@api_key_router.delete("/{key_id}")
async def revoke_api_key(key_id: str, user: dict = Depends(get_current_admin)):
    """吊销 API Key（需要管理员）—— 双删: 数据库软吊销 + 内存同步"""
    from qihuang_platform.gateway.auth import delete_api_key
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import ApiKey as DBApiKey

    # 1) 数据库软吊销（按 id 或 app_key 回退）
    db_revoked = False
    app_key_of = None
    db = SessionLocal()
    try:
        k = db.query(DBApiKey).filter_by(id=key_id).first()
        if not k:
            k = db.query(DBApiKey).filter_by(app_key=key_id).first()
        if k:
            k.status = "revoked"
            app_key_of = k.app_key
            db.commit()
            db_revoked = True
    except Exception:
        db.rollback()
    finally:
        db.close()

    # 2) 内存同步吊销（按 app_key；兜底按 key_id 直接试）
    mem_revoked = delete_api_key(app_key_of) if app_key_of else delete_api_key(key_id)

    if db_revoked or mem_revoked:
        return success({"message": "已吊销", "key_id": key_id})
    raise HTTPException(404, detail=error("NOT_FOUND", "密钥不存在"))


# ========== 管理端登录（生产环境正式账号） ==========

admin_auth_router = APIRouter(prefix="/admin/v1", tags=["管理端认证"])

class AdminLoginRequest(BaseModel):
    username: str
    password: str

ADMIN_ROLE_WHITELIST = {"super_admin", "tenant_admin", "org_admin", "admin"}


def _db_admin_login(username: str, password: str):
    """通道一：数据库账号。命中返回 (user, role_names)，未命中返回 None。

    命中但口令/状态/角色不合法时直接抛 HTTPException（不再回退环境变量，
    否则库里禁用的账号还能靠应急口令进来）。
    """
    from qihuang_platform.db.config import get_db
    from qihuang_platform.rbac.service import RBACService

    db = next(get_db())
    try:
        rbac = RBACService(db)
        u = rbac.get_user_by_username("tenant_default", username)
        if not u:
            return None
        if (u.status or "active") != "active":
            raise HTTPException(403, detail=error("ADMIN_DISABLED", "账号已停用"))
        try:
            pwd_ok = rbac.verify_password(u, password)
        except Exception:
            pwd_ok = False
        if not pwd_ok:
            raise HTTPException(401, detail=error("ADMIN_AUTH_FAILED", "账号或密码错误"))
        role_names = rbac.get_user_effective_roles(u.id)
        if not (ADMIN_ROLE_WHITELIST & set(role_names)):
            raise HTTPException(403, detail=error("ADMIN_FORBIDDEN", "该账号无管理端访问权限"))
        return u, role_names
    finally:
        db.close()


@admin_auth_router.post("/login")
async def admin_login(req: AdminLoginRequest):
    """管理端登录（双通道）

    1. **数据库账号（正式）**：users 表命中即走真 RBAC，角色由 user_roles 决定，
       改密/停用/调角色在控制台即时生效。
    2. **环境变量（应急）**：仅当库里查无此人时才回退 QH_ADMIN_USER/QH_ADMIN_PASS，
       用于数据库故障或首次初始化时的破门通道。
    """
    # ── 通道一：数据库账号 ──
    hit = None
    try:
        hit = _db_admin_login(req.username, req.password)
    except HTTPException:
        raise
    except Exception:
        hit = None  # 库不可用 → 落到应急通道

    if hit:
        u, role_names = hit
        org_id = u.org_id or "org_default"
        register_user(u.id, u.tenant_id, org_id, role_names)
        access_token = create_access_token(u.id, u.tenant_id, org_id, role_names)
        refresh_token_str = create_refresh_token(u.id, "admin")
        return success({
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "token_type": "bearer",
            "expires_in": 7200,
            "user_id": u.id,
            "username": u.username,
            "display_name": u.display_name or u.username,
            "tenant_id": u.tenant_id,
            "roles": role_names,
            "auth_source": "database",
        })

    # ── 通道二：环境变量应急口令 ──
    admin_user = os.getenv("QH_ADMIN_USER", "")
    admin_pass = os.getenv("QH_ADMIN_PASS", "")
    if not admin_user or not admin_pass:
        raise HTTPException(403, detail=error("ADMIN_AUTH_DISABLED", "管理端账号未配置"))
    if req.username != admin_user or req.password != admin_pass:
        raise HTTPException(401, detail=error("ADMIN_AUTH_FAILED", "账号或密码错误"))
    user_id = "admin"
    tenant_id = "tenant_default"
    org_id = "org_default"
    roles = ["user", "admin", "super_admin"]
    register_user(user_id, tenant_id, org_id, roles)
    access_token = create_access_token(user_id, tenant_id, org_id, roles)
    refresh_token_str = create_refresh_token(user_id, "admin")
    return success({
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": 7200,
        "user_id": user_id,
        "username": user_id,
        "display_name": "应急管理员",
        "tenant_id": tenant_id,
        "roles": roles,
        "auth_source": "env_fallback",
    })


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
