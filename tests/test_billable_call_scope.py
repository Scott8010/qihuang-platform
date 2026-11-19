"""计费口径回归（2026-11-19 老板拍板 A）

铁律：配额/账单/客户用量只算「真业务 AI 调用」
  - 真业务: /api/v1/agent/{key}/... 或 agent:{key}
  - 后台浏览/结算: /admin/*、/billing/* —— 属操作日志，不计费、不计用量

覆盖：
  1. my/call-logs?kind=business 只看 agent 调用
  2. my/call-logs?kind=operation 只看后台/结算请求
  3. my/call-logs?kind=all 全部可见
  4. 两路都强制按 token 租户收窄（跨租户拿不到）
  5. _get_month_usage 配额只累加真业务调用
  6. tenants-extended 的 usedCalls 只算真业务调用
"""
import uuid
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import CallLog, Tenant, User, Subscription, Plan
from qihuang_platform.gateway.auth import create_access_token
from qihuang_platform.billing.quota import _get_month_usage


def _headers(uid: str, tenant_id: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + create_access_token(uid, tenant_id, "org_default", roles)}


def _seed(tenant_id: str, tag: str):
    """一个租户写入 1 条 agent 调用 + 2 条后台请求（均本月 UTC）。"""
    now = datetime.now(timezone.utc)
    rows = [
        CallLog(id=uuid.uuid4().hex, trace_id=f"{tag}-biz", tenant_id=tenant_id,
                endpoint="/api/v1/agent/health-advisor/consult", method="POST",
                status_code=200, tokens_used=100, timestamp=now),
        CallLog(id=uuid.uuid4().hex, trace_id=f"{tag}-admin", tenant_id=tenant_id,
                endpoint="/admin/v1/tenants-extended", method="GET",
                status_code=200, tokens_used=0, timestamp=now),
        CallLog(id=uuid.uuid4().hex, trace_id=f"{tag}-bill", tenant_id=tenant_id,
                endpoint="/billing/wallet/balance", method="GET",
                status_code=200, tokens_used=0, timestamp=now),
    ]
    return rows


def test_call_logs_kind_filters_and_tenant_scope(client, ensure_admin_in_db):
    tid_a = "t-bill-a-" + uuid.uuid4().hex[:8]
    tid_b = "t-bill-b-" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        admin_uid = db.query(User).filter(User.username == "admin").first().id
        # PG 有 call_log.tenant_id 外键：Tenant 必须先落库，再写 CallLog
        for tid, name in ((tid_a, "口径甲"), (tid_b, "口径乙")):
            db.add(Tenant(id=tid, name=tid, display_name=name, status="active"))
        db.commit()
        rows = _seed(tid_a, "A") + _seed(tid_b, "B")
        db.add_all(rows)
        db.commit()
    finally:
        db.close()

    ha = _headers(admin_uid, tid_a, ["org_admin"])
    try:
        biz = client.get("/admin/v1/my/call-logs?kind=business&days=30&page_size=100", headers=ha).json()["data"]
        op = client.get("/admin/v1/my/call-logs?kind=operation&days=30&page_size=100", headers=ha).json()["data"]
        all_ = client.get("/admin/v1/my/call-logs?kind=all&days=30&page_size=100", headers=ha).json()["data"]

        # business：只有真业务 agent 调用，后台请求一律不出现
        assert biz["pagination"]["total"] == 1, biz
        assert biz["items"][0]["endpoint"].startswith("/api/v1/agent/"), biz["items"]
        biz_traces = {x["trace_id"] for x in biz["items"]}
        assert "A-biz" in biz_traces and "A-admin" not in biz_traces and "A-bill" not in biz_traces

        # operation：我种的 2 条后台请求都在；且绝不含 agent 调用。
        # 注意：访问本接口自身也会被中间件记一条 /admin/... 操作日志，故用包含断言而非精确总数。
        op_traces = {x["trace_id"] for x in op["items"]}
        assert "A-admin" in op_traces and "A-bill" in op_traces, op_traces
        assert all(not (x["endpoint"] or "").startswith("/api/v1/agent/") for x in op["items"]), op["items"]

        # all：三类都在
        assert all_["pagination"]["total"] >= 3, all_

        # 跨租户：乙机构的 trace 在甲机构任何口径下都拿不到
        for body in (biz, op, all_):
            assert all(x["trace_id"] != "B-biz" for x in body["items"]), body["items"]
    finally:
        db = SessionLocal()
        try:
            db.query(CallLog).filter(CallLog.tenant_id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_month_usage_counts_only_billable_calls():
    db = SessionLocal()
    tid = "t-quota-" + uuid.uuid4().hex[:8]
    try:
        db.add(Tenant(id=tid, name=tid, display_name="配额口径", status="active"))
        db.commit()  # PG 外键：Tenant 先落库
        db.add_all(_seed(tid, "Q"))
        db.commit()
        usage = _get_month_usage(db, tid)
        assert usage["used_calls"] == 1, usage       # 只有 1 条 agent 调用
        assert usage["used_tokens"] == 100, usage    # 后台请求 tokens=0，不计入
    finally:
        db.query(CallLog).filter(CallLog.tenant_id == tid).delete(synchronize_session=False)
        db.query(Tenant).filter(Tenant.id == tid).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_tenants_extended_usedcalls_only_billable(client, ensure_admin_in_db):
    tid = "t-used-a-" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        admin_uid = db.query(User).filter(User.username == "admin").first().id
        db.add(Tenant(id=tid, name=tid, display_name="用量口径", status="active"))
        db.commit()  # PG 外键：Tenant 先落库
        db.add_all(_seed(tid, "U"))
        db.commit()
    finally:
        db.close()

    # 用超管视角（token 租户留空）无法精确锁定单租户，直接用 org_admin token 收窄到本租户
    h = _headers(admin_uid, tid, ["org_admin"])
    try:
        r = client.get("/admin/v1/tenants-extended?page_size=100", headers=h)
        assert r.status_code == 200, r.text[:200]
        items = [x for x in r.json()["data"]["items"] if x["id"] == tid]
        assert len(items) == 1, items
        assert items[0]["usedCalls"] == 1, items[0]  # 后台 2 条不计入
    finally:
        db = SessionLocal()
        try:
            db.query(CallLog).filter(CallLog.tenant_id == tid).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id == tid).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
