"""
#474 计费中台钱包单测（本地 SQLite，不连生产）。
覆盖：汇率换算 / 不调LLM固定积分 / 充值 / 余额 / 扣费顺序 / 空池拦截。
"""
import pytest

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Wallet
from qihuang_platform.billing.wallet import recharge, get_balance, consume_credits
from qihuang_platform.billing.pricing_config import compute_credits, FLAT_CREDITS_PER_CALL


def _wipe():
    from qihuang_platform.db.models import Base
    db = SessionLocal()
    Base.metadata.create_all(db.bind)  # 确保新表 wallet 存在（幂等）
    db.query(Wallet).delete()
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
    assert b["base_credits"] == 0  # 测试无套餐，基本包为空


def test_consume_deducts_addon():
    _wipe()
    recharge("t_wallet_2", "pack_50")  # +1000
    ok, cost = consume_credits("t_wallet_2", "health-assistant", 500, False, True)  # 1 积分
    assert ok is True and cost == 1
    b = get_balance("t_wallet_2")["data"]
    assert b["addon_credits"] == 999


def test_consume_no_llm_flat_deducts():
    _wipe()
    recharge("t_wallet_4", "pack_50")  # +1000
    flat = FLAT_CREDITS_PER_CALL["compliance"]
    ok, cost = consume_credits("t_wallet_4", "compliance", 0, False, False)  # 固定积分
    assert ok is True and cost == flat
    b = get_balance("t_wallet_4")["data"]
    assert b["addon_credits"] == 1000 - flat


def test_consume_blocked_when_empty():
    _wipe()
    ok, cost = consume_credits("t_wallet_3", "health-assistant", 100000, False, True)
    assert ok is False  # 两池皆空 → 拦截，且不扣任何
    b = get_balance("t_wallet_3")["data"]
    assert b["total_credits"] == 0
