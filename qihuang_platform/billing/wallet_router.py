"""
计费中台钱包端点（#474）— 充值 + 余额查询。
挂载：main.py include_router(wallet_router) → /billing/v1/wallet/*
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from qihuang_platform.billing.wallet import recharge, get_balance

wallet_router = APIRouter(prefix="/billing/v1/wallet", tags=["wallet"])


@wallet_router.post("/recharge")
def api_recharge(tenant_id: str = Query(..., description="租户ID"), pack: str = Query(..., description="充值包 key：pack_50/100/200/500")):
    """叠加包充值（永久有效）。body 也可带 admin 鉴权，此处简化。"""
    return recharge(tenant_id, pack)


@wallet_router.get("/{tenant_id}")
def api_balance(tenant_id: str):
    """查询租户积分余额。"""
    return get_balance(tenant_id)
