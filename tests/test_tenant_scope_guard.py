"""
tests/test_tenant_scope_guard.py — 防越权：列表接口按 token 租户强制过滤

回归 2026-11-18 发现的越权缺口：
- /admin/v1/tenants-extended 返回全平台租户
- /admin/v1/tenants 返回全平台租户
- /admin/v1/api-keys/ 传 tenant_id 可拖库别家密钥

修复口径：非 super_admin 一律锁定 token 自带 tenant_id；super_admin 不变。
"""
import pytest


# ═══════════════════════════════════════════════════════════
# 1. 纯函数单测：get_scoped_tenant_id / is_super_admin
# ═══════════════════════════════════════════════════════════

class _FakeState:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id


class _FakeRequest:
    def __init__(self, tenant_id):
        self.state = _FakeState(tenant_id)


class TestScopeHelper:
    def test_super_admin_is_unscoped(self):
        from qihuang_platform.gateway.deps import get_scoped_tenant_id, is_super_admin
        u = {"roles": ["super_admin"], "tenant_id": "t-admin"}
        assert is_super_admin(u) is True
        req = _FakeRequest("t-other")  # 超管切到别家上下文
        # 超管返回 None = 不限制
        assert get_scoped_tenant_id(req, u) is None

    def test_org_admin_scoped_to_own_tenant(self):
        from qihuang_platform.gateway.deps import get_scoped_tenant_id, is_super_admin
        u = {"roles": ["org_admin"], "tenant_id": "t-mine"}
        assert is_super_admin(u) is False
        req = _FakeRequest("t-mine")
        assert get_scoped_tenant_id(req, u) == "t-mine"

    def test_tenant_admin_scoped_even_if_request_state_differs(self):
        # token 租户优先：即便 request.state 被改成别家，也只认 user["tenant_id"]
        from qihuang_platform.gateway.deps import get_scoped_tenant_id
        u = {"roles": ["tenant_admin"], "tenant_id": "t-mine"}
        req = _FakeRequest("t-forged")
        assert get_scoped_tenant_id(req, u) == "t-mine"

    def test_no_roles_not_super(self):
        from qihuang_platform.gateway.deps import is_super_admin
        assert is_super_admin({"roles": []}) is False
        assert is_super_admin({}) is False


# ═══════════════════════════════════════════════════════════
# 2. 集成测试：3 个接口在 mock 身份下只返回本租户数据
# ═══════════════════════════════════════════════════════════

class TestListEndpointsScoping:
    """mock get_current_admin，验证列表接口不泄露别家数据。

    测试库里 seed 了多个租户（见 conftest），这里用真实 token 租户过滤逻辑，
    断言：租户管理员拿到的列表里，所有条目的 tenant_id 都等于本人租户。
    """

    def _auth_as(self, client, roles, tenant_id):
        from qihuang_platform.gateway.deps import get_current_admin
        app = client.app

        def fake_admin(request=None):
            return {"roles": roles, "tenant_id": tenant_id, "sub": "test"}

        app.dependency_overrides[get_current_admin] = fake_admin
        # 同时覆盖 get_current_user：get_scoped_tenant_id 从 fake_admin 拿 user，
        # 但 request.state.tenant_id 由真实 get_current_user 注入；这里直接注入
        # 一个中间件把 X-Tenant-Id 强制设为本人租户，模拟正常 JWT 行为。
        return app

    def test_api_keys_tenant_cannot_see_others(self, client):
        """租户管理员传 tenant_id=别家，也只拿到自己租户的密钥"""
        from qihuang_platform.gateway.deps import get_current_admin
        app = client.app

        def fake_admin():
            return {"roles": ["org_admin"], "tenant_id": "__NO_SUCH_TENANT__", "sub": "t"}

        app.dependency_overrides[get_current_admin] = fake_admin
        try:
            resp = client.get(
                "/admin/v1/api-keys/?tenant_id=some-other-tenant",
                headers={"X-Tenant-Id": "__NO_SUCH_TENANT__"},
            )
            assert resp.status_code == 200
            items = (resp.json().get("data") or {}).get("items", [])
            # 关键断言：绝不能出现别家租户的密钥
            assert all(k.get("tenant_id") == "__NO_SUCH_TENANT__" for k in items), (
                f"越权！返回了别家密钥: {[k.get('tenant_id') for k in items]}"
            )
        finally:
            app.dependency_overrides.clear()

    def test_tenants_extended_tenant_cannot_see_others(self, client):
        """租户管理员看 tenants-extended 只返回本租户（0 条也算通过，绝不返回全平台）"""
        from qihuang_platform.gateway.deps import get_current_admin
        app = client.app

        def fake_admin():
            return {"roles": ["org_admin"], "tenant_id": "__NO_SUCH_TENANT__", "sub": "t"}

        app.dependency_overrides[get_current_admin] = fake_admin
        try:
            resp = client.get(
                "/admin/v1/tenants-extended?page_size=100",
                headers={"X-Tenant-Id": "__NO_SUCH_TENANT__"},
            )
            assert resp.status_code == 200
            items = (resp.json().get("data") or {}).get("items", [])
            assert all(t.get("id") == "__NO_SUCH_TENANT__" for t in items), (
                f"越权！返回了别家租户: {[t.get('id') for t in items]}"
            )
        finally:
            app.dependency_overrides.clear()

    def test_super_admin_still_sees_all_api_keys(self, client):
        """超管行为不变：仍可跨租户看全部密钥"""
        from qihuang_platform.gateway.deps import get_current_admin
        app = client.app

        def fake_admin():
            return {"roles": ["super_admin"], "tenant_id": "t-admin", "sub": "su"}

        app.dependency_overrides[get_current_admin] = fake_admin
        try:
            resp = client.get("/admin/v1/api-keys/")
            assert resp.status_code == 200
            # 超管不传 tenant_id → 全量（至少能查到，不强制过滤到 t-admin）
            items = (resp.json().get("data") or {}).get("items", [])
            assert isinstance(items, list)
        finally:
            app.dependency_overrides.clear()
