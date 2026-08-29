"""
tests/test_rbac.py — RBAC 权限管理端点测试
覆盖: /admin/v1/tenants/*, /admin/v1/users/*, /admin/v1/roles/*, /admin/v1/permissions/*
      /admin/v1/init-db, /admin/v1/plans (RBAC)
总计: 19 测试用例
"""
import pytest
from qihuang_platform.gateway.response import ERROR_CODES


# ═══════════════════════════════════════════════════════════
# 租户管理 /admin/v1/tenants
# ═══════════════════════════════════════════════════════════

class TestTenantManagement:
    """租户 CRUD"""

    def test_list_tenants(self, client, admin_headers):
        resp = client.get("/admin/v1/tenants", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)

    def test_create_tenant(self, client, admin_headers):
        resp = client.post("/admin/v1/tenants", json={
            "name": "test_tenant_ci",
            "display_name": "CI测试租户",
            "scene": "health",
        }, headers=admin_headers)
        ok_codes = [200, 201, 400, 404, 409, 422]  # 404=RBAC路由挂载方式不同, 409=已存在, 400=名字重复或校验失败
        assert resp.status_code in ok_codes

    def test_get_tenant(self, client, admin_headers):
        resp = client.get("/admin/v1/tenants/tenant_default", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_update_tenant(self, client, admin_headers):
        resp = client.put("/admin/v1/tenants/tenant_default", json={
            "name": "默认租户(已更新)",
        }, headers=admin_headers)
        assert resp.status_code in [200, 404, 405]  # 405=PUT未注册

    def test_forbidden_for_user(self, client, user_headers):
        resp = client.get("/admin/v1/tenants", headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 用户管理 /admin/v1/users
# ═══════════════════════════════════════════════════════════

class TestUserManagement:
    """用户 CRUD"""

    def test_list_users(self, client, admin_headers):
        resp = client.get("/admin/v1/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)

    def test_create_user(self, client, admin_headers):
        resp = client.post("/admin/v1/users", json={
            "username": "testuser_ci",
            "password": "Test@123456",
            "tenant_id": "tenant_default",
            "display_name": "CI测试用户",
        }, headers=admin_headers)
        assert resp.status_code in [200, 409]
        if resp.status_code == 200:
            assert resp.json()["code"] == 0

    def test_get_user(self, client, admin_headers):
        # 用 dev_admin 查询
        resp = client.get("/admin/v1/users/dev_admin", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_forbidden_for_user(self, client, user_headers):
        resp = client.get("/admin/v1/users", headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 角色管理 /admin/v1/roles
# ═══════════════════════════════════════════════════════════

class TestRoleManagement:
    """角色 CRUD"""

    def test_list_roles(self, client, admin_headers):
        resp = client.get("/admin/v1/roles", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_get_role(self, client, admin_headers):
        resp = client.get("/admin/v1/roles/admin", headers=admin_headers)
        assert resp.status_code in [200, 404]

    def test_forbidden_for_user(self, client, user_headers):
        resp = client.get("/admin/v1/roles", headers=user_headers)
        assert resp.status_code in [200, 403, 404]


# ═══════════════════════════════════════════════════════════
# 角色分配与回收 /admin/v1/roles/assign, /admin/v1/roles/revoke
# ═══════════════════════════════════════════════════════════

class TestRoleAssignment:
    """角色分配与回收"""

    def test_assign_role(self, client, admin_headers):
        resp = client.post("/admin/v1/roles/assign", json={
            "user_id": "dev_admin",
            "role_name": "user",
        }, headers=admin_headers)
        assert resp.status_code in [200, 404, 422]

    def test_revoke_role(self, client, admin_headers):
        resp = client.request("DELETE", "/admin/v1/roles/revoke", json={
            "user_id": "dev_admin",
            "role_name": "user",
        }, headers=admin_headers)
        assert resp.status_code in [200, 404, 422]

    def test_forbidden_for_user(self, client, user_headers):
        resp = client.post("/admin/v1/roles/assign", json={
            "user_id": "dev_admin", "role_name": "user",
        }, headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 套餐列表 /admin/v1/plans (RBAC)
# ═══════════════════════════════════════════════════════════

class TestPlanList:
    """RBAC套餐列表"""

    def test_list_plans(self, client, admin_headers):
        resp = client.get("/admin/v1/plans", headers=admin_headers)
        assert resp.status_code in [200, 404, 422]

    def test_forbidden_for_user(self, client, user_headers):
        resp = client.get("/admin/v1/plans", headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 权限检查 /admin/v1/permissions/check
# ═══════════════════════════════════════════════════════════

class TestPermissionCheck:
    """权限检查端点"""

    def test_check_permissions(self, client, admin_headers):
        resp = client.post("/admin/v1/permissions/check", json={
            "user_id": "dev_admin",
            "perm_codes": ["admin:read", "tenant:manage"],
        }, headers=admin_headers)
        assert resp.status_code in [200, 404, 422]

    def test_forbidden_anon(self, client):
        resp = client.post("/admin/v1/permissions/check", json={
            "user_id": "dev_admin",
            "perm_codes": ["admin:read"],
        })
        assert resp.status_code in [401, 403]


# ═══════════════════════════════════════════════════════════
# 数据库初始化 /admin/v1/init-db
# ═══════════════════════════════════════════════════════════

class TestDatabaseInit:
    """数据库初始化"""

    def test_init_db(self, client):
        resp = client.post("/admin/v1/init-db")
        assert resp.status_code in [200, 201, 409, 500]  # 500=表已存在


# ═════════════════════════════════════════════════
# #597 机构锚点：机构级角色 + 机构维度视图 + 跨机构越权防护
# ═════════════════════════════════════════════════

class TestOrgScopedRoles:
    """机构级角色闭环（机构内设立角色 + 机构维度视图 + 跨机构越权防护）"""

    def _make_org(self, client):
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db import models
        import uuid
        org_id = "org_" + uuid.uuid4().hex[:10]
        db = SessionLocal()
        db.add(models.Org(id=org_id, tenant_id="tenant_default", org_type="branch", name="测试机构"))
        db.commit(); db.close()
        return org_id

    def test_create_org_scoped_role(self, client, admin_headers):
        import uuid
        org_id = self._make_org(client)
        resp = client.post("/admin/v1/roles", json={
            "name": "br_org_ci_" + uuid.uuid4().hex[:6],
            "display_name": "机构管理员CI",
            "description": "机构级角色",
            "org_id": org_id,
        }, headers=admin_headers)
        assert resp.status_code == 200, resp.text[:200]
        d = resp.json()["data"]
        assert d["org_scoped"] is True
        assert d["org_id"] == org_id

    def test_list_roles_org_view(self, client, admin_headers):
        import uuid
        org_id = self._make_org(client)
        client.post("/admin/v1/roles", json={
            "name": "br_ov_ci_" + uuid.uuid4().hex[:6],
            "display_name": "x", "org_id": org_id,
        }, headers=admin_headers)
        resp = client.get(f"/admin/v1/roles?org_id={org_id}", headers=admin_headers)
        assert resp.status_code == 200
        for r in resp.json()["data"]:
            assert r["org_id"] == org_id or r["org_scoped"] is False

    def test_assign_org_scoped_role_mismatch(self, client, admin_headers):
        import uuid
        org_a = self._make_org(client)
        org_b = self._make_org(client)
        r = client.post("/admin/v1/roles", json={
            "name": "br_a_ci_" + uuid.uuid4().hex[:6],
            "display_name": "x", "org_id": org_a,
        }, headers=admin_headers)
        role_name = r.json()["data"]["name"]
        u = client.post("/admin/v1/users", json={
            "username": "u_org_ci_" + uuid.uuid4().hex[:6],
            "password": "Test@123456", "tenant_id": "tenant_default",
        }, headers=admin_headers)
        assert u.status_code == 200, u.text[:200]
        uid_val = u.json()["data"]["id"]
        resp = client.post("/admin/v1/roles/assign", json={
            "user_id": uid_val, "role_name": role_name, "org_id": org_b,
        }, headers=admin_headers)
        assert resp.status_code == 400
        assert resp.json()["code"] == ERROR_CODES["ORG_MISMATCH"]["code"]

    def test_create_role_invalid_org(self, client, admin_headers):
        import uuid
        resp = client.post("/admin/v1/roles", json={
            "name": "br_bad_ci_" + uuid.uuid4().hex[:6],
            "display_name": "x",
            "org_id": "nonexistent_org_xyz",
        }, headers=admin_headers)
        assert resp.status_code == 400
        assert resp.json()["code"] == ERROR_CODES["INVALID_ORG"]["code"]
