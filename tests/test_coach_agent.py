"""
coach 能力 Agent 上收（Agent 中台接入点）测试。

验证：
  - POST /api/v1/agent/coach/sessions 创建陪练会话
  - POST /api/v1/agent/coach/evaluate 提交作答 + 四档评分
  - GET  /api/v1/agent/coach/dashboard  学情看板
  - 套餐校验 require_agent_in_plan("coach") 生效（覆盖为放行以测业务）

依赖覆盖：
  - get_current_principal → 注入 tenant_default / user_id
  - proxy.forward → mock 8601 /chat/api/ask 返回推理链
"""
import importlib
import pytest

from qihuang_platform.db.models import EduCoachSession
from qihuang_platform.db.config import SessionLocal


@pytest.fixture
def coach_client(client):
    """覆盖鉴权依赖，注入测试租户。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.agent.deps import require_agent_in_plan

    async def fake_principal(request: Request):
        request.state.tenant_id = "tenant_default"
        return {"tenant_id": "tenant_default", "user_id": "u_coach_1"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    client.app.dependency_overrides[require_agent_in_plan("coach")] = (lambda: None)
    yield client
    client.app.dependency_overrides.clear()


def _patch_proxy(monkeypatch):
    """mock 8601 /chat/api/ask 推理链返回。

    coach router 用 `from capability.proxy import proxy` 绑定引用，且 coach 包 __init__
    的 `from .router import router` 把 `coach.router` 包属性污染成 APIRouter 实例，
    普通模块路径会定位到 APIRouter。因此用 sys.modules 拿真实模块再 monkeypatch。
    """
    from unittest.mock import MagicMock, AsyncMock
    import sys

    result = {
        "code": 0,
        "data": {
            "answer": "辨证属太阳病，宜桂枝汤发汗解表。",
            "reasoning_chain": ["辨病机", "定治法", "选方药"],
        },
    }
    mock_proxy = MagicMock(forward=AsyncMock(return_value=result))
    coach_router_mod = sys.modules["qihuang_platform.agent.coach.router"]
    monkeypatch.setattr(coach_router_mod, "proxy", mock_proxy)


def test_coach_session_and_evaluate(coach_client, monkeypatch):
    _patch_proxy(monkeypatch)

    # 1) 创建会话
    r = coach_client.post(
        "/api/v1/agent/coach/sessions",
        json={"topic": "太阳病辨证", "difficulty": "medium"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["session_id"]
    assert data["status"] == "active"
    session_id = data["session_id"]

    # 2) 提交作答并评估
    r2 = coach_client.post(
        "/api/v1/agent/coach/evaluate",
        json={
            "session_id": session_id,
            "answer": "患者发热恶寒，头项强痛，脉浮，辨为太阳病表证，治以桂枝汤辛温解表，调和营卫。",
        },
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["data"]
    assert d2["evaluation"] in ("PERFECT", "GOOD", "PARTIAL", "WRONG")
    assert isinstance(d2["score"], (int, float))
    assert d2["reasoning_chain"]  # 来自 mock 8601

    # 3) DB 落库校验
    db = SessionLocal()
    try:
        sess = db.query(EduCoachSession).filter_by(id=session_id).first()
        assert sess is not None
        assert sess.score == d2["score"]
        assert sess.tenant_id == "tenant_default"
    finally:
        db.close()


def test_coach_dashboard(coach_client, monkeypatch):
    _patch_proxy(monkeypatch)

    # 先造一个已评分会话
    coach_client.post(
        "/api/v1/agent/coach/sessions",
        json={"topic": "方剂组成", "difficulty": "easy"},
    )
    r = coach_client.get("/api/v1/agent/coach/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert "coach_sessions" in d
    assert "coach_avg_score" in d
    assert d["coach_sessions"] >= 1


def test_coach_invalid_difficulty(coach_client):
    r = coach_client.post(
        "/api/v1/agent/coach/sessions",
        json={"topic": "x", "difficulty": "ultra"},
    )
    print("DIAG invalid_difficulty:", r.status_code, r.text)
    assert r.status_code == 200
    assert r.json()["code"] != 0  # error(INVALID_PARAM)
