"""
活态化 B · 回路三（业务实证加权）+ 审核→图谱回流桥 — 测试套件

验证：
  1. emit_business_feedback 写 business 来源行 + 24h 去重
  2. bridge_compliance_scan 命中实体 → business_use 正加权
  3. bridge_compliance_feedback override/escalate → expert_reject 负加权（错知识回流）
  4. GAIN=0.5 激活后 business_use 信号经聚合放大回写图谱

8601 解析与回写均用 FakeKgClient mock（不依赖真实 8601）。
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(__file__))

import importlib
import pytest
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
import qihuang_platform.living.ingest as ingest_mod
import qihuang_platform.living.aggregator as agg_mod


class FakeKgClient:
    """mock 8601：resolve 按预设名映射 kg_id；batch 记录调用。"""

    def __init__(self, resolve_map=None, conf_map=None):
        self.resolve_map = resolve_map or {}
        self.conf_map = conf_map or {}
        self.batch_calls = []

    async def resolve(self, name):
        kg_id = self.resolve_map.get(name)
        if kg_id:
            return {"matches": [{"kg_id": kg_id, "labels": ["Herb"]}]}
        return {"matches": []}

    async def get_confidence(self, kg_id, target="node"):
        return self.conf_map.get(kg_id, 0.9)

    async def batch_update_confidence(self, items):
        self.batch_calls.append(items)
        return {"updated": len(items), "failed": [], "skipped": 0}


def _cleanup(db):
    db.query(KgFeedback).filter(KgFeedback.kg_id.like("kg-biz-%")).delete()
    db.query(KgFeedback).filter(KgFeedback.kg_id.like("kg-bridge-%")).delete()
    db.commit()


# ───────────────────────────────────────────────────────────
# 1) emit_business_feedback 写行 + 24h 去重
# ───────────────────────────────────────────────────────────

def test_emit_business_feedback_and_dedup():
    db = SessionLocal()
    try:
        _cleanup(db)
        row1 = ingest_mod.emit_business_feedback(
            db, "kg-biz-1", "business_use",
            business_weight=1.0, tenant_id="t1", store_id="s1",
            comment="合规送审命中实体「艾灸」",
        )
        assert row1 is not None
        assert row1.source == "business"
        assert row1.business_weight == 1.0
        assert row1.feedback_type == "business_use"
        assert "艾灸" in (row1.comment or "")
        assert "s1" in (row1.comment or "")

        # 24h 内同 kg_id+同类型+source='business' → 跳过
        row2 = ingest_mod.emit_business_feedback(
            db, "kg-biz-1", "business_use", business_weight=1.0,
        )
        assert row2 is None

        # 不同类型不冲突
        row3 = ingest_mod.emit_business_feedback(
            db, "kg-biz-1", "expert_reject", business_weight=1.0,
        )
        assert row3 is not None
        assert row3.feedback_type == "expert_reject"
    finally:
        _cleanup(db)
        db.close()


# ───────────────────────────────────────────────────────────
# 2) bridge_compliance_scan 命中实体 → business_use 正加权
# ───────────────────────────────────────────────────────────

def test_bridge_compliance_scan(monkeypatch):
    fake = FakeKgClient(resolve_map={"艾灸": "kg-bridge-aijiu", "拔罐": "kg-bridge-baguan"})
    monkeypatch.setattr(ingest_mod, "kg_client", fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        entities = [
            {"clause_id": "A1", "entity": "艾灸", "severity": "ORANGE"},
            {"clause_id": "B2", "entity": "拔罐", "severity": "YELLOW"},
            {"clause_id": "A1", "entity": "艾灸", "severity": "ORANGE"},  # 重复实体应去重
        ]
        summary = bridge_compliance_scan_call(
            db, entities, tenant_id="t1", store_id="s1",
        )
        assert summary["emitted"] == 2, summary
        assert summary["skipped"] == 0
        assert summary["errors"] == 0

        # 验证落库两行 business_use
        rows = db.query(KgFeedback).filter(
            KgFeedback.source == "business",
            KgFeedback.feedback_type == "business_use",
        ).all()
        assert len(rows) == 2
        kg_ids = {r.kg_id for r in rows}
        assert kg_ids == {"kg-bridge-aijiu", "kg-bridge-baguan"}
    finally:
        _cleanup(db)
        db.close()


# ───────────────────────────────────────────────────────────
# 3) bridge_compliance_feedback override/escalate → expert_reject
# ───────────────────────────────────────────────────────────

def test_bridge_compliance_feedback_override(monkeypatch):
    fake = FakeKgClient(resolve_map={"朱砂": "kg-bridge-zhusha"})
    monkeypatch.setattr(ingest_mod, "kg_client", fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        entities = [{"clause_id": "C1", "entity": "朱砂", "severity": "RED"}]
        # override（强制拦截疑错知识）→ 回流 expert_reject
        s1 = bridge_compliance_feedback_call(
            db, entities, "override", tenant_id="t1", store_id="s9",
        )
        assert s1["emitted"] == 1, s1

        rows = db.query(KgFeedback).filter(
            KgFeedback.source == "business",
            KgFeedback.feedback_type == "expert_reject",
        ).all()
        assert len(rows) == 1
        assert rows[0].kg_id == "kg-bridge-zhusha"

        # keep（正常放行）→ 不回流
        s2 = bridge_compliance_feedback_call(
            db, entities, "keep", tenant_id="t1", store_id="s9",
        )
        assert s2["emitted"] == 0
        assert s2.get("note") == "no_bridge_decision"
    finally:
        _cleanup(db)
        db.close()


# ───────────────────────────────────────────────────────────
# 4) GAIN=0.5 激活后 business_use 信号经聚合放大回写
# ───────────────────────────────────────────────────────────

def test_business_signal_amplified_through_bridge(monkeypatch):
    """完整路径：emit(business_use, weight=0.5) → 聚合(GAIN=0.5) → 0.9+0.000375。"""
    monkeypatch.setenv("LIVING_BUSINESS_GAIN", "0.5")
    importlib.reload(agg_mod)
    try:
        fake = FakeKgClient(conf_map={"kg-biz-gain": 0.9})
        monkeypatch.setattr(agg_mod, "kg_client", fake)

        db = SessionLocal()
        try:
            _cleanup(db)
            ingest_mod.emit_business_feedback(
                db, "kg-biz-gain", "business_use", business_weight=0.5,
            )
            summary = asyncio.run(agg_mod.aggregate_feedback(db, client=fake))
            assert summary["items_written"] == 1, summary
            items = {it["kg_id"]: it["confidence_abs"] for it in fake.batch_calls[0]}
            # delta = 0.0003 * (1 + 0.5*0.5=1.25) = 0.000375 → 0.900375
            assert abs(items["kg-biz-gain"] - 0.900375) < 1e-3, items
        finally:
            _cleanup(db)
            db.close()
    finally:
        monkeypatch.delenv("LIVING_BUSINESS_GAIN", raising=False)
        importlib.reload(agg_mod)


# ───────────────────────────────────────────────────────────
# 异步桥接函数的同步包装（pytest 同步用例调用）
# ───────────────────────────────────────────────────────────

def bridge_compliance_scan_call(db, entities, tenant_id=None, store_id=None):
    return asyncio.run(ingest_mod.bridge_compliance_scan(
        db, entities, tenant_id=tenant_id, store_id=store_id))


def bridge_compliance_feedback_call(db, entities, decision, tenant_id=None, store_id=None):
    return asyncio.run(ingest_mod.bridge_compliance_feedback(
        db, entities, decision, tenant_id=tenant_id, store_id=store_id))
