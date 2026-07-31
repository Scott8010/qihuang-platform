"""
Org 管理 + 租户用户查询 (P2-01~04, P2-08)
机构 CRUD + 启停 + 按租户查询用户
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Org, Tenant, User, UserRole, Role


def _uid():
    import uuid
    return str(uuid.uuid4())


router = APIRouter(prefix="/admin/v1", tags=["机构管理"])


# ═══════════════════════════════════════════
# P2-01~04: Org CRUD
# ═══════════════════════════════════════════

class OrgCreateRequest(BaseModel):
    name: str = Field(..., description="机构名称")
    org_type: str = Field("branch", description="root/branch/dept")


class OrgUpdateRequest(BaseModel):
    name: Optional[str] = None
    org_type: Optional[str] = None


@router.get("/tenants/{tenant_id}/orgs", summary="查询租户下机构列表")
async def list_orgs(
    tenant_id: str,
    admin: dict = Depends(get_current_admin),
):
    """P2-01: 返回指定租户下的所有机构及其用户数"""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        orgs = db.query(Org).filter_by(tenant_id=tenant_id).all()
        result = []
        for o in orgs:
            user_count = db.query(User).filter_by(org_id=o.id).count()
            result.append({
                "id": o.id,
                "name": o.name,
                "org_type": o.org_type,
                "users": user_count,
                "status": o.status,
            })
        return success(data={"orgs": result})
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/orgs", summary="创建机构")
async def create_org(
    tenant_id: str,
    req: OrgCreateRequest,
    admin: dict = Depends(get_current_admin),
):
    """P2-02: 在指定租户下创建机构"""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        # 检查同名
        existing = db.query(Org).filter_by(tenant_id=tenant_id, name=req.name).first()
        if existing:
            return error("DUPLICATE", message=f"机构 {req.name} 已存在")

        org = Org(
            id=_uid(), tenant_id=tenant_id,
            name=req.name, org_type=req.org_type,
            status="active",
        )
        db.add(org)
        db.commit()
        return success(data={
            "id": org.id, "name": org.name,
            "org_type": org.org_type, "users": 0, "status": "active",
        }, message="机构创建成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.put("/orgs/{org_id}", summary="编辑机构信息")
async def update_org(
    org_id: str,
    req: OrgUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """P2-03: 修改机构名称/类型"""
    db = SessionLocal()
    try:
        org = db.query(Org).filter_by(id=org_id).first()
        if not org:
            return error("NOT_FOUND", message="机构不存在")

        if req.name is not None:
            # 检查同名
            dup = db.query(Org).filter(
                Org.tenant_id == org.tenant_id,
                Org.name == req.name,
                Org.id != org_id,
            ).first()
            if dup:
                return error("DUPLICATE", message=f"机构名称 {req.name} 已被占用")
            org.name = req.name
        if req.org_type is not None:
            org.org_type = req.org_type

        db.commit()
        return success(data={"id": org.id, "name": org.name, "org_type": org.org_type},
                      message="机构信息已更新")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.put("/orgs/{org_id}/status", summary="启用/停用机构")
async def toggle_org_status(
    org_id: str,
    status: str = Body(..., embed=True, description="active/disabled"),
    admin: dict = Depends(get_current_admin),
):
    """P2-04: 切换机构启用/停用状态"""
    if status not in ("active", "disabled"):
        return error("INVALID_PARAM", message="status 必须为 active 或 disabled")

    db = SessionLocal()
    try:
        org = db.query(Org).filter_by(id=org_id).first()
        if not org:
            return error("NOT_FOUND", message="机构不存在")

        org.status = status
        db.commit()
        return success(data={"id": org.id, "status": status},
                      message=f"机构已{'启用' if status == 'active' else '停用'}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# P2-08: 按租户查询用户
# ═══════════════════════════════════════════

@router.get("/tenants/{tenant_id}/users", summary="租户下用户列表")
async def list_tenant_users(
    tenant_id: str,
    search: Optional[str] = Query(None, description="按姓名/手机号搜索"),
    role: Optional[str] = Query(None, description="按角色名过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    """P2-08: 查询指定租户下的所有用户（支持搜索/角色过滤/分页）"""
    db = SessionLocal()
    try:
        q = db.query(User).filter_by(tenant_id=tenant_id)

        if search:
            q = q.filter(
                (User.display_name.ilike(f"%{search}%")) |
                (User.phone.ilike(f"%{search}%")) |
                (User.username.ilike(f"%{search}%"))
            )

        if role:
            # 按角色过滤：查拥有该角色的用户
            role_obj = db.query(Role).filter_by(tenant_id=tenant_id, name=role).first()
            if role_obj:
                user_ids_with_role = [
                    ur.user_id for ur in db.query(UserRole).filter_by(role_id=role_obj.id).all()
                ]
                if user_ids_with_role:
                    q = q.filter(User.id.in_(user_ids_with_role))
                else:
                    return paginated(items=[], total=0, page=page, page_size=page_size)

        total = q.count()
        users = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        items = []
        for u in users:
            # 查该用户的角色
            user_roles = db.query(UserRole).filter_by(user_id=u.id).all()
            role_ids = [ur.role_id for ur in user_roles]
            roles = db.query(Role).filter(Role.id.in_(role_ids)).all() if role_ids else []
            # 查机构名
            org_name = ""
            if u.org_id:
                org = db.query(Org).filter_by(id=u.org_id).first()
                if org:
                    org_name = org.name

            items.append({
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "phone": u.phone,
                "email": u.email,
                "org_id": u.org_id,
                "org_name": org_name,
                "status": u.status,
                "roles": [{"name": r.name, "display_name": r.display_name} for r in roles],
                "created_at": u.created_at.isoformat() if u.created_at else None,
            })

        return paginated(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()
