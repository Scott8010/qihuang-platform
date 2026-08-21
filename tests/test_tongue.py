"""舌象健康特征分析 Agent 能力 · 单测（MindSen 路 A）。

全部本地可验证，不依赖服务器/真实视觉模型：
  - registry 注册与启用态
  - fail-closed：未配置视觉模型 / 未提供图片 → image_pending，绝不返回假数据
  - 视觉输出归一化：15 类标签 → TongueAnalysis 字段齐全（含 5 新字段）
  - 视觉调用失败 → image_error 安全回退
  - 路由鉴权链路：覆盖依赖后 200；无授权默认 403
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qihuang_platform.agent import registry
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.tongue import engine
from qihuang_platform.gateway.deps import get_current_user

_SAMPLE_TONGUE_JSON = json.dumps({
    "tongue_body": {
        "color": "淡红", "shape": "胖大 齿痕",
        "petechiae": "无瘀斑", "texture": "无老嫩", "deviation": "无歪斜",
    },
    "coating": {
        "color": "白", "thickness": "厚", "quality": "腻",
        "corrosion": "无腐苔", "peeling": "无剥脱",
    },
    "labels": ["绛", "舌胖", "有齿痕", "有裂纹", "有点刺", "无瘀斑", "无瘀点",
               "无老嫩", "无歪斜", "黄", "厚苔", "无腐苔", "有腻苔", "润", "无剥脱"],
    "syndrome_hints": ["脾虚湿盛"],
}, ensure_ascii=False)


# ════════════════ registry ════════════════
def test_tongue_registered_and_active():
    assert "tongue" in registry.BUILTIN_AGENTS
    spec = registry.BUILTIN_AGENTS["tongue"]
    assert spec["router_prefix"] == "/api/v1/agent/tongue"
    assert spec["status"] == "active"
    # 运行时缓存以 DB 为真相源：同步一次（DB 空则用 BUILTIN_AGENTS 播种）
    registry.sync_from_db()
    assert registry.is_active("tongue")


# ════════════════ engine fail-closed ════════════════
def test_tongue_pending_when_no_image():
    data = engine.analyze_tongue("")
    assert data["mode"] == "image_pending"
    assert data["provided"] is False
    assert data["tongue"] is None
    assert data["combined_syndrome"] == []


def test_tongue_pending_when_no_vision_env(monkeypatch):
    for k in ("GEO_VISION_API_BASE", "GEO_VISION_API_KEY", "GEO_VISION_MODEL"):
        monkeypatch.delenv(k, raising=False)
    data = engine.analyze_tongue("data:image/jpeg;base64,AAAA")
    assert data["mode"] == "image_pending"          # fail-closed：不造假
    assert data["provided"] is True
    assert data["tongue"] is None
    assert "未配置视觉模型" in data["note"]


# ════════════════ engine 归一化 ════════════════
def test_tongue_vision_success_normalize(monkeypatch):
    monkeypatch.setenv("GEO_VISION_API_BASE", "https://example.com/v1")
    monkeypatch.setenv("GEO_VISION_API_KEY", "sk-test")
    monkeypatch.setenv("GEO_VISION_MODEL", "qwen-vl-plus")

    def fake_vision(base, key, model, image_ref, prompt):
        assert image_ref.startswith("data:")
        assert "tongue_body" in prompt and "petechiae" in prompt
        return _SAMPLE_TONGUE_JSON

    monkeypatch.setattr(engine, "vision_chat_json", fake_vision)
    data = engine.analyze_tongue("data:image/jpeg;base64,AAAA")
    assert data["mode"] == "vision"
    assert data["engine"] == "qwen-vl-plus"
    assert data["vision_model"] == "qwen-vl-plus"
    t = data["tongue"]
    # 15 类标签 → TongueAnalysis 字段（含 5 新字段）
    assert t["tongue_body"]["color"] == "淡红"
    assert "齿痕" in t["tongue_body"]["shape"]
    assert t["tongue_body"]["petechiae"] == "无瘀斑"
    assert t["tongue_body"]["texture"] == "无老嫩"
    assert t["tongue_body"]["deviation"] == "无歪斜"
    assert t["coating"]["color"] == "白"
    assert t["coating"]["thickness"] == "厚"
    assert t["coating"]["quality"] == "腻"
    assert t["coating"]["corrosion"] == "无腐苔"
    assert t["coating"]["peeling"] == "无剥脱"
    assert "舌胖" in t["labels"]
    assert t["syndrome_hints"] == ["脾虚湿盛"]
    assert data["combined_syndrome"] == ["脾虚湿盛"]
    assert data["face"] is None


def test_tongue_vision_with_face_image(monkeypatch):
    monkeypatch.setenv("GEO_VISION_API_BASE", "https://example.com/v1")
    monkeypatch.setenv("GEO_VISION_API_KEY", "sk-test")

    def fake_vision(base, key, model, image_ref, prompt):
        if "舌象" in prompt:
            return _SAMPLE_TONGUE_JSON
        return json.dumps({"complexion": "萎黄", "lustre": "少泽", "note": ""}, ensure_ascii=False)

    monkeypatch.setattr(engine, "vision_chat_json", fake_vision)
    data = engine.analyze_tongue(
        "data:image/jpeg;base64,AAAA", face_image="data:image/jpeg;base64,BBBB"
    )
    assert data["mode"] == "vision"
    assert data["face"]["complexion"] == "萎黄"
    assert data["face"]["lustre"] == "少泽"


def test_tongue_vision_error_fallback(monkeypatch):
    monkeypatch.setenv("GEO_VISION_API_BASE", "https://example.com/v1")
    monkeypatch.setenv("GEO_VISION_API_KEY", "sk-test")

    def boom(*a, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr(engine, "vision_chat_json", boom)
    data = engine.analyze_tongue("data:image/jpeg;base64,AAAA")
    assert data["mode"] == "image_error"
    assert data["tongue"] is None
    assert "解析失败" in data["note"]


# ════════════════ router 链路 ════════════════
def _make_app():
    from qihuang_platform.agent.tongue.router import router as tongue_router
    app = FastAPI()
    app.include_router(tongue_router, prefix="/api/v1/agent")
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u-test"}
    return app


def test_tongue_route_403_without_plan():
    """不覆盖 require_agent_in_plan → 真实鉴权无租户上下文 → 403 AGENT_FORBIDDEN。"""
    from qihuang_platform.gateway.deps import get_current_principal
    app = _make_app()
    # 放行身份，但 request.state.tenant_id 为空 → 门禁 403「无法解析租户上下文」
    app.dependency_overrides[get_current_principal] = lambda: {"sub": "u-test"}
    with TestClient(app) as c:
        r = c.post("/api/v1/agent/tongue/analyze",
                   json={"image": "data:image/jpeg;base64,AAAA"})
    assert r.status_code == 403
    body = r.json()
    assert body.get("code") in ("AGENT_FORBIDDEN", None)


def test_tongue_route_200_with_authorized(monkeypatch):
    """覆盖鉴权 + fake 引擎 → 200 code=0 且结构完整。"""
    from qihuang_platform.agent.tongue.router import router as tongue_router
    app = FastAPI()
    app.include_router(tongue_router, prefix="/api/v1/agent")
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u-test"}
    app.dependency_overrides[require_agent_in_plan("tongue")] = lambda: {"sub": "u-test"}

    def fake_analyze(image_ref, face_image=None, profile=None):
        return {"engine": "qwen-vl-plus", "mode": "vision",
                "tongue": {"tongue_body": {"color": "淡红"}, "coating": {}},
                "face": None, "combined_syndrome": []}

    monkeypatch.setattr(engine, "analyze_tongue", fake_analyze)
    with TestClient(app) as c:
        r = c.post("/api/v1/agent/tongue/analyze",
                   json={"image": "data:image/jpeg;base64,AAAA"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("code") == 0
    assert body["data"]["mode"] == "vision"
    assert body["data"]["tongue"]["tongue_body"]["color"] == "淡红"
