"""
tests/test_mock.py — Mock 服务端点测试
覆盖: /mock/* (17 端点)
"""
import pytest


# ═══════════════════════════════════════════════════════════
# Mock 认证端点
# ═══════════════════════════════════════════════════════════

class TestMockAuth:
    """Mock 认证端点"""

    @pytest.mark.parametrize("endpoint,payload", [
        ("/auth/wechat-login", {"code": "mock_code"}),
        ("/auth/sms-code", {"phone": "13800000000"}),
        ("/auth/phone-login", {"phone": "13800000000", "sms_code": "888888"}),
    ])
    def test_login_endpoints(self, client, endpoint, payload):
        resp = client.post(f"/mock{endpoint}", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data

    @pytest.mark.parametrize("endpoint,method", [
        ("/auth/refresh", "POST"),
        ("/auth/profile", "GET"),
        ("/auth/switch-org", "POST"),
        ("/auth/logout", "POST"),
    ])
    def test_auth_endpoints(self, client, endpoint, method):
        if method == "POST":
            resp = client.post(f"/mock{endpoint}", json={})
        else:
            resp = client.get(f"/mock{endpoint}")
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data


# ═══════════════════════════════════════════════════════════
# Mock 核心能力端点
# ═══════════════════════════════════════════════════════════

class TestMockCore:
    """Mock 核心能力端点"""

    def test_reasoning_diagnose(self, client):
        resp = client.post("/mock/core/reasoning/diagnose", json={
            "symptoms": ["头痛", "发热"],
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_reasoning_system(self, client):
        resp = client.post("/mock/core/reasoning/viscera", json={
            "symptoms": ["乏力"],
        })
        assert resp.status_code == 200

    def test_safety_check(self, client):
        resp = client.post("/mock/core/safety/check", json={
            "content": "test",
        })
        assert resp.status_code == 200

    def test_graph_query(self, client):
        resp = client.post("/mock/core/graph/query", json={
            "query": "感冒",
        })
        assert resp.status_code == 200

    def test_graph_entity(self, client):
        resp = client.get("/mock/core/graph/entities/herb/麻黄")
        assert resp.status_code == 200

    def test_agent_chat(self, client):
        resp = client.post("/mock/core/agent/chat", json={
            "message": "什么是风寒感冒？",
        })
        assert resp.status_code == 200

    def test_literature_search(self, client):
        resp = client.get("/mock/core/literature/search", params={
            "keyword": "伤寒",
        })
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# Mock 3D穴位端点
# ═══════════════════════════════════════════════════════════

class TestMockAcupoint:
    """Mock 3D穴位端点"""

    def test_acupoint_model(self, client):
        resp = client.get("/mock/core/acupoint/model")
        assert resp.status_code == 200

    def test_acupoint_guide(self, client):
        resp = client.post("/mock/core/acupoint/guide", json={
            "symptom": "头痛",
        })
        assert resp.status_code == 200

    def test_acupoint_meridian(self, client):
        resp = client.get("/mock/core/acupoint/meridians/LU")
        assert resp.status_code == 200


# ─── 端点计数校验 ───
def test_mock_endpoint_count(client):
    """确认 Mock 端点全部可达"""
    endpoints = [
        ("POST", "/mock/auth/wechat-login"),
        ("POST", "/mock/auth/sms-code"),
        ("POST", "/mock/auth/phone-login"),
        ("POST", "/mock/auth/refresh"),
        ("GET", "/mock/auth/profile"),
        ("POST", "/mock/auth/switch-org"),
        ("POST", "/mock/auth/logout"),
        ("POST", "/mock/core/reasoning/diagnose"),
        ("POST", "/mock/core/reasoning/viscera"),
        ("POST", "/mock/core/safety/check"),
        ("POST", "/mock/core/graph/query"),
        ("GET", "/mock/core/graph/entities/herb/麻黄"),
        ("POST", "/mock/core/agent/chat"),
        ("GET", "/mock/core/literature/search"),
        ("GET", "/mock/core/acupoint/model"),
        ("POST", "/mock/core/acupoint/guide"),
        ("GET", "/mock/core/acupoint/meridians/LU"),
    ]
    for method, path in endpoints:
        if method == "POST":
            resp = client.post(path, json={})
        else:
            resp = client.get(path)
        assert resp.status_code == 200, f"Mock端点失败: {method} {path}"
