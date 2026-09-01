"""
RBAC API 路由（管理端）
租户开户 / 用户管理 / 角色权限 / 权限检查
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from qihuang_platform.db.config import get_db, init_db
from qihuang_platform.rbac.service import RBACService, validate_password
from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.db.models import seed_preset_data, Plan, Subscription, UserRole, Role
from qihuang_platform.billing.pricing_config import RECHARGE_PACKS, AGENT_ADDON_PRICE

rbac_router = APIRouter(prefix="/admin/v1", tags=["RBAC管理"])


def get_rbac(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


def _assert_same_tenant(target, user):
    """跨租户越权防护（IDOR 修复）。

    仅 super_admin 可跨租户操作；其余管理员目标资源必须归属本人租户，
    否则按 404 返回（不泄露目标是否存在，防止租户用户枚举）。
    """
    if "super_admin" in (user.get("roles") or []):
        return
    if getattr(target, "tenant_id", None) != user.get("tenant_id"):
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))


# ========== 请求模型 ==========

class CreateTenantRequest(BaseModel):
    name: str
    display_name: Optional[str] = None
    scene: str = "health"
    code: Optional[str] = None  # 可读机构代号（可选，缺省自动生成 JGxxxx）

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
    org_id: Optional[str] = None  # 机构级角色分配（与机构内角色绑定，为空=平台级）

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    org_id: Optional[str] = None
    status: Optional[str] = None  # active / disabled

class ResetPasswordRequest(BaseModel):
    password: Optional[str] = None  # 空则后台随机生成

class CheckPermissionRequest(BaseModel):
    user_id: str
    perm_codes: List[str]
    org_id: Optional[str] = None
    scene: Optional[str] = None

class SetRolePermissionsRequest(BaseModel):
    perm_codes: List[str] = []  # 该角色最终拥有的权限 code 列表（整体替换）

class CreateRoleRequest(BaseModel):
    name: str  # 角色标识（英文/下划线，租户内唯一）
    display_name: Optional[str] = None
    description: Optional[str] = None
    perm_codes: List[str] = []
    org_id: Optional[str] = None  # 机构级角色：指定所属机构（为空=平台级角色）


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
        tenant = rbac.create_tenant(req.name, req.display_name, req.scene, code=req.code)
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
    db: Session = Depends(get_db),
):
    """列出所有租户（含当前套餐，与 /tenants-extended 对齐，修复列表套餐显示缺失）"""
    tenants = rbac.list_tenants()
    # 批量拉取 active subscription -> plan，避免 N+1
    subs = db.query(Subscription).filter(Subscription.status == "active").all()
    plan_ids = {s.plan_id for s in subs}
    plans = {p.id: p for p in db.query(Plan).filter(Plan.id.in_(plan_ids)).all()} if plan_ids else {}
    # 保留订阅对象本身：end_date 用于列表「到期时间」列（此前不下发 → 永远显示 "—"）
    sub_map = {s.tenant_id: {"plan": plans.get(s.plan_id), "sub": s} for s in subs}

    # 待生效的预约升级（status=scheduled 且 start_date 在未来），批量避免 N+1
    from datetime import datetime as _dt, timezone as _tz
    _now = _dt.now(_tz.utc).replace(tzinfo=None)
    pend_subs = db.query(Subscription).filter(
        Subscription.status == "scheduled",
        Subscription.start_date > _now,
    ).all()
    pend_plan_ids = {s.plan_id for s in pend_subs}
    pend_plans = {p.id: p for p in db.query(Plan).filter(Plan.id.in_(pend_plan_ids)).all()} if pend_plan_ids else {}
    pend_map: dict = {}
    for s in pend_subs:
        if s.tenant_id in pend_map:
            continue
        pend_map[s.tenant_id] = {
            "pending_plan": (pend_plans.get(s.plan_id).display_name or pend_plans.get(s.plan_id).plan_name) if pend_plans.get(s.plan_id) else "",
            "pending_effective_date": s.start_date.strftime("%Y-%m-%d") if s.start_date else None,
        }

    rows = []
    for t in tenants:
        entry = sub_map.get(t.id) or {}
        plan = entry.get("plan")  # Plan ORM 对象或 None
        sub = entry.get("sub")    # Subscription ORM 对象或 None
        rows.append({
            "id": t.id, "code": t.code, "name": t.name, "display_name": t.display_name,
            "scene": t.scene, "status": t.status, "created_at": t.created_at.isoformat() if t.created_at else None,
            "plan_id": plan.id if plan else "",
            "plan_name": plan.plan_name if plan else "",
            "plan": (plan.display_name or plan.plan_name) if plan else "",
            # 到期时间：active 订阅的 end_date（此前缺 → 列表到期列恒空）
            "expires": sub.end_date.strftime("%Y-%m-%d") if (sub and sub.end_date) else "",
            # 联系人/3D模块：开户一条龙（/tenants/onboard）落在 Tenant.extra
            "contact_name": (t.extra or {}).get("contact_name", ""),
            "contact_phone": (t.extra or {}).get("contact_phone", ""),
            "contact_email": (t.extra or {}).get("contact_email", ""),
            "module_3d": bool((t.extra or {}).get("module_3d")),
            # 2026-08-22 开户表单升级：机构资质信息透传（详情页展示）
            "address_country": (t.extra or {}).get("address_country", ""),
            "address_province": (t.extra or {}).get("address_province", ""),
            "address_city": (t.extra or {}).get("address_city", ""),
            "address_district": (t.extra or {}).get("address_district", ""),
            "address_detail": (t.extra or {}).get("address_detail", ""),
            "org_intro": (t.extra or {}).get("org_intro", ""),
            "license_business": (t.extra or {}).get("license_business", ""),
            "license_business_name": (t.extra or {}).get("license_business_name", ""),
            "license_medical": (t.extra or {}).get("license_medical", ""),
            "license_medical_name": (t.extra or {}).get("license_medical_name", ""),
            "pending_plan": (pend_map.get(t.id) or {}).get("pending_plan") or None,
            "pending_effective_date": (pend_map.get(t.id) or {}).get("pending_effective_date") or None,
        })
    return success(rows)


@rbac_router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    t = rbac.get_tenant(tenant_id)
    if not t:
        raise HTTPException(404, detail=error("NOT_FOUND", "租户不存在"))
    return success({"id": t.id, "code": t.code, "name": t.name, "scene": t.scene, "status": t.status})


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
        ok, msg = validate_password(req.password)
        if not ok:
            raise HTTPException(400, detail=error("INVALID_PASSWORD", msg))
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
        # 当前 ValueError 仅用于"用户已存在"，返回 409 Conflict
        raise HTTPException(409, detail=error("DUPLICATE", str(e)))


@rbac_router.get("/users")
async def list_users(
    tenant_id: Optional[str] = None,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
    db: Session = Depends(get_db),
):
    """用户列表。

    super_admin 默认跨租户查看全平台用户（可用 tenant_id 参数收窄）；
    其余管理员一律锁定在自己所属租户内，忽略传入的 tenant_id。
    """
    is_super = "super_admin" in (user.get("roles") or [])
    if is_super:
        users = rbac.list_users(tenant_id) if tenant_id else rbac.list_users_all()
    else:
        users = rbac.list_users(user.get("tenant_id", "tenant_default"))
    user_ids = [u.id for u in users]
    # 批量拉取用户角色（避免 N+1）
    role_map = {}
    if user_ids:
        urs = db.query(UserRole, Role).join(Role, UserRole.role_id == Role.id).filter(
            UserRole.user_id.in_(user_ids)
        ).all()
        for ur, r in urs:
            role_map.setdefault(ur.user_id, []).append({
                "id": r.id, "name": r.name, "display_name": r.display_name,
            })
    return success([{
        "id": u.id, "username": u.username, "display_name": u.display_name,
        "phone": u.phone, "email": getattr(u, "email", None), "status": u.status,
        "tenant_id": u.tenant_id, "org_id": u.org_id,
        "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
        "roles": role_map.get(u.id, []),
    } for u in users])


@rbac_router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """用户详情（含角色）"""
    target = rbac.get_user(user_id)
    if not target:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    _assert_same_tenant(target, user)
    roles = rbac.get_user_roles(user_id)
    return success({
        "id": target.id, "username": target.username, "display_name": target.display_name,
        "phone": target.phone, "email": target.email, "status": target.status,
        "tenant_id": target.tenant_id, "org_id": target.org_id,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "roles": [{"id": r.id, "name": r.name, "display_name": r.display_name} for r in roles],
    })


@rbac_router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """更新用户基本信息/状态"""
    target = rbac.get_user(user_id)
    if not target:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    _assert_same_tenant(target, user)
    updated = rbac.update_user(
        user_id,
        display_name=req.display_name,
        phone=req.phone,
        email=req.email,
        org_id=req.org_id,
        status=req.status,
    )
    if not updated:
        raise HTTPException(400, detail=error("UPDATE_FAILED", "更新失败"))
    return success({
        "id": updated.id, "username": updated.username, "display_name": updated.display_name,
        "phone": updated.phone, "email": updated.email, "status": updated.status,
    })


@rbac_router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """重置用户密码（空则随机生成）"""
    target = rbac.get_user(user_id)
    if not target:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    _assert_same_tenant(target, user)
    if req.password is not None:
        ok, msg = validate_password(req.password)
        if not ok:
            raise HTTPException(400, detail=error("INVALID_PASSWORD", msg))
    new_pwd = rbac.reset_password(user_id, req.password)
    if new_pwd is None:
        raise HTTPException(400, detail=error("RESET_FAILED", "密码重置失败"))
    return success({"user_id": user_id, "new_password": new_pwd})


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@rbac_router.post("/me/change-password")
async def change_my_password(
    req: ChangePasswordRequest,
    request: Request,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """当前登录用户自助修改密码（必须验证原密码，不依赖短信）"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(401, detail=error("UNAUTHORIZED", "未登录"))
    target = rbac.get_user(user_id)
    if not target:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    if not rbac.verify_password(target, req.old_password):
        raise HTTPException(401, detail=error("OLD_PASSWORD_WRONG", "原密码错误"))
    ok, msg = validate_password(req.new_password)
    if not ok:
        raise HTTPException(400, detail=error("INVALID_PASSWORD", msg))
    rbac.reset_password(user_id, req.new_password)
    return success({"user_id": user_id, "changed": True})


@rbac_router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """删除用户（同时清理角色关联）"""
    target = rbac.get_user(user_id)
    if not target:
        raise HTTPException(404, detail=error("NOT_FOUND", "用户不存在"))
    _assert_same_tenant(target, user)
    ok = rbac.delete_user(user_id)
    if not ok:
        raise HTTPException(400, detail=error("DELETE_FAILED", "删除失败"))
    return success({"user_id": user_id, "action": "deleted"})


# ========== 角色管理 ==========

@rbac_router.get("/roles")
async def list_roles(
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
    db: Session = Depends(get_db),
    org_id: Optional[str] = None,
):
    """列出所有角色（含权限列表）。

    org_id 传值时仅返回「该机构级角色 + 平台级角色」，供机构管理页"机构内角色"视图；
    不传则返回本租户全部角色（含平台级与所有机构级）。
    """
    from qihuang_platform.db.models import RolePermission, Permission
    tenant_id = user.get("tenant_id", "tenant_default")
    roles = rbac.list_roles(tenant_id)
    if org_id:
        # 机构维度视图：本机构专属角色 + 平台级可继承角色
        roles = [r for r in roles if (r.org_id == org_id or not r.org_id)]

    result = []
    for r in roles:
        # 查该角色绑定的权限
        rps = db.query(RolePermission).filter_by(role_id=r.id).all()
        perm_ids = [rp.perm_id for rp in rps]
        perms = db.query(Permission).filter(Permission.id.in_(perm_ids)).all() if perm_ids else []
        # 查该角色下的用户数
        user_count = db.query(UserRole).filter_by(role_id=r.id).count()

        result.append({
            "id": r.id,
            "name": r.name,
            "display_name": r.display_name,
            "description": r.description,
            "is_system": r.is_system,
            "org_id": r.org_id,
            "org_scoped": bool(r.org_id),
            "users": user_count,
            "permissions": [{
                "code": p.code,
                "name": p.name,
                "perm_type": p.perm_type,
                "scene": p.scene,
            } for p in perms],
        })
    return success(result)


@rbac_router.get("/roles/{role_id}")
async def get_role(
    role_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """获取单个角色详情（支持 role_id 或 role_name）"""
    tenant_id = user.get("tenant_id", "tenant_default")
    role = rbac.get_role(role_id)
    if not role:
        role = rbac.get_role_by_name(tenant_id, role_id)
    if not role:
        raise HTTPException(404, detail=error("NOT_FOUND", "角色不存在"))
    perms = rbac.get_role_permissions(role.id)
    return success({
        "id": role.id,
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
        "is_system": role.is_system,
        "permissions": [{
            "code": p.code,
            "name": p.name,
            "perm_type": p.perm_type,
            "scene": p.scene,
        } for p in perms],
    })


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
    # 机构级角色只能在其所属机构内分配，防止跨机构越权挂载
    if role.org_id and role.org_id != (req.org_id or ""):
        raise HTTPException(400, detail=error(
            "ORG_MISMATCH",
            f"机构级角色 {req.role_name} 必须在其所属机构({role.org_id})内分配",
        ))
    rbac.assign_role(req.user_id, role.id, req.org_id)
    return success({"user_id": req.user_id, "role": req.role_name, "org_id": req.org_id})


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


@rbac_router.put("/roles/{role_id}/permissions")
async def set_role_permissions(
    role_id: str,
    req: SetRolePermissionsRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """整体替换角色权限（精细微调：勾选哪些就给哪些）"""
    role = rbac.get_role(role_id)
    if not role:
        raise HTTPException(404, detail=error("NOT_FOUND", "角色不存在"))
    n = rbac.set_role_permissions(role_id, req.perm_codes or [])
    return success({
        "role_id": role_id, "name": role.name,
        "is_system": role.is_system, "perm_count": n,
    })


@rbac_router.post("/roles")
async def create_role(
    req: CreateRoleRequest,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """创建自定义角色（is_system=False，可删可改）。

    org_id 非空 => 机构级角色（机构内设立，平台级不可见）；为空 => 平台级角色。
    """
    tenant_id = user.get("tenant_id", "tenant_default")
    # 机构级角色需校验 org 归属本租户，避免越权挂载到他人机构
    if req.org_id:
        from qihuang_platform.db.models import Org
        org = rbac.db.query(Org).filter_by(id=req.org_id, tenant_id=tenant_id).first()
        if not org:
            raise HTTPException(400, detail=error("INVALID_ORG", "机构不存在或不属于当前租户"))
    try:
        role = rbac.create_role(
            tenant_id, req.name, req.display_name,
            req.description, req.perm_codes or [],
            org_id=req.org_id,
        )
    except ValueError as e:
        raise HTTPException(400, detail=error("CREATE_FAILED", str(e)))
    return success({
        "id": role.id, "name": role.name,
        "display_name": role.display_name, "is_system": role.is_system,
        "org_id": role.org_id, "org_scoped": bool(role.org_id),
        "perm_count": len(req.perm_codes or []),
    })


@rbac_router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    user: dict = Depends(get_current_admin),
    rbac: RBACService = Depends(get_rbac),
):
    """删除自定义角色（系统预置角色不可删）"""
    role = rbac.get_role(role_id)
    if not role:
        raise HTTPException(404, detail=error("NOT_FOUND", "角色不存在"))
    if role.is_system:
        raise HTTPException(400, detail=error("SYS_ROLE", "系统预置角色不可删除"))
    try:
        ok = rbac.delete_role(role_id)
    except ValueError as e:
        raise HTTPException(400, detail=error("DELETE_FAILED", str(e)))
    if not ok:
        raise HTTPException(400, detail=error("DELETE_FAILED", "删除失败"))
    return success({"role_id": role_id, "action": "deleted"})


# ========== 仪表盘 ==========
# 仪表盘端点已由 control/router.py 统一管理（GET /admin/v1/dashboard → admin_dashboard）


# ========== 权限列表 ==========

@rbac_router.get("/permissions")
async def list_permissions(
    user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """列出所有权限（含中文名、场景、类型）"""
    from qihuang_platform.db.models import Permission
    perms = db.query(Permission).all()
    return success([{
        "code": p.code,
        "name": p.name,
        "perm_type": p.perm_type,
        "scene": p.scene,
    } for p in perms])


# ========== 套餐列表 ==========

@rbac_router.get("/plans")
async def list_plans(
    user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理端：查询所有套餐及功能开关
    套餐按 price_cents 升序：trial(¥99)→standard(¥299)→professional(¥599)→enterprise(¥999)，对齐页面 2×2 布局（上=轻量 / 下=旗舰）"""
    plans = db.query(Plan).order_by(Plan.price_cents.asc()).all()
    return success([{
        "id": p.id,
        "plan_name": p.plan_name,
        "display_name": p.display_name,
        "scene_type": p.scene_type,
        "qps": p.qps,
        "month_calls": p.month_calls,
        "month_tokens": p.month_tokens,
        "price_cents": p.price_cents,
        "status": p.status,
        "features_json": p.features_json or {},
    } for p in plans])


@rbac_router.get("/billing/price-book")
def api_price_book(_admin: dict = Depends(get_current_admin)):
    """计费价目表（#474 单一真源）— 收费中心渲染用，不在此硬编码。

    返回：叠加包（RECHARGE_PACKS，永久有效）+ 单加 agent 月费（AGENT_ADDON_PRICE）。
    调价只改 pricing_config.py，前端自动跟进。
    """
    return success({
        "recharge_packs": [
            {"key": k, "label": v["label"], "yuan": v["yuan"], "credits": v["credits"]}
            for k, v in RECHARGE_PACKS.items()
        ],
        "agent_addon": {
            "text_monthly_yuan": AGENT_ADDON_PRICE["text"],
            "multimodal_monthly_yuan": AGENT_ADDON_PRICE["multimodal"],
            "note": "客户单独开通某 agent 的月度订阅入口（开门费，不含赠送积分）；调用仍按 token 吞积分池，先赠后充。",
        },
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
