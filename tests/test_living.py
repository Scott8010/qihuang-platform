"""
活态化 P2 反馈闭环 — 测试套件
覆盖: 反馈提交 / 统计 / confidence 查询 / 聚合回写(confidence+纠偏+缺口) 全链路

8601 写通道用 FakeKgClient mock（不依赖真实 8601），专注验证 8602 侧聚合逻辑与路由。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.aggregator import (
    aggregate_feedback, process_corrections, process_gaps,
)
import importlib
router_mod = importlib.import_module("qihuang_platform.living.router")
agg_mod = importlib.import_module("qihuang_platform.living.aggregator")


class FakeKgClient:
    """mock 8601 /kg/api 写通道：记录调用、返回预设 confidence。"""

    def __init__(self, conf_map=None):
        self.conf_map = conf_map or {}
        self.batch_calls = []
        self.correction_calls = []
        self.gap_calls = []

    async def get_confidence(self, kg_id, target="node"):
        return self.conf_map.get(kg_id, 0.8)

    async def batch_update_confidence(self, items):
        self.batch_calls.append(items)
        return {"updated": len(items), "failed": [], "skipped": 0}

    async def apply_correction(self, kg_id, field, new_value, expert_id, reason):
        self.correction_calls.append((kg_id, field, new_value, expert_id, reason))
        return {"version_id": "v1", "kg_id": kg_id, "old": None, "new": new_value}

    async def mark_gap(self, kg_id_a, kg_id_b, conflict_type, evidence):
        self.gap_calls.append((kg_id_a, kg_id_b, conflict_type, evidence))
        return {"gap_id": "g1"}


def _add_feedback(db, **kw):
    fb = KgFeedback(**kw)
    db.add(fb)
    db.commit()
    return fb


def _cleanup(db):
    db.query(KgFeedback).filter(KgFeedback.kg_id.like("kg-test-%")).delete()
    db.query(KgFeedback).filter(KgFeedback.kg_id.like("pending:%")).delete()
    db.commit()


# ───────────────────────────────────────────────────────────
# 1) 反馈提交 + 统计（HTTP）
# ───────────────────────────────────────────────────────────

def test_feedback_submit_and_stats(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/living/feedback", headers=headers, json={
        "kg_id": "kg-test-submit", "feedback_type": "like", "comment": "好用",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["feedback_id"]
    assert r.json()["data"]["type"] == "like"

    # 非法类型应被拒
    r2 = client.post("/api/v1/living/feedback", headers=headers, json={
        "kg_id": "kg-test-submit", "feedback_type": "bogus",
    })
    assert r2.status_code == 400

    # 未带 token 应 401
    r3 = client.post("/api/v1/living/feedback", json={
        "kg_id": "kg-test-submit", "feedback_type": "like",
    })
    assert r3.status_code == 401

    # 统计
    r4 = client.get("/api/v1/living/feedback/stats", headers=headers)
    assert r4.status_code == 200
    assert r4.json()["data"]["by_type"].get("like", 0) >= 1

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


# ───────────────────────────────────────────────────────────
# 2) 实时 confidence 查询（mock 8601）
# ───────────────────────────────────────────────────────────

def test_confidence_endpoint(client, admin_token, monkeypatch):
    fake = FakeKgClient(conf_map={"kg-test-conf": 0.88})
    monkeypatch.setattr(router_mod, "kg_client", fake)

    r = client.get("/api/v1/living/kg/kg-test-conf/confidence")
    assert r.status_code == 200
    assert r.json()["data"]["confidence"] == 0.88


# ───────────────────────────────────────────────────────────
# 3) 聚合回写核心闭环（confidence delta 计算）
# ───────────────────────────────────────────────────────────

def test_aggregate_feedback(client, monkeypatch):
    fake = FakeKgClient(conf_map={"kg-test-a": 0.9, "kg-test-b": 0.9})
    monkeypatch.setattr(agg_mod, "kg_client", fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        # kg-test-a: 1 adopt + 3 like → delta = 0.001 + 3*0.0005 = 0.0025
        _add_feedback(db, kg_id="kg-test-a", feedback_type="adopt")
        for _ in range(3):
            _add_feedback(db, kg_id="kg-test-a", feedback_type="like")
        # kg-test-b: 2 dislike → delta = -0.01
        for _ in range(2):
            _add_feedback(db, kg_id="kg-test-b", feedback_type="dislike")
        # 一个已聚合的脏行（不应被二次处理）
        old = _add_feedback(db, kg_id="kg-test-old", feedback_type="like")
        old.aggregated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)
        db.commit()

        summary = __import__("asyncio").run(aggregate_feedback(db, client=fake))
    finally:
        db.close()

    # 断言（含模型信任杠杆，允许 1e-3 精度）
    assert summary["items_written"] == 2, summary
    assert summary["kg_ids_processed"] == 2
    items = {it["kg_id"]: it["confidence_abs"] for it in fake.batch_calls[0]}
    assert abs(items["kg-test-a"] - 0.9025) < 1e-3, items
    assert abs(items["kg-test-b"] - 0.89) < 1e-3, items

    # 已聚合行已标记
    db = SessionLocal()
    try:
        a = db.query(KgFeedback).filter_by(kg_id="kg-test-a").first()
        assert a.aggregated_at is not None
        _cleanup(db)
    finally:
        db.close()


# ───────────────────────────────────────────────────────────
# 4) 专家纠偏 + 缺口 处理通道
# ───────────────────────────────────────────────────────────

def test_process_corrections_and_gaps(client, monkeypatch):
    fake = FakeKgClient()
    monkeypatch.setattr(agg_mod, "kg_client", fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        _add_feedback(db, kg_id="kg-test-c", feedback_type="expert_correction",
                      field="confidence", new_value=json.dumps(0.77),
                      expert_id="exp1", reason="临床复核")
        _add_feedback(db, kg_id="kg-test-d", feedback_type="gap",
                      kg_id_b="kg-test-e", conflict_type="contradiction",
                      evidence="两说相悖")
        db.commit()

        c = __import__("asyncio").run(process_corrections(db, client=fake))
        g = __import__("asyncio").run(process_gaps(db, client=fake))
    finally:
        db.close()

    assert c["corrections_processed"] == 1, c
    assert g["gaps_processed"] == 1, g
    assert fake.correction_calls[0][0] == "kg-test-c"
    assert fake.correction_calls[0][2] == 0.77  # new_value 还原
    assert fake.gap_calls[0][0] == "kg-test-d"

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


# ───────────────────────────────────────────────────────────
# 5) 端到端：HTTP 触发 /aggregate（管理员 + mock 8601）
# ───────────────────────────────────────────────────────────

def test_aggregate_http_endpoint(client, admin_token, monkeypatch):
    fake = FakeKgClient(conf_map={"kg-test-h": 0.9})
    monkeypatch.setattr(agg_mod, "kg_client", fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        _add_feedback(db, kg_id="kg-test-h", feedback_type="expert_adopt")
        db.commit()
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/living/aggregate", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["confidence"]["items_written"] == 1
    assert data["corrections"]["corrections_processed"] == 0
    assert abs(fake.batch_calls[0][0]["confidence_abs"] - 0.91) < 1e-3

    # 非管理员应 401
    r2 = client.post("/api/v1/living/aggregate")
    assert r2.status_code == 401

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


# ───────────────────────────────────────────────────────────
# 6) 待补全节点（pending: 前缀）反馈链路
# ───────────────────────────────────────────────────────────

def test_pending_feedback(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/living/feedback", headers=headers, json={
        "kg_id": "pending:卷柏",
        "feedback_type": "adopt",
        "entity_name": "卷柏",
        "entity_type": "herb",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["kg_id"] == "pending:卷柏"

    # 列表中应展示 entity_name / pending 标志
    r2 = client.get("/api/v1/living/feedback?status=all", headers=headers)
    assert r2.status_code == 200
    items = [it for it in r2.json()["data"]["items"] if it.get("kg_id") == "pending:卷柏"]
    assert len(items) >= 1
    assert items[0]["pending"] is True
    assert items[0]["entity_name"] == "卷柏"

    # 聚合应跳过 pending 节点，不回写 8601
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


# ───────────────────────────────────────────────────────────
# 7) 回路三（业务实证加权）技术链路：business_use 信号加权验证
# ───────────────────────────────────────────────────────────

def test_business_signal_weights_delta(monkeypatch):
    """回路三激活（LIVING_BUSINESS_GAIN>0）后，business_use 信号应放大 delta。"""
    import importlib
    import qihuang_platform.living.aggregator as agg

    monkeypatch.setenv("LIVING_BUSINESS_GAIN", "0.5")
    importlib.reload(agg)
    try:
        fake = FakeKgClient(conf_map={"kg-test-biz": 0.9})
        monkeypatch.setattr(agg, "kg_client", fake)

        db = SessionLocal()
        try:
            _cleanup(db)
            _add_feedback(db, kg_id="kg-test-biz", feedback_type="business_use",
                          source="business", business_weight=0.5)
            summary = __import__("asyncio").run(agg.aggregate_feedback(db, client=fake))
        finally:
            db.close()

        assert summary["items_written"] == 1, summary
        items = {it["kg_id"]: it["confidence_abs"] for it in fake.batch_calls[0]}
        # 基础 delta = 0.0003 * multiplier(1+0.5*0.5=1.25) = 0.000375
        # new_c = 0.9 + 0.000375 = 0.900375
        assert abs(items["kg-test-biz"] - 0.900375) < 1e-3, items
    finally:
        # 恢复默认增益（0.0），避免影响其他测试 / 仿真期生产
        monkeypatch.delenv("LIVING_BUSINESS_GAIN", raising=False)
        importlib.reload(agg)
        db = SessionLocal()
        try:
            _cleanup(db)
        finally:
            db.close()
