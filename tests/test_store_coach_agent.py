"""
store_coach 门店话术对练能力 Agent（Agent 中台接入点）测试。

验证：
  - POST /api/v1/agent/store-coach/sessions  创建话术对练会话（AI 顾客开场）
  - POST /api/v1/agent/store-coach/evaluate  提交话术 → AI 顾客接话 + 四维评分 + 合规横切
  - GET  /api/v1/agent/store-coach/dashboard 话术学情看板
  - 参数校验（scene 非法）
  - 套餐校验 require_agent_in_plan("store-coach") 生效（覆盖为放行以测业务 / 不覆盖则 403）

依赖覆盖：
  - get_current_principal → 注入 tenant_default / user_id
  - engine.customer_reply / engine.evaluate → mock（避免真实 LLM 调用）
  - compliance_engine.analyze → mock（返回 已通过/违规拦截，验证合规横切）
"""
import sys
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def sc_client(client):
    """覆盖鉴权依赖，注入测试租户（store_coach_session.user_id 不强制 FK，API Key 调用无 user 上下文）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.agent.deps import require_agent_in_plan

    async def fake_principal(request: Request):
        request.state.tenant_id = "tenant_default"
        return {"tenant_id": "tenant_default", "user_id": "u_sc_1"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    client.app.dependency_overrides[require_agent_in_plan("store-coach")] = (lambda: None)
    yield client
    client.app.dependency_overrides.clear()


def _patch_engine(monkeypatch, compliance_state="已通过"):
    """mock engine 双角色 + compliance analyze。

    注意：store_coach/__init__.py 把 `router` 绑定成 APIRouter 对象遮蔽子模块，
    用 importlib.import_module 取子模块本体。
    """
    import importlib
    sc_router_mod = importlib.import_module("qihuang_platform.agent.store_coach.router")

    mock_customer = AsyncMock(return_value=("阿姨，您是想了解哪方面的调理呢？", "deepseek"))
    monkeypatch.setattr(sc_router_mod, "customer_reply", mock_customer)
    mock_eval = AsyncMock(return_value=(
        '{"evaluation":{"completeness":80,"professional":85,"affinity":75,"compliance":90},'
        '"score":82.5,"feedback":"开场不错，建议多问一句睡眠情况。","summary":"整体合格"}',
        "deepseek",
    ))
    monkeypatch.setattr(sc_router_mod, "evaluate", mock_eval)

    # mock compliance analyze（避免真实审核链路 + 不写 store）
    compliance_mod = importlib.import_module("qihuang_platform.agent.compliance.engine_l2")
    mock_analyze = AsyncMock(return_value={
        "material_id": "m_test",
        "state": compliance_state,
        "hit_count": 1 if compliance_state != "已通过" else 0,
        "hits": [] if compliance_state == "已通过" else [{"clause_id": "C01", "reason": "测试违规"}],
    })
    monkeypatch.setattr(compliance_mod.compliance_engine, "analyze", mock_analyze)
    return sc_router_mod


def _create_session(sc_client):
    r = sc_client.post(
        "/api/v1/agent/store-coach/sessions",
        json={"scene": "reception", "topic": "进店接待演练"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["session_id"]


def test_create_session(sc_client, monkeypatch):
    _patch_engine(monkeypatch)
    r = sc_client.post(
        "/api/v1/agent/store-coach/sessions",
        json={"scene": "reception", "topic": "进店接待演练", "customer_profile": "50岁阿姨"},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["session_id"]
    assert d["scene"] == "reception"
    assert d["opening"]
    assert d["model"] == "deepseek"


def test_evaluate_flow(sc_client, monkeypatch):
    _patch_engine(monkeypatch)
    sid = _create_session(sc_client)
    r = sc_client.post(
        "/api/v1/agent/store-coach/evaluate",
        json={"session_id": sid, "answer": "阿姨您好，欢迎光临！您想了解哪方面的调理呢？"},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["customer_reply"]
    assert d["score"] == 82.5
    assert d["evaluation"]["completeness"] == 80
    assert d["feedback"]
    assert d["compliance"]["ok"] is True


def test_evaluate_compliance_blocked(sc_client, monkeypatch):
    """违规话术 → compliance 横切拦截（ok=False + hits 标红），仍返回评分。"""
    _patch_engine(monkeypatch, compliance_state="违规拦截")
    sid = _create_session(sc_client)
    r = sc_client.post(
        "/api/v1/agent/store-coach/evaluate",
        json={"session_id": sid, "answer": "这个茶包治百病，保证根治您的失眠！"},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["compliance"]["ok"] is False
    assert len(d["compliance"]["hits"]) >= 1


def test_dashboard(sc_client, monkeypatch):
    _patch_engine(monkeypatch)
    sid = _create_session(sc_client)
    sc_client.post(
        "/api/v1/agent/store-coach/evaluate",
        json={"session_id": sid, "answer": "您好，欢迎光临！"},
    )
    r = sc_client.get("/api/v1/agent/store-coach/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert "total_sessions" in d
    assert "avg_score" in d
    assert "by_scene" in d
    assert d["total_sessions"] >= 1


def test_invalid_scene(sc_client):
    r = sc_client.post(
        "/api/v1/agent/store-coach/sessions",
        json={"scene": "bogus", "topic": "x"},
    )
    assert r.status_code == 200
    assert r.json()["code"] != 0  # error(INVALID_PARAM)


def test_session_not_found(sc_client, monkeypatch):
    _patch_engine(monkeypatch)
    r = sc_client.post(
        "/api/v1/agent/store-coach/evaluate",
        json={"session_id": "no_such_session", "answer": "你好"},
    )
    assert r.status_code == 200
    assert r.json()["code"] != 0  # error(NOT_FOUND)


def test_plan_gate_forbidden_without_subscription(client):
    """未订阅套餐的租户调用 store-coach → 403 AGENT_FORBIDDEN（不覆盖 require_agent_in_plan）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Tenant

    db = SessionLocal()
    try:
        tid = "tenant_sc_gate"
        if not db.query(Tenant).filter_by(id=tid).first():
            db.add(Tenant(id=tid, name=tid, display_name="SC Gate", scene="health", status="active", extra={}))
            db.commit()
    finally:
        db.close()

    async def fake_principal(request: Request):
        request.state.tenant_id = tid
        return {"tenant_id": tid, "user_id": "u_sc_gate"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    try:
        r = client.post(
            "/api/v1/agent/store-coach/sessions",
            json={"scene": "reception", "topic": "x"},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["code"] == 2008, body
        assert "Agent 能力" in body["message"] or "订阅" in body["message"], body
    finally:
        client.app.dependency_overrides.clear()
