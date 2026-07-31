"""
P2第二批: 角色与权限管理端点

角色CRUD + 权限分配 + 用户-角色关联管理
使用 DB 模型: Role, Permission, UserRole, RolePermission, User
"""
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    Role, Permission, UserRole, RolePermission, User, Tenant, Org,
)

# 使用 /roles-admin 前缀避免与 rbac/router.py 的 /roles 冲突
router = APIRouter(prefix="/admin/v1/roles-admin", tags=["角色权限管理"])

perm_router = APIRouter(prefix="/admin/v1/permissions", tags=["权限列表"])


def _uid():
    import uuid
    return uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════
# P2-R1: 角色列表
# ═══════════════════════════════════════════════════════════

@router.get("/", summary="角色模板列表")
async def list_roles(
    tenant_id: Optional[str] = Query(None, description="按租户过滤"),
    scene: Optional[str] = Query(None, description="按场景过滤: all/health/medical/edu"),
    search: Optional[str] = Query(None, description="按名称搜索"),
    admin: dict = Depends(get_current_admin),
):
    """返回角色列表，含用户数统计"""
    db = SessionLocal()
    try:
        q = db.query(Role)

        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        if search:
            q = q.filter(
                (Role.name.contains(search)) |
                (Role.display_name.contains(search))
            )

        roles = q.order_by(Role.is_system.desc(), Role.created_at.desc()).all()

        items = []
        for r in roles:
            user_count = db.query(func.count(UserRole.user_id)).filter_by(role_id=r.id).scalar() or 0

            # 获取权限ID列表
            perm_ids = [rp.perm_id for rp in db.query(RolePermission).filter_by(role_id=r.id).all()]

            items.append({
                "id": r.id,
                "tenant_id": r.tenant_id,
                "name": r.name,
                "display_name": r.display_name or r.name,
                "description": r.description or "",
                "is_system": r.is_system,
                "user_count": user_count,
                "perm_ids": perm_ids,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            })

        return success(data={"total": len(items), "items": items})
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-R2: 角色详情
# ═══════════════════════════════════════════════════════════

@router.get("/{role_id}", summary="角色详情")
async def get_role_detail(
    role_id: str,
    admin: dict = Depends(get_current_admin),
):
    """返回角色完整信息 + 权限列表(分组) + 已分配用户"""
    db = SessionLocal()
    try:
        r = db.query(Role).filter_by(id=role_id).first()
        if not r:
            return error("NOT_FOUND", message="角色不存在")

        # 权限详情(含 data_scope)
        perm_entries = db.query(RolePermission, Permission).join(
            Permission, RolePermission.perm_id == Permission.id
        ).filter(RolePermission.role_id == role_id).all()

        permissions = []
        for rp, p in perm_entries:
            permissions.append({
                "perm_id": p.id,
                "code": p.code,
                "name": p.name,
                "perm_type": p.perm_type,
                "resource": p.resource or "",
                "scene": p.scene or "all",
                "data_scope": rp.data_scope,
            })

        # 按类型分组
        menu_perms = [p for p in permissions if p["perm_type"] == "menu"]
        api_perms = [p for p in permissions if p["perm_type"] == "api"]
        data_perms = [p for p in permissions if p["perm_type"] == "data"]

        # 已分配用户
        user_entries = db.query(UserRole, User).join(
            User, UserRole.user_id == User.id
        ).filter(UserRole.role_id == role_id).all()

        assigned_users = []
        for ur, u in user_entries:
            assigned_users.append({
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name or "",
                "org_id": ur.org_id,
            })

        return success(data={
            "id": r.id,
            "tenant_id": r.tenant_id,
            "name": r.name,
            "display_name": r.display_name or r.name,
            "description": r.description or "",
            "is_system": r.is_system,
            "permissions": {
                "menu": menu_perms,
                "api": api_perms,
                "data": data_perms,
            },
            "users": assigned_users,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-R3: 编辑角色
# ═══════════════════════════════════════════════════════════

class RoleUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None


@router.put("/{role_id}", summary="编辑角色模板")
async def update_role(
    role_id: str,
    req: RoleUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """更新角色名称/描述"""
    db = SessionLocal()
    try:
        r = db.query(Role).filter_by(id=role_id).first()
        if not r:
            return error("NOT_FOUND", message="角色不存在")

        if req.display_name is not None:
            r.display_name = req.display_name
        if req.description is not None:
            r.description = req.description

        db.commit()
        return success(data={"id": r.id}, message="角色已更新")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-R4: 更新角色权限
# ═══════════════════════════════════════════════════════════

class PermEntry(BaseModel):
    perm_id: str
    data_scope: Optional[str] = "SELF"  # SELF/ORG/TENANT


class UpdatePermissionsRequest(BaseModel):
    permissions: list[PermEntry] = Field(default=[], description="完整权限列表(覆盖式更新)")


@router.put("/{role_id}/permissions", summary="更新角色权限")
async def update_role_permissions(
    role_id: str,
    req: UpdatePermissionsRequest,
    admin: dict = Depends(get_current_admin),
):
    """
    覆盖式更新角色权限：先删除所有旧权限关联，再创建新的。
    支持 data_scope (SELF/ORG/TENANT) 级别控制。
    """
    db = SessionLocal()
    try:
        r = db.query(Role).filter_by(id=role_id).first()
        if not r:
            return error("NOT_FOUND", message="角色不存在")

        # 删除旧权限关联
        db.query(RolePermission).filter_by(role_id=role_id).delete()

        # 创建新权限关联
        for entry in req.permissions:
            rp = RolePermission(
                role_id=role_id,
                perm_id=entry.perm_id,
                data_scope=entry.data_scope or "SELF",
            )
            db.add(rp)

        db.commit()
        return success(data={
            "role_id": role_id,
            "perm_count": len(req.permissions),
        }, message=f"已更新 {len(req.permissions)} 条权限")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-R5: 分配用户到角色
# ═══════════════════════════════════════════════════════════

class AssignUserEntry(BaseModel):
    user_id: str
    org_id: Optional[str] = None  # 机构级角色需指定机构


class AssignUsersRequest(BaseModel):
    users: list[AssignUserEntry] = Field(default=[], description="要分配的用户列表")


@router.post("/{role_id}/users", summary="为角色分配用户")
async def assign_users_to_role(
    role_id: str,
    req: AssignUsersRequest,
    admin: dict = Depends(get_current_admin),
):
    """
    批量分配用户到角色。已存在的关联会跳过(不报错)。
    """
    db = SessionLocal()
    try:
        r = db.query(Role).filter_by(id=role_id).first()
        if not r:
            return error("NOT_FOUND", message="角色不存在")

        added = 0
        skipped = 0
        for entry in req.users:
            existing = db.query(UserRole).filter_by(
                user_id=entry.user_id, role_id=role_id
            ).first()
            if existing:
                skipped += 1
                continue

            ur = UserRole(
                user_id=entry.user_id,
                role_id=role_id,
                org_id=entry.org_id,
            )
            db.add(ur)
            added += 1

        db.commit()
        return success(data={
            "role_id": role_id,
            "added": added,
            "skipped": skipped,
        }, message=f"已分配 {added} 名用户，跳过 {skipped} 人(已存在)")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-R6: 权限列表
# ═══════════════════════════════════════════════════════════

@perm_router.get("/", summary="权限列表")
async def list_permissions(
    perm_type: Optional[str] = Query(None, description="按类型过滤: menu/api/data"),
    scene: Optional[str] = Query(None, description="按场景过滤: all/health/medical/edu"),
    admin: dict = Depends(get_current_admin),
):
    """返回全部可分配权限列表，支持按类型和场景过滤"""
    db = SessionLocal()
    try:
        q = db.query(Permission)
        if perm_type:
            q = q.filter_by(perm_type=perm_type)
        if scene:
            q = q.filter(Permission.scene.in_(["all", scene]))
        perms = q.order_by(Permission.perm_type, Permission.code).all()

        return success(data={
            "total": len(perms),
            "items": [{
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "perm_type": p.perm_type,
                "resource": p.resource or "",
                "scene": p.scene or "all",
            } for p in perms],
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()
