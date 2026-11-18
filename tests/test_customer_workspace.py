"""客户工作台新增端点的租户隔离回归（2026-11-18）

覆盖：登录响应带 tenant_name、租户工单只能看自己的、
使用日志只能看自己的、非超管不能处理工单。
"""
import uuid

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import CallLog, Tenant, SupportTicket, User
from qihuang_platform.gateway.auth import create_access_token


def _token(uid: str, tenant_id: str, roles: list[str]) -> str:
    return create_access_token(uid, tenant_id, "org_default", roles)


def _headers(uid: str, tenant_id: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + _token(uid, tenant_id, roles)}


def test_login_response_has_tenant_name(client, ensure_admin_in_db):
    r = client.post("/admin/v1/login", json={"username": "admin", "password": "TestAdmin@2026"})
    assert r.status_code == 200, r.text[:200]
    data = r.json()["data"]
    assert "tenant_name" in data and data["tenant_name"], data


def test_ticket_and_calllog_are_tenant_scoped(client, ensure_admin_in_db):
    tid_a = "t-a-" + uuid.uuid4().hex[:8]
    tid_b = "t-b-" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        # JWT 的 sub 必须是库内真实用户，否则 get_current_user 直接 401
        admin_uid = db.query(User).filter(User.username == "admin").first().id
        for tid, name in ((tid_a, "甲机构"), (tid_b, "乙机构")):
            db.add(Tenant(id=tid, name=tid, display_name=name, status="active"))
        db.commit()
        ta = SupportTicket(id=uuid.uuid4().hex, ticket_no="TKA" + uuid.uuid4().hex[:8],
                           tenant_id=tid_a, title="甲的问题", content="甲内容", status="open")
        tb = SupportTicket(id=uuid.uuid4().hex, ticket_no="TKB" + uuid.uuid4().hex[:8],
                           tenant_id=tid_b, title="乙的问题", content="乙内容", status="open")
        ca = CallLog(id=uuid.uuid4().hex, trace_id="trace-a-" + uuid.uuid4().hex[:8],
                     tenant_id=tid_a, endpoint="/api/v1/agent/health-advisor/consult", status_code=200)
        cb = CallLog(id=uuid.uuid4().hex, trace_id="trace-b-" + uuid.uuid4().hex[:8],
                     tenant_id=tid_b, endpoint="/api/v1/agent/health-advisor/consult", status_code=200)
        db.add_all([ta, tb, ca, cb])
        db.commit()
        ticket_b_id = tb.id
        trace_b = cb.trace_id
    finally:
        db.close()

    ha = _headers(admin_uid, tid_a, ["org_admin"])
    try:
        # 提交工单：归属强制取 token 租户，客户端无法指定别家
        r = client.post("/admin/v1/my/tickets", headers=ha, json={
            "title": "申请开通新能力", "content": "请帮忙开通内容审核", "category": "申请",
        })
        assert r.status_code == 200, r.text[:200]
        assert r.json()["data"]["tenant_id"] == tid_a

        # 我的工单 / 平台工单（租户视角）都只能看到甲机构
        for path in ("/admin/v1/my/tickets", "/admin/v1/tickets",
                     "/admin/v1/my/call-logs"):
            rr = client.get(path, headers=ha)
            assert rr.status_code == 200, (path, rr.text[:200])
            body = rr.json()["data"]
            assert body["pagination"]["total"] >= 1
            assert all(x.get("tenant_id", tid_a) == tid_a for x in body["items"]) if path != "/admin/v1/my/call-logs" else True
        logs = client.get("/admin/v1/my/call-logs", headers=ha).json()["data"]["items"]
        assert all(x["trace_id"] != trace_b for x in logs)

        # 非超管不能处理工单
        rr = client.post(f"/admin/v1/tickets/{ticket_b_id}/reply", headers=ha,
                         json={"status": "resolved", "note": "越权处理"})
        assert rr.status_code == 403, rr.text[:200]
    finally:
        db = SessionLocal()
        try:
            db.query(SupportTicket).filter(SupportTicket.tenant_id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.query(CallLog).filter(CallLog.tenant_id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id.in_([tid_a, tid_b])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
