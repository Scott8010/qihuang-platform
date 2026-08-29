"""
#474 计费中台钱包单测（本地 SQLite，不连生产）。
覆盖：汇率换算 / 不调LLM固定积分 / 充值 / 余额 / 扣费顺序 / 空池拦截。
"""
import pytest

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Wallet, Tenant
from qihuang_platform.billing.wallet import recharge, get_balance, consume_credits
from qihuang_platform.billing.pricing_config import compute_credits, FLAT_CREDITS_PER_CALL


def _wipe():
    from qihuang_platform.db.models import Base
    db = SessionLocal()
    Base.metadata.create_all(db.bind)  # 确保 wallet/tenant 等新表存在（幂等）
    db.query(Wallet).delete()
    # 预置测试租户：wallet.tenant_id 有外键指向 tenant，CI 用 PostgreSQL 强制校验，
    # 本地 SQLite 默认不校验易漏。不造租户会导致所有充值/扣费测试外键报错。
    for tid in ["t_wallet_1", "t_wallet_2", "t_wallet_3", "t_wallet_4",
                "other_tenant", "admin_t", "my_t", "other_t"]:
        db.merge(Tenant(id=tid, name=tid, display_name=tid, scene="health", status="active", extra={}))
    db.commit()
    db.close()


def test_compute_credits_llm_text():
    # A = 500 token/积分（文本）：500→1，1000→2
    assert compute_credits("health-assistant", 500, False, True) == 1
    assert compute_credits("health-assistant", 1000, False, True) == 2


def test_compute_credits_llm_multimodal():
    # 多模态 ×1.5：500 token → 1.5 → 向上取整 2
    assert compute_credits("tongue", 500, True, True) == 2


def test_compute_credits_no_llm_flat():
    # 不调 LLM 的 agent → 固定积分/次（与 pricing_config 配置一致，改数不破测）
    assert compute_credits("compliance", 0, False, False) == FLAT_CREDITS_PER_CALL["compliance"]
    assert compute_credits("fortune", 0, False, False) == FLAT_CREDITS_PER_CALL["fortune"]
    assert compute_credits("geo", 0, False, False) == FLAT_CREDITS_PER_CALL["geo"]


def test_recharge_and_balance():
    _wipe()
    r = recharge("t_wallet_1", "pack_50")
    assert r.get("code", -1) == 0 and "data" in r
    b = get_balance("t_wallet_1")["data"]
    assert b["addon_credits"] == 1000
    assert b["base_credits"] == 300  # 测试无套餐，按默认基本包 BASE_CREDITS_DEFAULT=300 播种


def test_consume_deducts_addon():
    _wipe()
    recharge("t_wallet_2", "pack_50")  # +1000
    ok, cost = consume_credits("t_wallet_2", "health-assistant", 500, False, True)  # 1 积分
    assert ok is True and cost == 1
    b = get_balance("t_wallet_2")["data"]
    # 消费 1 积分：基本包默认 300 充足，先扣 base（300→299），不碰 addon
    assert b["base_credits"] == 299
    assert b["addon_credits"] == 1000


def test_consume_no_llm_flat_deducts():
    _wipe()
    recharge("t_wallet_4", "pack_50")  # +1000
    flat = FLAT_CREDITS_PER_CALL["compliance"]
    ok, cost = consume_credits("t_wallet_4", "compliance", 0, False, False)  # 固定积分
    assert ok is True and cost == flat
    b = get_balance("t_wallet_4")["data"]
    # 固定积分同样先扣 base（300-flat），addon 不动
    assert b["base_credits"] == 300 - flat
    assert b["addon_credits"] == 1000


def test_consume_blocked_when_empty():
    _wipe()
    # 显式造真正空钱包（base=0/addon=0）：无订阅租户默认会播种 base=300，
    # 这里直接置 0 才能验证「两池皆空 → 拦截」
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Wallet
    from qihuang_platform.billing.wallet import _month_str
    db = SessionLocal()
    db.add(Wallet(tenant_id="t_wallet_3", base_credits=0, addon_credits=0, period_month=_month_str()))
    db.commit()
    db.close()
    ok, cost = consume_credits("t_wallet_3", "health-assistant", 100000, False, True)
    assert ok is False  # 两池皆空 → 拦截，且不扣任何
    b = get_balance("t_wallet_3")["data"]
    assert b["total_credits"] == 0


# ──────────────────────────────────────────────────────────────
# 鉴权测试（#474 安全加固）：裸端点 → 必须登录 + 租户归属
# ──────────────────────────────────────────────────────────────
def test_wallet_auth_unauthenticated_rejected():
    """无鉴权头 → 401（GET 与 recharge 同理）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qihuang_platform.billing.wallet_router import wallet_router
    app = FastAPI()
    app.include_router(wallet_router)
    c = TestClient(app)
    assert c.get("/billing/v1/wallet/any").status_code == 401
    assert c.post("/billing/v1/wallet/recharge?tenant_id=any&pack=pack_50").status_code == 401


def test_wallet_auth_admin_can_query_any_and_recharge():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from qihuang_platform.billing.wallet_router import wallet_router
    from qihuang_platform.gateway.deps import get_current_principal, get_current_user
    _wipe()
    app = FastAPI()
    app.include_router(wallet_router)

    async def fake_principal(request: Request):
        request.state.tenant_id = "admin_t"
        request.state.roles = ["admin"]
        return {"tenant_id": "admin_t", "roles": ["admin"]}

    async def fake_user(request: Request):
        request.state.tenant_id = "admin_t"
        request.state.roles = ["admin"]
        return {"tenant_id": "admin_t", "roles": ["admin"]}

    app.dependency_overrides[get_current_principal] = fake_principal
    app.dependency_overrides[get_current_user] = fake_user
    c = TestClient(app)
    r = c.get("/billing/v1/wallet/other_tenant")
    assert r.status_code == 200 and r.json()["code"] == 0
    r = c.post("/billing/v1/wallet/recharge?tenant_id=other_tenant&pack=pack_50")
    assert r.status_code == 200
    app.dependency_overrides.clear()


def test_wallet_auth_tenant_only_self():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from qihuang_platform.billing.wallet_router import wallet_router
    from qihuang_platform.gateway.deps import get_current_principal
    _wipe()
    app = FastAPI()
    app.include_router(wallet_router)

    async def fake_principal(request: Request):
        request.state.tenant_id = "my_t"
        request.state.roles = []
        return {"tenant_id": "my_t", "roles": []}

    app.dependency_overrides[get_current_principal] = fake_principal
    c = TestClient(app)
    assert c.get("/billing/v1/wallet/my_t").status_code == 200
    assert c.get("/billing/v1/wallet/other_t").status_code == 403
    app.dependency_overrides.clear()


def test_wallet_auth_nonadmin_cannot_recharge():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from qihuang_platform.billing.wallet_router import wallet_router
    from qihuang_platform.gateway.deps import get_current_user
    _wipe()
    app = FastAPI()
    app.include_router(wallet_router)

    async def fake_user(request: Request):
        request.state.tenant_id = "my_t"
        request.state.roles = []  # 非 admin
        return {"tenant_id": "my_t", "roles": []}

    app.dependency_overrides[get_current_user] = fake_user
    c = TestClient(app)
    r = c.post("/billing/v1/wallet/recharge?tenant_id=my_t&pack=pack_50")
    assert r.status_code == 403  # get_current_admin 拒绝非 admin
    app.dependency_overrides.clear()
