"""
内容合规审核 Agent 能力 · 单测（L1 底座 + L2 引擎 + 回写 + 对齐 + 租户隔离）

全部本地可验证，不依赖服务器/Neo4j/真实 LLM：
  - L1 KB：种子完整性、检索召回、条款溯源、实体对齐
  - L2 引擎：L0 硬红线拦截、L2 语义补充、免责语境不误判、三轨融合
  - 回写：material_key 幂等、feedback 状态流转、四态看板、租户行级隔离
  - Neo4j 后端：懒加载（无 neo4j 环境时 skip，不报错）
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qihuang_platform.agent.compliance.engine_l2 import ComplianceEngineL2
from qihuang_platform.agent.compliance.kb import (
    ComplianceKB, JsonlBackend, Neo4jBackend, rules_to_clauses,
)
from qihuang_platform.agent.compliance.schema import ComplianceClause
from qihuang_platform.agent.compliance.store import ComplianceStore

_SEED_SRC = os.path.join(
    os.path.dirname(__file__), "..", "qihuang_platform", "agent",
    "compliance", "seed", "compliance_clauses.jsonl",
)
_SEED_SRC = os.path.abspath(_SEED_SRC)
_RULES_PATH = r"C:/Users/Administrator/WorkBuddy/HealthBridge/hb-compliance-guard/rules.py"


@pytest.fixture
def tmp_env():
    """临时种子(复制真种子) + 临时存储 + 注入式引擎。"""
    d = tempfile.mkdtemp()
    seed = os.path.join(d, "seed.jsonl")
    store = os.path.join(d, "materials.jsonl")
    shutil.copy(_SEED_SRC, seed)
    yield {"seed": seed, "store": store, "dir": d}
    shutil.rmtree(d, ignore_errors=True)


def make_engine(seed, store, violations=None):
    """构造注入式引擎：fake llm 可返回指定 L2 违规。"""
    def fake_llm(prompt, system):
        return {"violations": violations or [], "summary": "ok"}
    return ComplianceEngineL2(
        kb=ComplianceKB(JsonlBackend(seed)),
        store=ComplianceStore(store),
        llm_call=fake_llm,
    )


def make_fake_llm(violations):
    def fake(prompt, system):
        return {"violations": violations, "summary": "ok"}
    return fake


# ════════════════ L1 底座 ════════════════
def test_kb_seed_count(tmp_env):
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    assert asyncio.run(kb.count()) == 32


def test_kb_retrieve_recall(tmp_env):
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    hits = asyncio.run(kb.retrieve("本品包治百病、药到病除、根治百病", top_k=8))
    ids = [c.clause_id for c in hits]
    assert "HC-B-011" in ids  # 包治百病/药到病除/根治 关键词命中


def test_kb_b012_b015_keywords_recall(tmp_env):
    """验证 HC-B-012(量化疗效) 和 HC-B-015(时效承诺) 补齐 keywords 后能被 L1 召回。"""
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    # HC-B-012：量化疗效数据
    hits = asyncio.run(kb.retrieve("本品有效率达95%，治愈率超过80%", top_k=8))
    ids = [c.clause_id for c in hits]
    assert "HC-B-012" in ids, f"HC-B-012 未被召回，实际召回: {ids}"
    # HC-B-015：具体时间承诺
    hits2 = asyncio.run(kb.retrieve("一个疗程见效，三天就能改善", top_k=8))
    ids2 = [c.clause_id for c in hits2]
    assert "HC-B-015" in ids2, f"HC-B-015 未被召回，实际召回: {ids2}"


def test_kb_source_ref(tmp_env):
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    c = asyncio.run(kb.get("HC-F-052"))
    assert c is not None
    assert "广告法" in c.source_ref
    # 毒性药材实体对齐桥接
    assert "何首乌" in c.aligns_to


def test_kb_aligned_entities(tmp_env):
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    aligned = asyncio.run(kb.aligned_entities("本方含何首乌与朱砂"))
    clause_ids = {a["clause_id"] for a in aligned}
    assert "HC-F-052" in clause_ids


def test_rules_to_clauses_shape():
    sample = [{
        "rule_id": "HC-X-001", "category": "A", "severity": "RED",
        "effective_action": "block", "confidence": 0.97,
        "patterns": ["最好的", "最佳"], "title": "「最」字类绝对化，违反《广告法》第九条第(三)项",
        "suggested_replace": "改为相对描述",
    }]
    cs = rules_to_clauses(sample)
    assert len(cs) == 1
    c = cs[0]
    assert isinstance(c, ComplianceClause)
    assert c.kg_id  # 确定性 UUID
    assert c.source_ref.startswith("《广告法》")
    assert c.keywords == ["最好的", "最佳"]


# ════════════════ L2 引擎 ════════════════
def test_l0_hard_redline(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    body = asyncio.run(eng.analyze(
        "我们包治百病、药到病除，根治一切慢性病", "朋友圈", "wechat", "store_A"))
    assert body["state"] == "违规拦截"
    layers = {h["clause_id"]: h["layer"] for h in body["hits"]}
    assert layers.get("HC-B-011") == "L0"


def test_l2_semantic_supplement(tmp_env):
    # 直接验证 L2 融合逻辑（隔离 L0 干扰）：L0 未命中、L2 产出一条 L1 条款库内
    # ORANGE 违规，且结构化字段（severity/explanation/source_ref）完整落地。
    # 选 HC-A-004（ORANGE「第一」类，L0 用组合正则可能漏「全国第一品牌」等变体，
    # 正是 L2 语义补充的典型场景）。
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    kb = ComplianceKB(JsonlBackend(tmp_env["seed"]))
    c = asyncio.run(kb.get("HC-A-004"))
    assert c is not None
    clause_map = {c.clause_id: c}
    l2_v = [{
        "clause_id": "HC-A-004", "severity": "ORANGE", "confidence": 0.9,
        "explanation": "绝对化用语「第一」", "suggested_replace": "改为相对描述",
    }]
    merged = eng._merge([], l2_v, clause_map)
    assert len(merged) == 1
    hit = merged[0]
    assert hit["clause_id"] == "HC-A-004"
    assert hit["layer"] == "L2"
    assert hit["severity"] == "ORANGE"
    assert hit["explanation"] == "绝对化用语「第一」"
    assert hit["source_ref"].startswith("《广告法》")
    assert hit["suggested_replace"] == "改为相对描述"


def test_exempt_context_not_blocked(tmp_env):
    # 免责声明不应误判
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    body = asyncio.run(eng.analyze(
        "本品不能替代药物，具体请遵医嘱", "详情页", "store_page", "store_C"))
    assert body["state"] != "违规拦截"


def test_aligned_in_body(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    body = asyncio.run(eng.analyze(
        "艾灸拔罐调理，孕妇禁用", "朋友圈", "wechat", "store_D"))
    ents = {a["clause_id"] for a in body["aligned_entities"]}
    assert "HC-E-041" in ents  # 拔罐/艾灸 对齐到 E-041


# ════════════════ 回写 / 看板 / 隔离 ════════════════
def test_feedback_state_transition(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    body = asyncio.run(eng.analyze(
        "包治百病根治百病", "朋友圈", "wechat", "store_E"))
    mid = body["material_id"]
    assert body["state"] == "违规拦截"
    res = asyncio.run(eng.feedback(mid, "keep", "released", "人工确认无误", "op1"))
    assert res is not None
    assert res["state"] == "已通过"
    assert res["feedback_log"][0]["decision"] == "keep"


def test_feedback_not_found(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    res = asyncio.run(eng.feedback("MAT-NOPE", "keep", "released", None, "op"))
    assert res is None


def test_material_key_idempotent(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    a = asyncio.run(eng.analyze("文案A", "海报", "wechat", "store_F", material_key="promo_x"))
    b = asyncio.run(eng.analyze("文案A改了措辞", "海报", "wechat", "store_F", material_key="promo_x"))
    assert a["material_id"] == b["material_id"]  # 同业务键覆盖同一条


def test_tenant_row_isolation(tmp_env):
    eng = make_engine(tmp_env["seed"], tmp_env["store"])
    asyncio.run(eng.analyze("包治百病", "朋友圈", "wechat", "store_A"))
    asyncio.run(eng.analyze("包治百病", "朋友圈", "wechat", "store_B"))
    da = asyncio.run(eng.dashboard(institution_id="store_A"))
    db = asyncio.run(eng.dashboard(institution_id="store_B"))
    assert da["total"] == 1 and db["total"] == 1
    assert da["states"]["违规拦截"] == 1


# ════════════════ Neo4j 后端（懒加载） ════════════════
def test_neo4j_backend_lazy():
    b = Neo4jBackend()  # 构造不触发 neo4j import（懒加载在 _get_driver）
    assert b is not None
    try:
        asyncio.run(b.load_all())
    except Exception:
        pytest.skip("无 Neo4j 环境，跳过真实加载（验证懒加载不报错即达标）")


# ════════════════ Router 集成（门店送审工作台形态） ════════════════
def test_router_scan_and_feedback(tmp_env):
    from qihuang_platform.agent.compliance import engine_l2
    from qihuang_platform.agent.compliance.router import router as compliance_router
    from qihuang_platform.gateway.deps import get_current_user, get_current_admin

    # 让单例用临时存储，避免污染种子目录
    engine_l2.compliance_engine.store = ComplianceStore(tmp_env["store"])
    os.environ["COMPLIANCE_RULES_PATH"] = _RULES_PATH

    app = FastAPI()
    app.middleware("http")(_set_tenant)
    app.include_router(compliance_router, prefix="/api/v1/agent")

    def fake_user():
        return {"sub": "u1"}
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_current_admin] = fake_user  # 测试环境模拟管理员

    client = TestClient(app)
    r = client.post("/api/v1/agent/compliance/scan", json={
        "text": "包治百病、药到病除，根治一切", "store_id": "store_Z",
        "material_type": "朋友圈", "port": "wechat", "material_key": "promo_z",
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["material_id"].startswith("MAT-")
    assert data["state"] == "违规拦截"
    assert data["store_id"] == "store_Z"
    assert data["tenant_id"] == "t1"  # 中间件注入

    mid = data["material_id"]
    r2 = client.post("/api/v1/agent/compliance/feedback", json={
        "material_id": mid, "decision": "keep", "action_taken": "released",
    })
    assert r2.status_code == 200
    assert r2.json()["data"]["state"] == "已通过"


def test_router_feedback_requires_admin(tmp_env):
    """非管理员调 feedback 应返回 403（RBAC 权限分级验证）。"""
    from qihuang_platform.agent.compliance import engine_l2
    from qihuang_platform.agent.compliance.router import router as compliance_router
    from qihuang_platform.gateway.deps import get_current_user, get_current_admin
    from qihuang_platform.gateway.deps import get_current_admin as real_admin

    engine_l2.compliance_engine.store = ComplianceStore(tmp_env["store"])
    os.environ["COMPLIANCE_RULES_PATH"] = _RULES_PATH

    app = FastAPI()
    app.middleware("http")(_set_tenant)
    app.include_router(compliance_router, prefix="/api/v1/agent")

    # 只 override get_current_user（模拟普通用户），不 override get_current_admin
    # → get_current_admin 走真实逻辑，但 request.state.roles 未设 → 403
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    # get_current_admin 不 override，走真实逻辑
    # 但因为 get_current_user 被 override，不会设 request.state.roles
    # 需要在中间件里模拟设 roles 为空
    async def _set_tenant_no_admin(request, call_next):
        request.state.tenant_id = "t1"
        request.state.roles = []  # 普通用户无 admin 角色
        return await call_next(request)
    app.middleware("http")(_set_tenant_no_admin)

    client = TestClient(app)
    r = client.post("/api/v1/agent/compliance/feedback", json={
        "material_id": "MAT-FAKE", "decision": "keep", "action_taken": "released",
    })
    assert r.status_code == 403


async def _set_tenant(request, call_next):
    request.state.tenant_id = "t1"
    return await call_next(request)
