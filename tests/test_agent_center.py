"""
Agent 中台（A 资源池 + B 套餐调配 + C 各能力看板）— 控制端端点 + 调用鉴权 403 用例。

依赖 conftest 的 client(全量 app) / admin_headers(超管) / user_headers(普通用户) fixture。
注意：/admin/v1/plans 存在 rbac 与 control 双路由冲突（rbac 版先注册生效，返回 list），
本测试直接用 DB 取 enterprise 套餐 id，规避该既有冲突。
"""
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Plan
from qihuang_platform.agent.registry import is_active


def _enterprise_plan_id():
    db = SessionLocal()
    try:
        ent = db.query(Plan).filter_by(plan_name="enterprise").first()
        return ent.id if ent else None
    finally:
        db.close()


class TestAgentCenterControl:
    def test_list_agents(self, client, admin_headers):
        r = client.get("/admin/v1/agents", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["total"] >= 1
        keys = {a["agent_key"] for a in body["data"]["agents"]}
        assert "compliance" in keys
        comp = next(a for a in body["data"]["agents"] if a["agent_key"] == "compliance")
        assert isinstance(comp["included_in_plans"], list)

    def test_agent_detail(self, client, admin_headers):
        r = client.get("/admin/v1/agents/compliance", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["data"]["agent_key"] == "compliance"

    def test_agent_detail_not_found(self, client, admin_headers):
        r = client.get("/admin/v1/agents/nope", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 6001  # NOT_FOUND

    def test_toggle_agent(self, client, admin_headers):
        r = client.post("/admin/v1/agents/compliance/toggle",
                        json={"status": "inactive"}, headers=admin_headers)
        assert r.status_code == 200 and r.json()["code"] == 0
        assert r.json()["data"]["status"] == "inactive"
        assert is_active("compliance") is False

        r2 = client.post("/admin/v1/agents/compliance/toggle",
                         json={"status": "active"}, headers=admin_headers)
        assert r2.status_code == 200 and r2.json()["data"]["status"] == "active"
        assert is_active("compliance") is True

    def test_toggle_agent_invalid_status(self, client, admin_headers):
        r = client.post("/admin/v1/agents/compliance/toggle",
                        json={"status": "weird"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 1001  # INVALID_PARAM

    def test_toggle_agent_not_found(self, client, admin_headers):
        r = client.post("/admin/v1/agents/nope/toggle",
                        json={"status": "active"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 6001

    def test_plan_agents_get_set(self, client, admin_headers):
        plan_id = _enterprise_plan_id()
        assert plan_id, "enterprise 套餐应已预置"

        g = client.get(f"/admin/v1/plans/{plan_id}/agents", headers=admin_headers)
        assert g.status_code == 200 and g.json()["code"] == 0
        original = list(g.json()["data"]["agents"])

        s = client.put(f"/admin/v1/plans/{plan_id}/agents",
                       json={"agents": ["compliance"]}, headers=admin_headers)
        assert s.status_code == 200 and s.json()["code"] == 0
        assert s.json()["data"]["agents"] == ["compliance"]

        # 还原（幂等可重复）
        client.put(f"/admin/v1/plans/{plan_id}/agents",
                   json={"agents": original}, headers=admin_headers)

    def test_plan_agents_not_found(self, client, admin_headers):
        r = client.get("/admin/v1/plans/nope_id/agents", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 6001

    def test_agent_dashboard(self, client, admin_headers):
        r = client.get("/admin/v1/agents/compliance/dashboard", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 0
        assert "dashboard" in r.json()["data"]


class TestAgentCallAuthorization:
    def test_compliance_scan_forbidden_without_plan(self, client, user_headers):
        """普通用户(tenant_demo 无有效订阅)调用合规审核 → 403 AGENT_FORBIDDEN。"""
        r = client.post("/api/v1/agent/compliance/scan", json={
            "text": "包治百病根治百病", "store_id": "store_GATED",
        }, headers=user_headers)
        assert r.status_code == 403
        assert r.json()["code"] == 2008  # FORBIDDEN

    def test_compliance_scan_allowed_with_enterprise(self, client, admin_headers):
        """企业版(含 compliance)租户调用 → 放行（persist=False 不污染引擎库）。"""
        r = client.post("/api/v1/agent/compliance/scan", json={
            "text": "包治百病根治百病", "store_id": "store_ENT", "persist": False,
        }, headers=admin_headers)
        assert r.status_code != 403
