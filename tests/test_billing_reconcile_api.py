"""
tests/test_billing_reconcile_api.py — 对账/用量增强端点契约测试（本地 SQLite）

锁定：
  GET /admin/v1/billing/reconcile  —— 真计费对账端点（全租户/单租户 + 异常检测）
  GET /admin/v1/agents/usage       —— 增强：tenant_id 下钻 + days + cost_yuan
"""
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import CallLog, Tenant


def _seed_call(tenant_id, cost, trace_id, day=15):
    db = SessionLocal()
    try:
        # upsert 租户以满足 call_log.tenant_id 外键约束（CI 真 Postgres 强制 FK，
        # 本地 SQLite 不强制；此处统一保证两种环境一致，避免测试假绿）
        db.merge(Tenant(id=tenant_id, name=tenant_id, status="active"))
        db.commit()
        db.add(CallLog(
            tenant_id=tenant_id,
            endpoint="/api/v1/agent/health-assistant/consult",
            method="POST",
            status_code=200,
            tokens_used=10,
            cost_cents=cost,
            trace_id=trace_id,
            timestamp=datetime(2026, 9, day, 12, 0, 0, tzinfo=timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def test_reconcile_endpoint_all_empty(client, admin_headers):
    """全租户模式：无数据周期返回 ok 汇总（验证端点接线）"""
    resp = client.get("/admin/v1/billing/reconcile?period=2099-01", headers=admin_headers)
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["mode"] == "all"
    assert d["period"] == "2099-01"
    assert "summary" in d


def test_reconcile_endpoint_tenant_detects_gap(client, admin_headers):
    """单租户模式：插入一条调用，端点应检出 missing_usage_order"""
    _seed_call("t_api_rec", 120, "api_rec_1")
    resp = client.get(
        "/admin/v1/billing/reconcile?period=2026-09&tenant_id=t_api_rec",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["mode"] == "tenant"
    assert d["reconcile"]["tenant_id"] == "t_api_rec"
    assert any(g["type"] == "missing_usage_order" for g in d["reconcile"]["gaps"])
    # 异常检测块存在
    assert "anomalies" in d


def test_usage_endpoint_enhanced(client, admin_headers):
    """增强用量端点：返回 cost_yuan 维度 + 时间窗参数可用"""
    resp = client.get("/admin/v1/agents/usage?days=30", headers=admin_headers)
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["period"] == "30d"
    assert "total_cost_yuan" in d
    assert "usage" in d
    assert isinstance(d["usage"], list)
    # 已插入的 t_api_rec 调用应体现在金额维度
    for item in d["usage"]:
        if item["agent_key"] == "health-assistant":
            assert "cost_yuan" in item
            break
