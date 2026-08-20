"""
P1-B 活态化业务实证加权（回路三）— 数据源落地验证

数据源 = 8602 consult 引用日志（consult_attribution 表）。
验证链路：
  1. orchestrator 归因钩子把方剂名解析为 kg_id 落库（best-effort）。
  2. fetch_business_usage 按窗口内被采纳引用次数归一化为实证权重。
  3. collect_business_signals 翻开关后写入 KgFeedback(source='business')。
  4. aggregator 经 LIVING_BUSINESS_GAIN 放大 delta（端到端）。
"""
import asyncio
import importlib

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import ConsultAttribution
from qihuang_platform.living.models import KgFeedback


def _cleanup(db):
    db.query(ConsultAttribution).delete()
    db.query(KgFeedback).filter(KgFeedback.source == "business").delete()
    db.commit()


# ── orchestrator 归因钩子：方剂名 → kg_id 落库（mock 8601 resolve）──

class _F:
    def __init__(self, name): self.name = name

class _Syn:
    def __init__(self, name): self.name = name

class _Resp:
    def __init__(self, formulas, syndrome, partial):
        self.formulas = formulas
        self.syndrome = syndrome
        self.partial = partial
        self.session_id = "s1"

class _Req:
    store_id = "store1"


async def _fake_resolve(name):
    return {"matches": [{"kg_id": "kg-" + name, "labels": ["Formula"]}]}


def test_orchestrator_attribution(monkeypatch, client):
    """consult 成功后归因钩子应解析方剂名并写入 consult_attribution。"""
    import qihuang_platform.living.kg_write_client as kwc
    monkeypatch.setattr(kwc.kg_client, "resolve", _fake_resolve)

    from qihuang_platform.agent.health_advisor.orchestrator import HealthAdvisor
    ha = HealthAdvisor()
    db = SessionLocal()
    try:
        _cleanup(db)
        asyncio.run(ha._record_attribution(
            "tenant_default", _Req(),
            _Resp([_F("麻黄汤"), _F("桂枝汤")], _Syn("风寒表实证"), False),
            "tr1",
        ))
        rows = db.query(ConsultAttribution).all()
        assert len(rows) >= 2, [r.entity_name for r in rows]
        names = {r.entity_name for r in rows}
        assert "麻黄汤" in names and "桂枝汤" in names
        assert all(r.kg_id for r in rows)
        # 非 partial → adopted=True
        assert all(r.adopted for r in rows)
    finally:
        db.close()
        db = SessionLocal()
        try:
            _cleanup(db)
        finally:
            db.close()


# ── fetch_business_usage + collect_business_signals 端到端 ──

def test_business_signal_fetch_and_collect(monkeypatch, client):
    """5 次被采纳引用（除数5）→ 权重 1.0；翻开关后 collect 写出 business_use 信号。"""
    import qihuang_platform.living.business_signal as bs

    db = SessionLocal()
    try:
        _cleanup(db)
        for _ in range(5):
            db.add(ConsultAttribution(
                tenant_id="tenant_default", kg_id="kg-A", entity_name="麻黄汤",
                entity_type="formula", adopted=True))
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv("LIVING_BUSINESS_SIGNAL_ENABLED", "true")
    monkeypatch.setenv("LIVING_BIZ_WEIGHT_DIVISOR", "5")
    importlib.reload(bs)
    try:
        summary = asyncio.run(bs.collect_business_signals())
        assert summary.get("enabled") is True
        assert summary.get("signals_written") == 1, summary

        db = SessionLocal()
        try:
            fbs = db.query(KgFeedback).filter(
                KgFeedback.kg_id == "kg-A",
                KgFeedback.source == "business",
            ).all()
            assert len(fbs) == 1, [f.kg_id for f in fbs]
            assert fbs[0].feedback_type == "business_use"
            assert abs(fbs[0].business_weight - 1.0) < 1e-6
        finally:
            db.close()
    finally:
        monkeypatch.delenv("LIVING_BUSINESS_SIGNAL_ENABLED", raising=False)
        monkeypatch.delenv("LIVING_BIZ_WEIGHT_DIVISOR", raising=False)
        importlib.reload(bs)
        db = SessionLocal()
        try:
            _cleanup(db)
        finally:
            db.close()


def test_business_gain_amplifies(monkeypatch, client):
    """3 次引用/除数5 → weight 0.6；开启 LIVING_BUSINESS_GAIN=0.5 后放大 delta。"""
    import qihuang_platform.living.business_signal as bs
    import qihuang_platform.living.aggregator as agg

    class FakeKgClient:
        def __init__(self): self.batch_calls = []
        async def get_confidence(self, kg_id, target="node"): return 0.9
        async def batch_update_confidence(self, items):
            self.batch_calls.append(items)
            return {"updated": len(items)}

    db = SessionLocal()
    try:
        _cleanup(db)
        for _ in range(3):
            db.add(ConsultAttribution(
                tenant_id="tenant_default", kg_id="kg-B", entity_name="桂枝汤",
                entity_type="formula", adopted=True))
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv("LIVING_BUSINESS_SIGNAL_ENABLED", "true")
    monkeypatch.setenv("LIVING_BIZ_WEIGHT_DIVISOR", "5")
    importlib.reload(bs)
    try:
        asyncio.run(bs.collect_business_signals())
        # 激活增益
        monkeypatch.setenv("LIVING_BUSINESS_GAIN", "0.5")
        importlib.reload(agg)
        fake = FakeKgClient()
        monkeypatch.setattr(agg, "kg_client", fake)
        db = SessionLocal()
        try:
            summary = asyncio.run(agg.aggregate_feedback(db, client=fake))
            assert summary["items_written"] == 1, summary
            items = {it["kg_id"]: it["confidence_abs"] for it in fake.batch_calls[0]}
            # delta = 0.0003 * (1 + 0.5*0.6=1.3) = 0.00039; new_c = 0.9 + 0.00039 = 0.90039
            assert abs(items["kg-B"] - 0.90039) < 1e-3, items
        finally:
            db.close()
    finally:
        monkeypatch.delenv("LIVING_BUSINESS_SIGNAL_ENABLED", raising=False)
        monkeypatch.delenv("LIVING_BIZ_WEIGHT_DIVISOR", raising=False)
        monkeypatch.delenv("LIVING_BUSINESS_GAIN", raising=False)
        importlib.reload(bs)
        importlib.reload(agg)
        db = SessionLocal()
        try:
            _cleanup(db)
        finally:
            db.close()


def test_agent_business_signals_endpoint(client, admin_token):
    """④ 活态 P1-B 前端面板的后端数据端点：聚合 consult_attribution（排除 pending 噪声）。"""
    from datetime import datetime, timezone
    H = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    try:
        _cleanup(db)
        now = datetime.now(timezone.utc)
        for _ in range(3):
            db.add(ConsultAttribution(
                tenant_id="tenant_default", kg_id="kg-a", entity_name="麻黄汤",
                entity_type="formula", adopted=True, consulted_at=now))
        for _ in range(2):
            db.add(ConsultAttribution(
                tenant_id="tenant_default", kg_id="kg-b", entity_name="桂枝汤",
                entity_type="formula", adopted=True, consulted_at=now))
        # pending 解析噪声应被排除
        db.add(ConsultAttribution(
            tenant_id="tenant_default", kg_id="pending:xyz", entity_name=None,
            entity_type=None, adopted=False, consulted_at=now))
        db.commit()
    finally:
        db.close()

    r = client.get("/admin/v1/agent-business-signals", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["totals"]["references"] == 5, d["totals"]
    assert d["totals"]["distinct_kg"] == 2, d["totals"]
    assert d["top"][0]["kg_id"] == "kg-a"
    assert d["top"][0]["ref_count"] == 3
    assert d["top"][1]["kg_id"] == "kg-b"

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()
