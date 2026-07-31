"""
RBAC API 路由（控制端）
租户开户 / 用户管理 / 角色权限 / 权限检查
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from qihuang_platform.db.config import get_db, init_db
from qihuang_platform.rbac.service import RBACService
from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.db.models import seed_preset_data

rbac_router = APIRouter(prefix="/admin/v1", tags=["RBAC管理"])


def get_rbac(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


# ========== 请求模型 ==========

class CreateTenantRequest(BaseModel):
    name: str
    display_name: Optional[str] = None
    scene: str = "health"

class CreateUserRequest(BaseModel):
    username: str
    password: str
    tenant_id: Optional[str] = None  # 跨租户创建（需super_admin）
    display_name: Optional[str] = None
    org_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class AssignRoleRequest(BaseModel):
    user_id: str
    role_name: str

class CheckPermissionRequest(BaseModel):
    user_id: str
    perm_codes: List[str]
    org_id: Optional[str] = None
    scene: Optional[str] = None


# ========== 初始化 ==========

@rbac_router.post("/init-db")
async def initialize_database():
    """初始化数据库表 + 预置数据（仅开发环境）"""
    init_db()
    db = next(get_db())
    try:
        seed_preset_data(db)
        return success({"message": "数据库初始化完成", "tables": 24, "roles": 9, "permissions": 18})
    finally:
        db.close()


# ========== 租户管理 ==========

@rbac_router.post("/tenants")
async def create_tenant(
    req: CreateTenantRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """创建新租户（需要管理员权限）"""
    try:
        tenant = rbac.create_tenant(req.name, req.display_name, req.scene)
        return success({
            "id": tenant.id, "name": tenant.name,
            "display_name": tenant.display_name, "scene": tenant.scene,
        })
    except Exception as e:
        raise HTTPException(400, detail=error("DUPLICATE", str(e)))


@rbac_router.get("/tenants")
async def list_tenants(
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """列出所有租户"""
    tenants = rbac.list_tenants()
    return success([{
        "id": t.id, "name": t.name, "display_name": t.display_name,
        "scene": t.scene, "status": t.status, "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in tenants])


@rbac_router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    t = rbac.get_tenant(tenant_id)
    if not t:
        raise HTTPException(404, detail=error("NOT_FOUND", "租户不存在"))
    return success({"id": t.id, "name": t.name, "scene": t.scene, "status": t.status})


# ========== 用户管理 ==========

@rbac_router.post("/users")
async def create_user(
    req: CreateUserRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """创建用户（需要管理员权限）"""
    # 支持跨租户创建（仅super_admin）
    if req.tenant_id and "super_admin" in user.get("roles", []):
        tenant_id = req.tenant_id
    else:
        tenant_id = user.get("tenant_id", "tenant_default")
    try:
        u = rbac.create_user(
            tenant_id=tenant_id, username=req.username,
            password=req.password, org_id=req.org_id,
            display_name=req.display_name, phone=req.phone, email=req.email,
        )
        # 自动分配默认角色
        rbac.assign_default_role(u)
        return success({
            "id": u.id, "username": u.username, "tenant_id": u.tenant_id,
            "display_name": u.display_name,
        })
    except ValueError as e:
        raise HTTPException(400, detail=error("DUPLICATE", str(e)))


@rbac_router.get("/users")
async def list_users(
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    tenant_id = user.get("tenant_id", "tenant_default")
    users = rbac.list_users(tenant_id)
    return success([{
        "id": u.id, "username": u.username, "display_name": u.display_name,
        "phone": u.phone, "status": u.status,
    } for u in users])


# ========== 角色管理 ==========

@rbac_router.get("/roles")
async def list_roles(
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    tenant_id = user.get("tenant_id", "tenant_default")
    roles = rbac.list_roles(tenant_id)
    return success([{
        "id": r.id, "name": r.name, "display_name": r.display_name,
        "description": r.description, "is_system": r.is_system,
    } for r in roles])


@rbac_router.post("/roles/assign")
async def assign_role(
    req: AssignRoleRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """给用户分配角色"""
    target_user = rbac.get_user(req.user_id)
    if not target_user:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    role = rbac.get_role_by_name(target_user.tenant_id, req.role_name)
    if not role:
        raise HTTPException(404, detail=error("NOT_FOUND", f"角色 {req.role_name} 不存在"))
    rbac.assign_role(req.user_id, role.id)
    return success({"user_id": req.user_id, "role": req.role_name})


@rbac_router.delete("/roles/revoke")
async def revoke_role(
    req: AssignRoleRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    role = rbac.get_role_by_name(user.get("tenant_id", "tenant_default"), req.role_name)
    if role:
        rbac.remove_role(req.user_id, role.id)
    return success({"user_id": req.user_id, "role": req.role_name, "action": "revoked"})


# ========== 仪表盘 ==========

@rbac_router.get("/dashboard")
async def dashboard(
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """控制端仪表盘：租户数/用户数/API调用量汇总"""
    from qihuang_platform.gateway.metering import metering_store

    tenant_id = user.get("tenant_id", "tenant_default")
    roles = user.get("roles", [])
    is_super = "super_admin" in roles

    # 租户和用户统计
    if is_super:
        tenants = rbac.list_tenants()
        tenant_count = len(tenants)
        active_tenants = sum(1 for t in tenants if t.status == "active")
        users = rbac.list_users_all()  # 跨租户
        user_count = len(users)
    else:
        tenant_count = 1
        active_tenants = 1
        users = rbac.list_users(tenant_id)
        user_count = len(users)

    # 计量统计
    stats = metering_store.stats() if is_super else metering_store.stats(tenant_id)
    recent_calls = metering_store.query(limit=10)

    return success({
        "tenants": {"total": tenant_count, "active": active_tenants},
        "users": {"total": user_count},
        "api": {
            "total_calls": stats["total_calls"],
            "total_tokens": stats["total_tokens"],
            "avg_latency_ms": stats["avg_latency_ms"],
        },
        "recent_calls": [{
            "endpoint": c.endpoint, "method": c.method,
            "status_code": c.status_code, "latency_ms": c.latency_ms,
            "timestamp": c.timestamp,
        } for c in recent_calls],
    })


# ========== 权限检查 ==========

@rbac_router.post("/permissions/check")
async def check_permissions(
    req: CheckPermissionRequest,
    user: dict = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac),
):
    """检查用户是否有指定权限"""
    results = rbac.check_permissions(req.user_id, req.perm_codes, req.org_id, req.scene)
    return success({"user_id": req.user_id, "permissions": results})
