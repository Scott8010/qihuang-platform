"""机构端「账单与配额」总览回归（2026-11-19）

铁律：
  1. /admin/v1/my/billing-overview 强制按 token 租户收窄，不接受客户端 tenant_id。
  2. 消费金额 / 近6月趋势 / 费用构成只算真业务 AI 调用（billable_call_filter）。
  3. 后台浏览 / 结算请求不计入任何消费数字。
  4. 跨租户隔离：甲机构拿不到乙机构的消费与调用。
"""
import uuid
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import CallLog, Tenant, User
from qihuang_platform.gateway.auth import create_access_token


def _headers(uid: str, tenant_id: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + create_access_token(uid, tenant_id, "org_default", roles)}


def _bill_call(tid: str, tag: str, cost: float) -> CallLog:
    return CallLog(
        id=uuid.uuid4().hex, trace_id=f"{tag}-bill", tenant_id=tid,
        endpoint="/api/v1/agent/health-advisor/consult", method="POST",
        status_code=200, tokens_used=100, cost_cents=cost,
        timestamp=datetime.now(timezone.utc),
    )


def test_billing_overview_scope_and_billable(client, ensure_admin_in_db):
    tid_a = "t-billov-a-" + uuid.uuid4().hex[:8]
    tid_b = "t-billov-b-" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        admin_uid = db.query(User).filter(User.username == "admin").first().id
        # PG 外键：Tenant 先落库，再写 CallLog
        for tid, name in ((tid_a, "账单甲"), (tid_b, "账单乙")):
            db.add(Tenant(id=tid, name=tid, display_name=name, status="active"))
        db.commit()
        db.add_all([
            _bill_call(tid_a, "A", 25.0),   # 甲机构本月消费 25 分
            _bill_call(tid_a, "A2", 15.0),  # 甲机构本月消费 15 分
            _bill_call(tid_b, "B", 99.0),   # 乙机构本月消费 99 分
            CallLog(id=uuid.uuid4().hex, trace_id="A-admin", tenant_id=tid_a,
                    endpoint="/admin/v1/tenants", method="GET", status_code=200,
                    tokens_used=0, cost_cents=0, timestamp=datetime.now(timezone.utc)),
        ])
        db.commit()
    finally:
        db.close()

    ha = _headers(admin_uid, tid_a, ["org_admin"])
    try:
        r = client.get("/admin/v1/my/billing-overview", headers=ha)
        assert r.status_code == 200, r.text[:300]
        d = r.json()["data"]

        # 强制收窄到 token 租户
        assert d["tenant_id"] == tid_a, d
        # 本月消费只算真业务：25+15=40 分，乙机构 99 分不算，后台 0 分不算
        assert d["month"]["cost_cents"] == 40, d["month"]
        assert d["month"]["calls"] == 2, d["month"]
        # 近 6 个月趋势：6 个月，本月为 40 分
        assert len(d["monthly_trend"]) == 6, d["monthly_trend"]
        assert d["monthly_trend"][-1]["cost_cents"] == 40, d["monthly_trend"]
        # 费用构成按 agent 聚合，只含真业务 agent，总额=40 分
        bc = d["cost_breakdown"]
        assert sum(x["cost_cents"] for x in bc) == 40, bc
        assert all(x["agent"] == "health-advisor" for x in bc), bc
        # 发票占位文案明确，不造假数据
        assert "发票" in d["invoice_note"], d["invoice_note"]
    finally:
        db = SessionLocal()
        try:
            db.query(CallLog).filter(CallLog.tenant_id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
