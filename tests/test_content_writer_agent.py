"""
content_writer 能力 Agent（Agent 中台接入点）测试。

验证：
  - POST /api/v1/agent/content-writer/generate 生成文案（单版本 + 多版本）
  - GET  /api/v1/agent/content-writer/dashboard  用量看板
  - 参数校验（content_type/tone/length 非法）
  - 套餐校验 require_agent_in_plan("content-writer") 生效（覆盖为放行以测业务 / 不覆盖则 403）

依赖覆盖：
  - get_current_principal → 注入 tenant_default / user_id
  - engine.generate → mock 4 引擎 LLM（返回 (文本, 模型key)），避免真实 LLM 调用
"""
import sys
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def cw_client(client):
    """覆盖鉴权依赖，注入测试租户（content-writer 无状态，不依赖 user 表 FK）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.agent.deps import require_agent_in_plan

    async def fake_principal(request: Request):
        request.state.tenant_id = "tenant_default"
        return {"tenant_id": "tenant_default", "user_id": "u_cw_1"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    client.app.dependency_overrides[require_agent_in_plan("content-writer")] = (lambda: None)
    yield client
    client.app.dependency_overrides.clear()


def _patch_engine(monkeypatch):
    """mock engine.generate（4 引擎 LLM），返回 (文本, 模型key)。

    注意：content_writer/__init__.py 把 `router` 这个名字绑定到了 APIRouter 对象，
    会遮蔽 `content_writer.router` 子模块。用 importlib.import_module 取子模块本体，
    否则取到的是 APIRouter 对象、没有 generate 属性。
    """
    import importlib
    cw_router_mod = importlib.import_module("qihuang_platform.agent.content_writer.router")
    mock_generate = AsyncMock(return_value=("夏季养心，宜静心少虑，饮菊花枸杞茶以清补。", "deepseek", 50))
    monkeypatch.setattr(cw_router_mod, "generate", mock_generate)
    return mock_generate


def test_generate_single(cw_client, monkeypatch):
    _patch_engine(monkeypatch)
    r = cw_client.post(
        "/api/v1/agent/content-writer/generate",
        json={"topic": "夏季养心茶饮推荐", "content_type": "product", "tone": "warm", "length": "medium", "variants": 1},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert len(d["variants"]) == 1
    assert d["variants"][0]["text"]
    assert d["used_model"] == "deepseek"
    assert d["generated_count"] == 1


def test_generate_multi_variants(cw_client, monkeypatch):
    mock_gen = _patch_engine(monkeypatch)
    r = cw_client.post(
        "/api/v1/agent/content-writer/generate",
        json={"topic": "秋季润肺文案", "content_type": "social_post", "tone": "fun", "length": "short", "variants": 3},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert len(d["variants"]) == 3
    assert mock_gen.call_count == 3
    assert all(v["text"] for v in d["variants"])


def test_dashboard(cw_client, monkeypatch):
    _patch_engine(monkeypatch)
    cw_client.post(
        "/api/v1/agent/content-writer/generate",
        json={"topic": "冬至进补", "content_type": "health_article", "tone": "professional", "length": "long", "variants": 2},
    )
    r = cw_client.get("/api/v1/agent/content-writer/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert "total_generations" in d
    assert "total_variants" in d
    assert d["total_generations"] >= 1
    assert d["total_variants"] >= 2


def test_invalid_content_type(cw_client):
    r = cw_client.post(
        "/api/v1/agent/content-writer/generate",
        json={"topic": "x", "content_type": "bogus"},
    )
    assert r.status_code == 200
    assert r.json()["code"] != 0  # error(INVALID_PARAM)


def test_plan_gate_forbidden_without_subscription(client):
    """未订阅套餐的租户调用 content-writer → 403 AGENT_FORBIDDEN（不覆盖 require_agent_in_plan）。"""
    from fastapi import Request
    from qihuang_platform.gateway.deps import get_current_principal
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Tenant

    # 创建无订阅的隔离租户（不碰 tenant_default，避免受其他测试 seed 影响）
    db = SessionLocal()
    try:
        tid = "tenant_cw_gate"
        if not db.query(Tenant).filter_by(id=tid).first():
            db.add(Tenant(id=tid, name=tid, display_name="CW Gate", scene="health", status="active", extra={}))
            db.commit()
    finally:
        db.close()

    async def fake_principal(request: Request):
        request.state.tenant_id = tid
        return {"tenant_id": tid, "user_id": "u_cw_gate"}

    client.app.dependency_overrides[get_current_principal] = fake_principal
    try:
        r = client.post(
            "/api/v1/agent/content-writer/generate",
            json={"topic": "x", "content_type": "general", "variants": 1},
        )
        # 响应码：HTTP 403 + 业务码 2008（AGENT_FORBIDDEN，统一响应体的 code 是数字不是字符串键）
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["code"] == 2008, body
        assert "Agent 能力" in body["message"] or "订阅" in body["message"], body
    finally:
        client.app.dependency_overrides.clear()
