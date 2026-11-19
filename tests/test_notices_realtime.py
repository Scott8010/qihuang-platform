"""机构端「平台公告与告警」+「实时消耗」收窄接口回归（2026-11-19）

铁律：
  1. my/notices、my/realtime-usage 强制按 token 租户收窄，不接客户端 tenant_id。
  2. 公告只返回 published 且 audience=all 或本租户的，跨租户专属公告不可见。
  3. 告警全部来自真数据表（配额/到期/工单/错误率），不用 monitor 硬编码假数。
  4. 实时消耗只算 billable_call_filter() 真业务调用，与 usage/billing 同源。
  5. 超管 CRUD 公告，机构管理员无权发布/改状态。
"""
import uuid
from datetime import datetime, timezone, timedelta

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    Tenant, Plan, Subscription, User, CallLog, SupportTicket, PlatformNotice, Wallet,
)
from qihuang_platform.billing.plans import seed_plans
from qihuang_platform.gateway.auth import create_access_token


def _headers(uid: str, tid: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + create_access_token(uid, tid, "org_default", roles)}


def _uid() -> str:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == "admin").first().id
    finally:
        db.close()


def _seed_tenant(tid: str) -> None:
    db = SessionLocal()
    try:
        seed_plans(db)
        if not db.query(Tenant).filter_by(id=tid).first():
            db.add(Tenant(id=tid, name=tid, display_name=tid, scene="MED"))
        db.commit()
    finally:
        db.close()


def _cleanup(*tids: str) -> None:
    """PG 外键：子表先删（call_log/工单/公告/订阅/钱包），父表 tenant 最后删。"""
    db = SessionLocal()
    try:
        db.query(CallLog).filter(CallLog.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(SupportTicket).filter(SupportTicket.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(PlatformNotice).filter(PlatformNotice.target_tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(Wallet).filter(Wallet.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(PlatformNotice).filter(PlatformNotice.id.like("%test%")).delete(synchronize_session=False)
        db.query(Tenant).filter(Tenant.id.in_(tids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# ── 公告收窄 + 告警真值 ──
def test_my_notices_scope_and_real_alerts(client, ensure_admin_in_db):
    ta = "t-notice-a-" + uuid.uuid4().hex[:8]
    tb = "t-notice-b-" + uuid.uuid4().hex[:8]
    admin_uid = _uid()
    _seed_tenant(ta)
    _seed_tenant(tb)
    db = SessionLocal()
    try:
        # 全体公告 + A 专属 + B 专属 + 草稿 + 下架
        db.add_all([
            PlatformNotice(id="test-n-all", title="全体维护", content="x", category="维护", audience="all", status="published", published_at=datetime.now(timezone.utc)),
            PlatformNotice(id="test-n-a", title="A专属", content="x", audience="tenant", target_tenant_id=ta, status="published", published_at=datetime.now(timezone.utc)),
            PlatformNotice(id="test-n-b", title="B专属", content="x", audience="tenant", target_tenant_id=tb, status="published", published_at=datetime.now(timezone.utc)),
            PlatformNotice(id="test-n-draft", title="草稿公告", content="x", audience="all", status="draft", published_at=datetime.now(timezone.utc)),
            PlatformNotice(id="test-n-off", title="下架公告", content="x", audience="all", status="withdrawn", published_at=datetime.now(timezone.utc)),
            # B 租户一条待处理工单（A 不应看到 B 的告警来源）
            SupportTicket(id="test-t-b", ticket_no="T-TEST-B", tenant_id=tb, title="x", content="x", status="open"),
        ])
        # A 的近 30 分钟 10 次调用中 3 次失败（30% > 10% 阈值，触发真错误率告警）
        for i in range(10):
            db.add(CallLog(
                id=f"test-c-a{i}", tenant_id=ta, endpoint="/api/v1/agent/health-assistant/consult",
                status_code=500 if i < 3 else 200, tokens_used=10, cost_cents=5,
                timestamp=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/admin/v1/my/notices", headers=_headers(admin_uid, ta, ["org_admin"]))
        assert r.status_code == 200, r.text[:300]
        d = r.json()["data"]
        assert d["tenant_id"] == ta
        titles = [n["title"] for n in d["announcements"]]
        assert "全体维护" in titles and "A专属" in titles, titles
        assert "B专属" not in titles, titles          # 跨租户专属不可见
        assert "草稿公告" not in titles and "下架公告" not in titles, titles

        # B 专属公告只 B 可见
        rb = client.get("/admin/v1/my/notices", headers=_headers(admin_uid, tb, ["org_admin"]))
        titles_b = [n["title"] for n in rb.json()["data"]["announcements"]]
        assert "B专属" in titles_b and "A专属" not in titles_b, titles_b

        # 告警：A 有错误率告警（1/1 失败），B 有工单告警；两边互不串
        al = {x["id"]: x for x in d["alerts"]}
        assert "ERRORS" in al, d["alerts"]
        assert "TICKET" not in al, d["alerts"]     # A 没工单
        alb = {x["id"]: x for x in rb.json()["data"]["alerts"]}
        assert "TICKET" in alb, rb.json()["data"]["alerts"]
    finally:
        _cleanup(ta, tb)


# ── 实时消耗：真调用聚合 + 跨租户隔离 + 只算 billable ──
def test_my_realtime_usage_billable_and_scoped(client, ensure_admin_in_db):
    ta = "t-rt-a-" + uuid.uuid4().hex[:8]
    tb = "t-rt-b-" + uuid.uuid4().hex[:8]
    admin_uid = _uid()
    _seed_tenant(ta)
    _seed_tenant(tb)
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add_all([
            CallLog(id="test-rt-a1", tenant_id=ta, endpoint="/api/v1/agent/health-assistant/consult",
                    status_code=200, tokens_used=100, cost_cents=50, latency_ms=800, timestamp=now),
            CallLog(id="test-rt-a2", tenant_id=ta, endpoint="/api/v1/agent/tongue/analyze",
                    status_code=200, tokens_used=200, cost_cents=70, latency_ms=1200, timestamp=now - timedelta(minutes=2)),
            # 后台浏览请求：不算实时消耗
            CallLog(id="test-rt-a3", tenant_id=ta, endpoint="/admin/v1/dashboard",
                    status_code=200, tokens_used=999, cost_cents=999, latency_ms=10, timestamp=now),
            # B 租户专属调用：A 看不到
            CallLog(id="test-rt-b1", tenant_id=tb, endpoint="/api/v1/agent/fortune/cast",
                    status_code=200, tokens_used=500, cost_cents=300, latency_ms=500, timestamp=now),
        ])
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/admin/v1/my/realtime-usage?minutes=60", headers=_headers(admin_uid, ta, ["org_admin"]))
        assert r.status_code == 200, r.text[:300]
        d = r.json()["data"]
        assert d["tenant_id"] == ta
        assert d["summary"]["calls"] == 2, d["summary"]         # 只算 2 条 agent 调用
        assert d["summary"]["tokens"] == 300, d["summary"]
        assert d["summary"]["cost_cents"] == 120, d["summary"]
        agents = {x["agent"] for x in d["by_agent"]}
        assert agents == {"health-assistant", "tongue"}, agents
        assert "fortune" not in agents                            # 跨租户不可见
        assert all(x["calls"] > 0 for x in d["timeline"])         # 分钟分桶有数据
    finally:
        _cleanup(ta, tb)


# ── 超管发布权限 ──
def test_notice_crud_requires_super_admin(client, ensure_admin_in_db):
    tid = "t-notice-crud-" + uuid.uuid4().hex[:8]
    admin_uid = _uid()
    _seed_tenant(tid)
    try:
        # 机构管理员不能发布
        r = client.post("/admin/v1/notices", json={"title": "x", "content": "x"},
                        headers=_headers(admin_uid, tid, ["org_admin"]))
        assert r.status_code == 403, r.text[:200]
        # 超管可发布
        payload = {"title": "回归测试公告", "content": "x", "category": "公告", "audience": "all", "status": "published"}
        rs = client.post("/admin/v1/notices", json=payload,
                         headers=_headers(admin_uid, "", ["super_admin"]))
        assert rs.status_code == 200, rs.text[:300]
        nid = rs.json()["data"]["id"]
        # 机构管理员不能改状态
        rp = client.patch(f"/admin/v1/notices/{nid}/status", json={"status": "withdrawn"},
                          headers=_headers(admin_uid, tid, ["org_admin"]))
        assert rp.status_code == 403, rp.text[:200]
        # 超管能改
        rp2 = client.patch(f"/admin/v1/notices/{nid}/status", json={"status": "withdrawn"},
                           headers=_headers(admin_uid, "", ["super_admin"]))
        assert rp2.status_code == 200, rp2.text[:300]
        db = SessionLocal()
        try:
            db.query(PlatformNotice).filter_by(id=nid).delete()
            db.commit()
        finally:
            db.close()
    finally:
        _cleanup(tid)
