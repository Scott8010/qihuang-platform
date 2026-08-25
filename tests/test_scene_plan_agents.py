"""
场景预配 + 门控动态取 agent 验证（#472 / #473）。

- get_effective_agents：按 (plan, scene) 从 SCENE_PLAN_AGENTS 取编排，非法 scene fallback MED
- require_agent_in_plan：门控真实按 tenant.scene 动态取，而非套餐 features_json.agents 静态兜底；
  RETAIL 专业版含 fortune 放行、不含 tongue 则 403
"""
import asyncio
from types import SimpleNamespace

from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.billing.plans import (
    DEFAULT_PLANS, SCENE_PLAN_AGENTS, get_effective_agents, seed_plans,
)


def _plan(name):
    return next(p for p in DEFAULT_PLANS if p["plan_name"] == name)


# ───────────────────── 纯函数：场景化取 agents ─────────────────────
def test_get_effective_agents_by_scene():
    # RETAIL 专业版 = compliance + fortune + health-assistant
    assert get_effective_agents(_plan("professional"), "RETAIL") == \
        ["compliance", "fortune", "health-assistant"]
    # EDU 企业版 = coach + content-writer + health-assistant + insight
    assert get_effective_agents(_plan("enterprise"), "EDU") == \
        ["coach", "content-writer", "health-assistant", "insight"]
    # HQ 仅企业版有编排，且不含 health-assistant
    assert get_effective_agents(_plan("enterprise"), "HQ") == \
        ["compliance", "content-writer", "insight", "store-coach"]
    assert get_effective_agents(_plan("trial"), "HQ") == []


def test_get_effective_agents_invalid_scene_fallback_med():
    # 非法 scene（含旧体系 health/medical/edu）fallback 到 MED 同档编排
    assert get_effective_agents(_plan("professional"), "health") == \
        SCENE_PLAN_AGENTS["MED"]["professional"]
    assert get_effective_agents(_plan("professional"), None) == \
        SCENE_PLAN_AGENTS["MED"]["professional"]


# ───────────────────── 门控：真实按 tenant.scene 取 ─────────────────────
def _ensure_db(tid, scene, plan_name):
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Tenant, Plan, Subscription
    db = SessionLocal()
    seed_plans(db)
    plan = db.query(Plan).filter_by(plan_name=plan_name).first()
    t = db.query(Tenant).filter_by(id=tid).first()
    if not t:
        t = Tenant(id=tid, name=tid, display_name=tid, scene=scene)
        db.add(t)
        db.flush()
    else:
        t.scene = scene
    sub = db.query(Subscription).filter_by(tenant_id=tid).first()
    if not sub:
        sub = Subscription(id=f"sub_{tid}", tenant_id=tid, plan_id=plan.id, status="active")
        db.add(sub)
    else:
        sub.plan_id = plan.id
        sub.status = "active"
    db.commit()
    db.close()


def test_gateway_honors_tenant_scene_retail(monkeypatch):
    """RETAIL 专业版：fortune 放行、tongue 拦截（dynamic scene-based gate）。
    mock is_active 放行，聚焦验证「按 tenant.scene 动态取 agents」场景维度。"""
    import qihuang_platform.agent.deps as deps_mod
    monkeypatch.setattr(deps_mod, "is_active", lambda k: True)
    tid = "test_scene_retail"
    _ensure_db(tid, "RETAIL", "professional")
    req = SimpleNamespace(state=SimpleNamespace(tenant_id=tid))
    user = {"sub": "x"}

    # fortune 在 RETAIL 专业版编排内 → 放行
    dep_allow = require_agent_in_plan("fortune")
    asyncio.run(dep_allow(req, user))  # 不抛 = 放行

    # tongue 不在 RETAIL 专业版编排 → 403
    dep_deny = require_agent_in_plan("tongue")
    try:
        asyncio.run(dep_deny(req, user))
        raise AssertionError("RETAIL 专业版不含 tongue，应 403")
    except Exception as e:
        assert getattr(e, "status_code", None) == 403


def test_gateway_honors_tenant_scene_med_tongue_allowed(monkeypatch):
    """MED 专业版含 tongue → 放行（对照，证明 scene 维度生效）。"""
    import qihuang_platform.agent.deps as deps_mod
    monkeypatch.setattr(deps_mod, "is_active", lambda k: True)
    tid = "test_scene_med"
    _ensure_db(tid, "MED", "professional")
    req = SimpleNamespace(state=SimpleNamespace(tenant_id=tid))
    user = {"sub": "x"}
    dep = require_agent_in_plan("tongue")
    asyncio.run(dep(req, user))  # MED 专业版含 tongue → 放行
