"""舌象健康特征分析 Agent 能力 · 单测（MindSen 路 A + 三层解耦 T2 规则层）。

全部本地可验证，不依赖服务器/真实视觉模型：
  - registry 注册与启用态
  - fail-closed：未配置视觉模型 / 未提供图片 → image_pending，绝不返回假数据
  - 视觉输出归一化：15 类标签 → TongueAnalysis 字段齐全（含 5 新字段 + 枚举别名归一）
  - Layer2 规则层（rules.py）：标签 → 健康状态倾向 [{name,confidence,source:rule}]
    （健康舌 → 空；未识别字段不触发；source 必须标 rule）
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
from qihuang_platform.gateway.deps import get_current_principal

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
    # Layer2 规则层：[{name, confidence, source:"rule"}]，齿痕+胖大 → 脾虚湿盛倾向
    hints = t["syndrome_hints"]
    assert isinstance(hints, list) and hints
    assert all(h.get("source") == "rule" for h in hints)
    assert all(0 < h.get("confidence", 0) <= 0.9 for h in hints)
    names = [h["name"] for h in hints]
    assert "脾虚湿盛倾向" in names
    assert data["combined_syndrome"] == names
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


def test_tongue_enum_alias_normalize(monkeypatch):
    """视觉模型输出「厚苔」等变体 → 契约枚举「厚」（2026-08-21 探针实测发现）。"""
    monkeypatch.setenv("GEO_VISION_API_BASE", "https://example.com/v1")
    monkeypatch.setenv("GEO_VISION_API_KEY", "sk-test")

    def fake_vision(base, key, model, image_ref, prompt):
        return json.dumps({
            "tongue_body": {"color": "淡红", "shape": "正常", "petechiae": "无瘀斑",
                            "texture": "无老嫩", "deviation": "无歪斜"},
            "coating": {"color": "白苔", "thickness": "厚苔", "quality": "有腻苔",
                        "corrosion": "无腐苔", "peeling": "无剥脱"},
            "labels": [], "syndrome_hints": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(engine, "vision_chat_json", fake_vision)
    data = engine.analyze_tongue("data:image/jpeg;base64,AAAA")
    t = data["tongue"]
    assert t["coating"]["color"] == "白"
    assert t["coating"]["thickness"] == "厚"
    assert t["coating"]["quality"] == "腻"


# ════════════════ Layer2 规则层（rules.py，协助单 T2） ════════════════
from qihuang_platform.agent.tongue.rules import derive_syndrome_hints


def _mk_tongue(color="淡红", shape="正常", petechiae="无瘀斑", deviation="无歪斜",
               c_color="白", thickness="薄", quality="润", peeling="无剥脱",
               corrosion="无腐苔", labels=None):
    return {
        "tongue_body": {"color": color, "shape": shape, "petechiae": petechiae,
                        "texture": "无老嫩", "deviation": deviation},
        "coating": {"color": c_color, "thickness": thickness, "quality": quality,
                    "corrosion": corrosion, "peeling": peeling},
        "labels": labels if labels is not None else [],
    }


def test_rules_healthy_tongue_empty():
    """硬指标 #5：健康舌不得硬编结论 → 空数组。"""
    hints = derive_syndrome_hints(_mk_tongue())
    assert hints == []


def test_rules_teeth_marks_spleen():
    """硬指标 #1 关联：齿痕 → 脾虚湿盛倾向。"""
    hints = derive_syndrome_hints(_mk_tongue(shape="齿痕"))
    names = [h["name"] for h in hints]
    assert "脾虚湿盛倾向" in names
    assert all(h["source"] == "rule" for h in hints)


def test_rules_yellow_greasy_damp_heat():
    """硬指标 #3 关联：黄+腻 → 湿热内蕴倾向（组合信号高置信）。"""
    hints = derive_syndrome_hints(_mk_tongue(c_color="黄", quality="腻"))
    top = hints[0]
    assert top["name"] == "湿热内蕴倾向"
    assert top["confidence"] >= 0.8


def test_rules_thick_white_coat():
    """硬指标 #2 关联：白+厚 → 湿浊内蕴倾向。"""
    hints = derive_syndrome_hints(_mk_tongue(thickness="厚"))
    names = [h["name"] for h in hints]
    assert "湿浊内蕴倾向" in names


def test_rules_unrecognized_no_conclusion():
    """fail-closed：字段未识别 → 不臆断任何倾向。"""
    hints = derive_syndrome_hints(_mk_tongue(
        color="未识别", shape="未识别", c_color="未识别", thickness="未识别", quality="未识别"))
    assert hints == []


def test_rules_cyanotic_blood_stasis():
    hints = derive_syndrome_hints(_mk_tongue(color="青紫"))
    names = [h["name"] for h in hints]
    assert "血瘀倾向" in names


def test_rules_no_coat_yin_deficiency():
    hints = derive_syndrome_hints(_mk_tongue(c_color="无苔", thickness="无苔"))
    names = [h["name"] for h in hints]
    assert "阴液不足倾向" in names


def test_rules_labels_fallback_signal():
    """结构化字段未识别但 labels 有明确异常 → 低置信度兜底信号。"""
    hints = derive_syndrome_hints(_mk_tongue(
        color="未识别", shape="未识别", c_color="未识别", thickness="未识别",
        quality="未识别", labels=["有齿痕"]))
    names = [h["name"] for h in hints]
    assert "脾虚湿盛倾向" in names


def test_rules_healthy_vetoed_by_labels():
    """结构化字段全健康但 labels 含异常标签 → 否决健康判定。"""
    hints = derive_syndrome_hints(_mk_tongue(labels=["有齿痕"]))
    assert hints != []


# ════════════════ router 链路 ════════════════
def _make_app():
    from qihuang_platform.agent.tongue.router import router as tongue_router
    app = FastAPI()
    app.include_router(tongue_router, prefix="/api/v1/agent")
    app.dependency_overrides[get_current_principal] = lambda: {"sub": "u-test"}
    return app


def test_tongue_route_403_without_plan():
    """不覆盖 require_agent_in_plan → 真实鉴权无租户上下文 → 403 AGENT_FORBIDDEN。"""
    app = _make_app()
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
    app.dependency_overrides[get_current_principal] = lambda: {"sub": "u-test"}
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
