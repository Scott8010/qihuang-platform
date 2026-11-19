"""机构端「我的可用 Agent」收窄接口回归（2026-11-19）

铁律：
  1. GET /admin/v1/my/agents 强制按 token 租户收窄，不接受客户端 tenant_id。
  2. 可用范围与 require_agent_in_plan 门控同源（resolve_tenant_agent_access），
     页面能看到 = 真能调用，杜绝「看着能用、调不通」。
  3. 单加（addon）正确标记来源，未开通能力进 locked 灰显。
  4. 无订阅租户不造假能力，available 为空、全部灰显。
"""
import uuid

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Tenant, Plan, Subscription, User, CallLog
from qihuang_platform.billing.plans import SCENE_PLAN_AGENTS, seed_plans
from qihuang_platform.gateway.auth import create_access_token
from qihuang_platform.agent.deps import resolve_tenant_agent_access


def _headers(uid: str, tid: str, roles: list[str]) -> dict:
    return {"Authorization": "Bearer " + create_access_token(uid, tid, "org_default", roles)}


def _seed_tenant(tid: str, scene: str, plan_name: str,
                 addons: list[str] | None = None, active_sub: bool = True):
    db = SessionLocal()
    try:
        seed_plans(db)
        plan = db.query(Plan).filter_by(plan_name=plan_name).first()
        t = db.query(Tenant).filter_by(id=tid).first()
        if not t:
            t = Tenant(id=tid, name=tid, display_name=tid, scene=scene,
                       extra={"agent_addons": addons or []})
            db.add(t)
            db.flush()
        else:
            t.scene = scene
            t.extra = {"agent_addons": addons or []}
        db.query(Subscription).filter_by(tenant_id=tid).delete(synchronize_session=False)
        if active_sub:
            db.add(Subscription(id="sub_" + tid[:20], tenant_id=tid,
                                plan_id=plan.id, status="active"))
        db.commit()  # Tenant/Plan 先落库，Subscription 同批也带 FK，父表已在 seed_plans 提交
    finally:
        db.close()


def _cleanup(*tids: str):
    """按外键依赖顺序清理：先子表后父表。
    PG 强制 FK（本地 SQLite 不强制，易假绿）：调用 /admin/v1/my/agents 时中间件会自动
    记一条 operation 类 call_log 引用测试租户，不先删 call_log 就删 tenant 会触发
    call_log_tenant_id_fkey。铁律：造带 FK 的记录一律父表先落库、清理一律子表先删。"""
    db = SessionLocal()
    try:
        db.query(CallLog).filter(CallLog.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.tenant_id.in_(tids)).delete(synchronize_session=False)
        db.query(Tenant).filter(Tenant.id.in_(tids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _admin_uid() -> str:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == "admin").first().id
    finally:
        db.close()


def test_my_agents_scope_and_gate_consistency(client, ensure_admin_in_db):
    tid_a = "t-myag-a-" + uuid.uuid4().hex[:8]
    tid_b = "t-myag-b-" + uuid.uuid4().hex[:8]
    uid = _admin_uid()
    # A：MED 企业版 + 单加 fortune；B：EDU 标准版（另有 coach，作跨租户反证）
    _seed_tenant(tid_a, "MED", "enterprise", addons=["fortune"])
    _seed_tenant(tid_b, "EDU", "standard")
    try:
        r = client.get("/admin/v1/my/agents", headers=_headers(uid, tid_a, ["org_admin"]))
        assert r.status_code == 200, r.text[:300]
        d = r.json()["data"]

        # 强制收窄到 token 租户
        assert d["tenant_id"] == tid_a, d
        assert d["scene"] == "MED", d
        assert d["plan"] == "企业版", d

        # MED 企业版 4 个 + 单加 fortune，顺序与套餐编排一致
        keys = [x["agent_key"] for x in d["available"]]
        assert keys == SCENE_PLAN_AGENTS["MED"]["enterprise"] + ["fortune"], keys
        src = {x["agent_key"]: x["source"] for x in d["available"]}
        assert src["fortune"] == "addon", src
        assert src["compliance"] == "plan", src

        # 门控同源铁律：接口可用集 == 门控解析出的 agents
        assert keys == resolve_tenant_agent_access(tid_a)["agents"]

        # 未开通能力进 locked 灰显；已开通的不出现在 locked
        locked = [x["agent_key"] for x in d["locked"]]
        assert "coach" in locked, locked
        assert "compliance" not in locked and "fortune" not in locked, locked

        # 跨租户反证：B 的 EDU 标准版专属 coach 不能变成 A 的可用能力
        assert "coach" not in keys

        # 每项都有中文名和说明，前端不靠 key 硬编码
        assert all(x.get("name") and x.get("desc") for x in d["available"]), d["available"]
    finally:
        _cleanup(tid_a, tid_b)


def test_my_agents_without_subscription(client, ensure_admin_in_db):
    tid = "t-myag-nosub-" + uuid.uuid4().hex[:8]
    uid = _admin_uid()
    _seed_tenant(tid, "MED", "enterprise", active_sub=False)
    try:
        r = client.get("/admin/v1/my/agents", headers=_headers(uid, tid, ["org_admin"]))
        assert r.status_code == 200, r.text[:300]
        d = r.json()["data"]
        assert d["has_subscription"] is False, d
        assert d["available"] == [], d["available"]
        assert len(d["locked"]) > 0, d["locked"]  # 全部灰显，不造假
    finally:
        _cleanup(tid)
