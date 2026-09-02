"""
tests/test_billing_reconcile.py — 真计费对账模块单测（本地 SQLite，不连生产）

覆盖：aggregate_calllog 聚合 / reconcile_tenant 漏结算检测 / ensure_usage_snapshot_for 补漏 /
detect_calllog_anomalies 裸0+双写 / reconcile_all 全租户遍历。
"""
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Base, Tenant, CallLog, Order, Bill
from qihuang_platform.billing.reconcile import (
    aggregate_calllog,
    reconcile_tenant,
    detect_calllog_anomalies,
    ensure_usage_snapshot_for,
    reconcile_all,
)

PERIOD = "2026-09"
_TIDS = ["t_rec_1", "t_rec_2"]


def _dt(day, h=12):
    return datetime(2026, 9, day, h, 0, 0, tzinfo=timezone.utc)


def _setup():
    db = SessionLocal()
    Base.metadata.create_all(db.bind)
    for tid in _TIDS:
        db.merge(Tenant(id=tid, name=tid, display_name=tid,
                        scene="health", status="active", extra={}))
    db.query(CallLog).filter(CallLog.tenant_id.in_(_TIDS)).delete()
    db.query(Order).filter(Order.tenant_id.in_(_TIDS)).delete()
    db.query(Bill).filter(Bill.tenant_id.in_(_TIDS)).delete()
    db.commit()
    return db


def _add_call(db, tid, cost, tokens=10, status=200, trace_id=None, day=15):
    db.add(CallLog(
        tenant_id=tid,
        endpoint="/api/v1/agent/health-assistant/consult",
        method="POST",
        status_code=status,
        tokens_used=tokens,
        cost_cents=cost,
        trace_id=trace_id,
        timestamp=_dt(day),
    ))


def test_aggregate_calllog_sums():
    db = _setup()
    _add_call(db, "t_rec_1", 100, 20, trace_id="a1")
    _add_call(db, "t_rec_1", 50, 10, trace_id="a2")
    db.commit()
    agg = aggregate_calllog(db, "t_rec_1", PERIOD)
    assert agg["calls"] == 2
    assert agg["tokens"] == 30
    assert agg["cost_cents"] == 150.0
    db.close()


def test_reconcile_detects_missing_usage_order():
    db = _setup()
    _add_call(db, "t_rec_1", 120, 24, trace_id="b1")
    db.commit()
    res = reconcile_tenant(db, "t_rec_1", PERIOD)
    assert not res["healthy"]
    assert any(g["type"] == "missing_usage_order" for g in res["gaps"])
    db.close()


def test_ensure_snapshot_fixes_reconcile():
    db = _setup()
    _add_call(db, "t_rec_1", 120, 24, trace_id="c1")
    db.commit()
    fx = ensure_usage_snapshot_for(db, "t_rec_1", PERIOD)
    assert fx.get("ok") and not fx.get("skipped")
    db.commit()
    res = reconcile_tenant(db, "t_rec_1", PERIOD)
    assert res["healthy"], res["gaps"]
    assert res["usage_order"]["cost_cents"] == 120
    db.close()


def test_detect_bare_zero_and_double_write():
    db = _setup()
    # 裸0：成功 agent 调用 cost<=0（引擎漏回传 usage + 兜底未生效）
    _add_call(db, "t_rec_1", 0, 0, status=200, trace_id="z1")
    # 双写嫌疑：同 trace_id 两条 CallLog
    _add_call(db, "t_rec_1", 30, 5, trace_id="dup1", day=10)
    _add_call(db, "t_rec_1", 30, 5, trace_id="dup1", day=11)
    db.commit()
    an = detect_calllog_anomalies(db, "t_rec_1", PERIOD)
    assert an["bare_zero"]["count"] == 1
    assert an["double_write_suspect"]["trace_ids_with_dup"] == 1
    assert an["double_write_suspect"]["count"] == 2
    db.close()


def test_reconcile_all_iterates_tenants():
    db = _setup()
    _add_call(db, "t_rec_1", 100, trace_id="r1")
    _add_call(db, "t_rec_2", 200, trace_id="r2")
    db.commit()
    out = reconcile_all(db, PERIOD, fix=False)
    tids = {t["tenant_id"] for t in out["tenants"]}
    assert {"t_rec_1", "t_rec_2"} <= tids
    assert out["summary"]["total"] >= 2
    assert out["summary"]["with_gaps"] >= 2  # 两租户都漏结算
    db.close()


def test_reconcile_cost_drift_detected():
    """CallLog 费用与已存在 usage 单金额偏差超阈值 → 报 cost_drift_vs_usage_order"""
    db = _setup()
    _add_call(db, "t_rec_1", 100, trace_id="d1")
    db.commit()
    fx = ensure_usage_snapshot_for(db, "t_rec_1", PERIOD)
    db.commit()
    assert fx.get("ok")
    # 再补一笔调用，使 CallLog 真值偏离 usage 单（单已固定 100）
    _add_call(db, "t_rec_1", 500, trace_id="d2")
    db.commit()
    res = reconcile_tenant(db, "t_rec_1", PERIOD)
    assert any(g["type"] == "cost_drift_vs_usage_order" for g in res["gaps"])
    db.close()
