"""
tests/test_gateway.py — API Gateway 端点测试
覆盖: /api/v1/auth/*, /api/v1/protected/*, /open/v1/*, /admin/v1/api-keys/*, /admin/v1/login
"""
import pytest

from tests.conftest import DEV_ROUTES_ENABLED, TEST_ADMIN_PASS, TEST_ADMIN_USER


# ═══════════════════════════════════════════════════════════
# 认证端点 /api/v1/auth/*
# ═══════════════════════════════════════════════════════════

class TestAuthLogin:
    """POST /api/v1/auth/login — 登录"""

    def test_wechat_login_ok(self, client):
        """微信Mock登录成功"""
        resp = client.post("/api/v1/auth/login", json={
            "login_type": "wechat", "code": "mock_test_code",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["access_token"]
        assert data["data"]["refresh_token"]
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["expires_in"] == 7200

    def test_wechat_login_missing_code(self, client):
        """微信登录缺少code"""
        resp = client.post("/api/v1/auth/login", json={
            "login_type": "wechat",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_sms_login_ok(self, client):
        """短信验证码登录成功"""
        resp = client.post("/api/v1/auth/login", json={
            "login_type": "sms", "phone": "13800138000", "sms_code": "888888",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_sms_login_wrong_code(self, client):
        """短信验证码错误"""
        resp = client.post("/api/v1/auth/login", json={
            "login_type": "sms", "phone": "13800138000", "sms_code": "000000",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_invalid_login_type(self, client):
        """不支持的登录方式"""
        resp = client.post("/api/v1/auth/login", json={
            "login_type": "password",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] != 0


class TestAuthProfile:
    """GET /api/v1/auth/profile — 获取用户信息"""

    def test_get_profile_ok(self, client, user_headers):
        resp = client.get("/api/v1/auth/profile", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["user_id"]
        assert data["data"]["tenant_id"]
        assert data["data"]["roles"]

    def test_get_profile_unauthorized(self, client):
        resp = client.get("/api/v1/auth/profile")
        assert resp.status_code == 401


class TestAuthRefresh:
    """POST /api/v1/auth/refresh — 刷新Token"""

    def test_refresh_ok(self, client):
        # 先登录获取 refresh_token
        login_resp = client.post("/api/v1/auth/login", json={
            "login_type": "wechat", "code": "mock_test_code",
        })
        refresh_token = login_resp.json()["data"]["refresh_token"]

        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["access_token"]

    def test_refresh_bad_token(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "bad_token",
        })
        assert resp.status_code == 200
        assert resp.json()["code"] != 0


class TestAuthLogout:
    """POST /api/v1/auth/logout — 登出"""

    def test_logout_ok(self, client, user_headers):
        resp = client.post("/api/v1/auth/logout", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_logout_unauthorized(self, client):
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 401


class TestAuthUsage:
    """GET /api/v1/auth/usage — 用户用量"""

    def test_get_usage_ok(self, client, user_headers):
        resp = client.get("/api/v1/auth/usage", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "daily_calls" in data["data"]
        assert "monthly_calls" in data["data"]

    def test_get_usage_unauthorized(self, client):
        resp = client.get("/api/v1/auth/usage")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# 受保护资源 /api/v1/protected/*
# ═══════════════════════════════════════════════════════════

class TestProtected:
    """受保护端点"""

    def test_hello_ok(self, client, user_headers):
        resp = client.get("/api/v1/protected/hello", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_hello_unauthorized(self, client):
        resp = client.get("/api/v1/protected/hello")
        assert resp.status_code == 401

    def test_admin_only_ok(self, client, admin_headers):
        resp = client.get("/api/v1/protected/admin-only", headers=admin_headers)
        assert resp.status_code == 200

    def test_admin_only_forbidden(self, client, user_headers):
        """普通用户无法访问管理员端点"""
        resp = client.get("/api/v1/protected/admin-only", headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 限流测试 /api/v1/test/*
# ═══════════════════════════════════════════════════════════

class TestRateLimit:
    """限流测试端点"""

    def test_ratelimited_ok(self, client, user_headers):
        resp = client.get("/api/v1/test/ratelimited", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_ratelimited_unauthorized(self, client):
        resp = client.get("/api/v1/test/ratelimited")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# 开放API /open/v1/*
# ═══════════════════════════════════════════════════════════

class TestOpenAPI:
    """开放API（API Key 签名认证）"""

    def test_unauthorized(self, client):
        resp = client.get("/open/v1/graph/query")
        assert resp.status_code == 401

    def test_missing_signature(self, client):
        resp = client.get("/open/v1/graph/query", headers={
            "X-App-Key": "test_key",
        })
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════
# API Key 管理 /admin/v1/api-keys/*
# ═══════════════════════════════════════════════════════════

class TestAPIKeyManagement:
    """API Key 管理端点（需管理员）"""

    def test_create_api_key(self, client, admin_headers):
        resp = client.post("/admin/v1/api-keys/", json={
            "tenant_id": "tenant_default",
            "plan": "standard",
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["app_key"]
        assert data["data"]["app_secret"]

    def test_list_api_keys(self, client, admin_headers):
        resp = client.get("/admin/v1/api-keys/", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "items" in data["data"]

    def test_revoke_api_key(self, client, admin_headers):
        # 先创建一个key
        create_resp = client.post("/admin/v1/api-keys/", json={
            "tenant_id": "tenant_default", "plan": "standard",
        }, headers=admin_headers)
        key_id = create_resp.json()["data"]["app_key"]

        # 吊销
        resp = client.delete(f"/admin/v1/api-keys/{key_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_create_key_forbidden(self, client, user_headers):
        resp = client.post("/admin/v1/api-keys/", json={
            "tenant_id": "test", "plan": "standard",
        }, headers=user_headers)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════
# 开发辅助 /dev/*
# ═══════════════════════════════════════════════════════════

class TestAdminLoginSecurity:
    """管理员登录安全基线 —— dev 后门必须下线，只走正式账密通道"""

    def test_dev_backdoor_removed(self, client):
        """/dev/admin-login 后门必须不存在（曾可无鉴权签发 super_admin token）"""
        resp = client.post("/dev/admin-login")
        assert resp.status_code in (404, 405), (
            f"开发后门未下线！status={resp.status_code}，任何人都能拿到 super_admin token"
        )

    def test_login_rejects_wrong_password(self, client):
        resp = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": "__definitely_wrong__",
        })
        assert resp.status_code == 401

    def test_login_rejects_unknown_user(self, client):
        resp = client.post("/admin/v1/login", json={
            "username": "__no_such_user__", "password": TEST_ADMIN_PASS,
        })
        assert resp.status_code == 401

    def test_login_issues_admin_token(self, client):
        resp = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["access_token"]


class TestChangeMyPassword:
    """POST /admin/v1/me/change-password — 当前用户自助改密（验证原密码）"""

    def test_change_password_requires_old(self, client, ensure_admin_in_db):
        """原密码错误应 401"""
        token = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
        }).json()["data"]["access_token"]
        r = client.post("/admin/v1/me/change-password", json={
            "old_password": "__wrong_old__", "new_password": "NewPass@2026",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_change_password_ok_and_relogin(self, client, ensure_admin_in_db):
        """改密成功 → 新密码可登录、旧密码失效；测试后改回避免污染"""
        token = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
        }).json()["data"]["access_token"]
        H = {"Authorization": f"Bearer {token}"}
        # 改密
        r = client.post("/admin/v1/me/change-password", json={
            "old_password": TEST_ADMIN_PASS, "new_password": "NewPass@2026",
        }, headers=H)
        assert r.status_code == 200
        # 新密码可登录
        r2 = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": "NewPass@2026",
        })
        assert r2.status_code == 200
        # 旧密码失效
        r3 = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
        })
        assert r3.status_code == 401
        # 改回原密码，恢复测试环境
        token2 = r2.json()["data"]["access_token"]
        client.post("/admin/v1/me/change-password", json={
            "old_password": "NewPass@2026", "new_password": TEST_ADMIN_PASS,
        }, headers={"Authorization": f"Bearer {token2}"})

    def test_change_password_rejects_weak(self, client, ensure_admin_in_db):
        """弱密码应 400"""
        token = client.post("/admin/v1/login", json={
            "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
        }).json()["data"]["access_token"]
        r = client.post("/admin/v1/me/change-password", json={
            "old_password": TEST_ADMIN_PASS, "new_password": "123",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400


    @pytest.mark.skipif(DEV_ROUTES_ENABLED, reason="ENABLE_DEV_ROUTES=1 时 dev 路由应可用")
    def test_dev_routes_absent_by_default(self, client):
        assert client.post("/dev/register-api-key", json={}).status_code in (404, 405)
        assert client.get("/dev/metering/stats").status_code in (404, 405)

    @pytest.mark.skipif(not DEV_ROUTES_ENABLED, reason="仅在 ENABLE_DEV_ROUTES=1 时校验")
    def test_dev_routes_present_when_enabled(self, client):
        resp = client.get("/dev/metering/stats")
        assert resp.status_code == 200
        assert "stats" in resp.json()["data"]


# ─── 端点计数校验 ───
def test_gateway_endpoint_count(client):
    """确认网关端点可通过 OpenAPI 文档统计"""
    resp = client.get("/platform/openapi.json")
    assert resp.status_code == 200
    paths = resp.json().get("paths", {})
    gateway_paths = [p for p in paths if any(
        p.startswith(prefix) for prefix in 
        ["/api/v1/auth", "/api/v1/protected", "/open/v1", "/admin/v1/api-keys", "/dev"]
    )]
    assert len(gateway_paths) >= 10, f"仅检测到 {len(gateway_paths)} 个网关端点，预期 >= 10"
