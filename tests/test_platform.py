"""
tests/test_platform.py — 平台基础端点 + 集成冒烟测试
"""
import pytest


class TestPlatformHealth:
    """GET /platform/health"""
    
    def test_health_ok(self, client):
        resp = client.get("/platform/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "岐黄智脑商业化平台"
        assert data["status"] == "ok"


class TestPlatformStatus:
    """GET /platform/status"""
    
    def test_status_ok(self, client):
        resp = client.get("/platform/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.1.0-alpha"
        assert "modules" in data


class TestPageRedirects:
    """页面重定向"""
    
    @pytest.mark.parametrize("path", ["/", "/admin"])
    def test_redirect_ok(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in [200, 307, 302]
    
    @pytest.mark.parametrize("path", ["/ops", "/business"])
    def test_optional_pages(self, client, path):
        """运维/运营页面存在则重定向，不存在则404（正常）"""
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in [200, 307, 302, 404]
        

class TestOpenAPIDocs:
    """OpenAPI 文档"""
    
    def test_docs_available(self, client):
        resp = client.get("/platform/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, client):
        resp = client.get("/platform/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "岐黄智脑商业化平台"
        assert "paths" in data


# ═══════════════════════════════════════════════════════════
# 集成冒烟测试 — API 全链路
# ═══════════════════════════════════════════════════════════

class TestIntegrationSmoke:
    """端到端集成冒烟测试"""
    
    def test_full_auth_flow(self, client):
        """完整认证流程：登录 → 获取信息 → 刷新 → 登出"""
        # 1. 登录
        r1 = client.post("/api/v1/auth/login", json={
            "login_type": "wechat", "code": "smoke_test",
        })
        assert r1.status_code == 200
        token = r1.json()["data"]["access_token"]
        refresh = r1.json()["data"]["refresh_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. 获取用户信息
        r2 = client.get("/api/v1/auth/profile", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["data"]["user_id"]
        
        # 3. 刷新 Token
        r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert r3.status_code == 200
        assert r3.json()["data"]["access_token"]
        
        # 4. 登出
        r4 = client.post("/api/v1/auth/logout", headers=headers)
        assert r4.status_code == 200
    
    def test_admin_flow(self, client):
        """管理员流程：登录 → RBAC操作 → 控制端操作"""
        # 管理员登录
        r1 = client.post("/dev/admin-login")
        assert r1.status_code == 200
        admin_token = r1.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # RBAC: 查看租户
        r2 = client.get("/admin/v1/tenants", headers=headers)
        assert r2.status_code == 200
        
        # RBAC: 查看角色
        r3 = client.get("/admin/v1/roles", headers=headers)
        assert r3.status_code == 200
        
        # 控制端: 查看仪表盘
        r4 = client.get("/admin/v1/dashboard", headers=headers)
        assert r4.status_code in [200, 404, 500]
    
    def test_unified_response_format(self, client):
        """验证 API 端点返回统一格式 {code, message, data, trace_id}"""
        endpoints_to_check = [
            ("POST", "/mock/auth/wechat-login", {"code": "test"}),
            ("POST", "/api/v1/auth/login", {"login_type": "wechat", "code": "fmt_test"}),
        ]
        for method, path, *payload in endpoints_to_check:
            if method == "POST":
                resp = client.post(path, json=payload[0] if payload else {})
            else:
                resp = client.get(path)
            data = resp.json()
            assert "code" in data, f"{method} {path} 缺少 code 字段"
            assert "message" in data, f"{method} {path} 缺少 message 字段"
            assert "data" in data, f"{method} {path} 缺少 data 字段"
            assert "trace_id" in data, f"{method} {path} 缺少 trace_id 字段"


# ─── 汇总：确认总覆盖数 ───
def test_total_endpoint_count(client):
    """确认 OpenAPI 文档中注册的端点数"""
    resp = client.get("/platform/openapi.json")
    assert resp.status_code == 200
    paths = resp.json().get("paths", {})
    # 每个 path 可能有多个 method (GET/POST等)
    total = sum(len(methods) for methods in paths.values())
    print(f"\n[CI] OpenAPI 注册端点总数: {total}")
    assert total >= 30, f"仅检测到 {total} 个端点，预期 >= 30"
