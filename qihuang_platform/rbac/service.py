"""
RBAC 权限服务层
租户开户 / 用户CRUD / 角色分配 / 权限检查
"""
from typing import Optional, List
from sqlalchemy.orm import Session
import bcrypt

from qihuang_platform.db.models import (
    Tenant, Org, User, Role, Permission,
    UserRole, RolePermission, AuditLog, _uid, _now
)


class RBACService:
    """RBAC权限服务"""

    def __init__(self, db: Session):
        self.db = db

    # ── 租户管理 ──

    def create_tenant(self, name: str, display_name: str = None,
                      scene: str = "health", extra: dict = None) -> Tenant:
        """创建租户"""
        t = Tenant(
            id=_uid(), name=name,
            display_name=display_name or name,
            scene=scene, extra=extra or {},
        )
        self.db.add(t)
        # 自动创建根机构
        org = Org(
            id=_uid(), tenant_id=t.id,
            name=f"{name}-根机构", org_type="root",
        )
        self.db.add(org)
        self.db.flush()
        self._log_audit(t.id, None, "CREATE_TENANT", "TENANT", t.id, {"name": name})
        self.db.commit()
        return t

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self.db.query(Tenant).filter_by(id=tenant_id).first()

    def list_tenants(self) -> List[Tenant]:
        return self.db.query(Tenant).filter_by(status="active").all()

    # ── 用户管理 ──

    def create_user(self, tenant_id: str, username: str, password: str,
                    org_id: str = None, display_name: str = None,
                    phone: str = None, email: str = None) -> User:
        """创建用户（自动分配 tenant 的默认角色）"""
        # 检查是否已存在
        existing = self.db.query(User).filter_by(username=username, tenant_id=tenant_id).first()
        if existing:
            raise ValueError(f"用户 {username} 已存在")

        pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(
            id=_uid(), tenant_id=tenant_id, org_id=org_id,
            username=username, password_hash=pwd_hash,
            display_name=display_name or username,
            phone=phone, email=email,
        )
        self.db.add(user)
        self.db.flush()
        self._log_audit(tenant_id, user.id, "CREATE_USER", "USER", user.id, {"username": username})
        self.db.commit()
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter_by(id=user_id).first()

    def get_user_by_username(self, tenant_id: str, username: str) -> Optional[User]:
        return self.db.query(User).filter_by(tenant_id=tenant_id, username=username).first()

    def verify_password(self, user: User, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), user.password_hash.encode())

    def list_users(self, tenant_id: str) -> List[User]:
        return self.db.query(User).filter_by(tenant_id=tenant_id).all()

    def list_users_all(self) -> List[User]:
        """跨租户列出所有用户（超管用）"""
        return self.db.query(User).all()

    # ── 角色管理 ──

    def get_role(self, role_id: str) -> Optional[Role]:
        return self.db.query(Role).filter_by(id=role_id).first()

    def get_role_by_name(self, tenant_id: str, name: str) -> Optional[Role]:
        return self.db.query(Role).filter_by(tenant_id=tenant_id, name=name).first()

    def list_roles(self, tenant_id: str) -> List[Role]:
        return self.db.query(Role).filter_by(tenant_id=tenant_id).all()

    def assign_role(self, user_id: str, role_id: str, org_id: str = None):
        """给用户分配角色"""
        existing = self.db.query(UserRole).filter_by(
            user_id=user_id, role_id=role_id, org_id=org_id
        ).first()
        if not existing:
            self.db.add(UserRole(user_id=user_id, role_id=role_id, org_id=org_id))
            self.db.commit()

    def remove_role(self, user_id: str, role_id: str):
        """移除用户角色"""
        self.db.query(UserRole).filter_by(user_id=user_id, role_id=role_id).delete()
        self.db.commit()

    def assign_default_role(self, user: User, role_name: str = "health_user"):
        """给用户分配默认角色"""
        role = self.get_role_by_name(user.tenant_id, role_name)
        if role:
            self.assign_role(user.id, role.id, user.org_id)

    def get_user_roles(self, user_id: str) -> List[Role]:
        """获取用户的所有角色"""
        ur = self.db.query(UserRole).filter_by(user_id=user_id).all()
        role_ids = [r.role_id for r in ur]
        return self.db.query(Role).filter(Role.id.in_(role_ids)).all() if role_ids else []

    def get_user_effective_roles(self, user_id: str, org_id: str = None) -> List[str]:
        """获取用户在指定机构下的有效角色名"""
        ur_query = self.db.query(UserRole).filter_by(user_id=user_id)
        if org_id:
            ur_query = ur_query.filter(
                (UserRole.org_id == org_id) | (UserRole.org_id.is_(None))
            )
        ur = ur_query.all()
        role_ids = [r.role_id for r in ur]
        roles = self.db.query(Role).filter(Role.id.in_(role_ids)).all() if role_ids else []
        return [r.name for r in roles]

    # ── 权限检查 ──

    def check_permission(self, user_id: str, perm_code: str,
                         org_id: str = None, scene: str = None) -> bool:
        """检查用户是否有指定权限"""
        user = self.get_user(user_id)
        if not user:
            return False

        roles = self.get_user_effective_roles(user_id, org_id)
        if "super_admin" in roles:
            return True

        # 查找权限
        perm = self.db.query(Permission).filter_by(code=perm_code).first()
        if not perm:
            return False

        if scene and perm.scene != "all" and perm.scene != scene:
            return False  # 场景白名单限制

        # 检查角色是否有此权限
        rp = self.db.query(RolePermission).join(Role).filter(
            Role.name.in_(roles),
            RolePermission.perm_id == perm.id,
        ).first()

        return rp is not None

    def check_permissions(self, user_id: str, perm_codes: List[str],
                          org_id: str = None, scene: str = None) -> dict:
        """批量检查权限"""
        return {code: self.check_permission(user_id, code, org_id, scene) for code in perm_codes}

    # ── 审计日志 ──

    def _log_audit(self, tenant_id: str, user_id: str, action: str,
                   target_type: str, target_id: str, detail: dict):
        log = AuditLog(
            id=_uid(), tenant_id=tenant_id, user_id=user_id,
            action=action, target_type=target_type, target_id=target_id,
            detail=detail, success=True,
        )
        self.db.add(log)
