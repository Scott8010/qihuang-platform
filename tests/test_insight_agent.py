"""
insight 数据诊断能力 Agent（Agent 中台接入点）测试。

验证：
  - POST /api/v1/agent/insight/diagnose 经营数据诊断（单指标 + 多指标 + JSON 解析）
  - GET  /api/v1/agent/insight/dashboard  用量看板
  - 参数校验（无指标）
  - 套餐校验 require_agent_in_plan("insight") 生效（覆盖为放行以测业务 / 不覆盖则 403）

依赖覆盖：
  - get_current_principal → 注入 tenant_default / user_id
  - engine.diagnose → mock 4 引擎 LLM（返回 (文本, 模型key)），避免真实 LLM 调用
"""
import sys
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def ins_client(client):
    """覆盖鉴权依赖，注入测试租户（insight 无状态，不依赖 user 表 FK）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.agent.deps import require_agent_in_plan

    async def fake_principal(request: Request):
        request.state.tenant_id = "tenant_default"
        return {"tenant_id": "tenant_default", "user_id": "u_ins_1"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    client.app.dependency_overrides[require_agent_in_plan("insight")] = (lambda: None)
    yield client
    client.app.dependency_overrides.clear()


def _patch_engine(monkeypatch, raw=None):
    """mock engine.diagnose（4 引擎 LLM），返回 (文本, 模型key)。

    注意：insight/__init__.py 把 `router` 这个名字绑定到了 APIRouter 对象，
    会遮蔽 `insight.router` 子模块。用 importlib.import_module 取子模块本体，
    否则取到的是 APIRouter 对象、没有 diagnose 属性。
    """
    import importlib
    ins_router_mod = importlib.import_module("qihuang_platform.agent.insight.router")
    if raw is None:
        raw = (
            '{"summary":"客流下降但客单上升，需重点挽回进店流量。",'
            '"issues":[{"severity":"高","title":"客流环比下降","reason":"本月客流 860 低于上月 920","evidence":["customers: 860","customers_prev: 920"]}],'
            '"suggestions":[{"action":"加强门店引流活动","reason":"客流是当前主要短板","priority":"高"}],'
            '"missing_data":["复购率"]}'
        )
    mock_diagnose = AsyncMock(return_value=(raw, "deepseek"))
    monkeypatch.setattr(ins_router_mod, "diagnose", mock_diagnose)
    return mock_diagnose


def _sample_metrics():
    return [
        {"key": "revenue", "label": "本月营业额", "value": 128000, "unit": "元", "prev_value": 150000, "prev_label": "上月"},
        {"key": "customers", "label": "本月客流", "value": 860, "unit": "人", "prev_value": 920, "prev_label": "上月"},
        {"key": "avg_order", "label": "客单价", "value": 148.8, "unit": "元", "prev_value": 163.0, "prev_label": "上月"},
    ]


def test_diagnose_single(ins_client, monkeypatch):
    mock_diag = _patch_engine(monkeypatch)
    r = ins_client.post(
        "/api/v1/agent/insight/diagnose",
        json={"store_id": "store_1", "title": "7月经营诊断", "metrics": _sample_metrics()},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["diagnosis"]["summary"]
    assert len(d["diagnosis"]["issues"]) == 1
    assert d["diagnosis"]["issues"][0]["severity"] == "高"
    assert d["diagnosis"]["issues"][0]["evidence"]
    assert d["model"] == "deepseek"
    assert d["metric_count"] == 3
    assert mock_diag.call_count == 1


def test_diagnose_json_wrapped(ins_client, monkeypatch):
    """LLM 偶发用 ```json 包裹时也能解析。"""
    raw = '```json\n{"summary":"测试包裹","issues":[],"suggestions":[],"missing_data":[]}\n```'
    _patch_engine(monkeypatch, raw=raw)
    r = ins_client.post(
        "/api/v1/agent/insight/diagnose",
        json={"metrics": [{"key": "revenue", "label": "营业额", "value": 100}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["diagnosis"]["summary"] == "测试包裹"


def test_diagnose_unparseable(ins_client, monkeypatch):
    """LLM 返回非 JSON 时降级保留原文，不 500。"""
    _patch_engine(monkeypatch, raw="客流下滑明显，建议加强引流。")
    r = ins_client.post(
        "/api/v1/agent/insight/diagnose",
        json={"metrics": [{"key": "customers", "label": "客流", "value": 100}]},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert "客流下滑明显" in d["diagnosis"]["summary"]


def test_dashboard(ins_client, monkeypatch):
    _patch_engine(monkeypatch)
    ins_client.post(
        "/api/v1/agent/insight/diagnose",
        json={"metrics": _sample_metrics()},
    )
    r = ins_client.get("/api/v1/agent/insight/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert "total_diagnoses" in d
    assert "total_metrics" in d
    assert d["total_diagnoses"] >= 1
    assert d["total_metrics"] >= 3


def test_invalid_no_metrics(ins_client):
    r = ins_client.post(
        "/api/v1/agent/insight/diagnose",
        json={"metrics": []},
    )
    assert r.status_code == 200
    assert r.json()["code"] != 0  # error(INVALID_PARAM)


def test_plan_gate_forbidden_without_subscription(client):
    """未订阅套餐的租户调用 insight → 403 AGENT_FORBIDDEN（不覆盖 require_agent_in_plan）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Tenant

    db = SessionLocal()
    try:
        tid = "tenant_ins_gate"
        if not db.query(Tenant).filter_by(id=tid).first():
            db.add(Tenant(id=tid, name=tid, display_name="INS Gate", scene="health", status="active", extra={}))
            db.commit()
    finally:
        db.close()

    async def fake_principal(request: Request):
        request.state.tenant_id = tid
        return {"tenant_id": tid, "user_id": "u_ins_gate"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    try:
        r = client.post(
            "/api/v1/agent/insight/diagnose",
            json={"metrics": [{"key": "revenue", "label": "营业额", "value": 1}]},
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["code"] == 2008, body
        assert "Agent 能力" in body["message"] or "订阅" in body["message"], body
    finally:
        client.app.dependency_overrides.clear()
