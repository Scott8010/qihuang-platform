"""
计费中台钱包端点（#474）— 充值 + 余额查询。
挂载：main.py include_router(wallet_router) → /billing/v1/wallet/*

鉴权（#474 安全加固，66bb041 后续提交）：
- POST /recharge     仅平台管理员（JWT admin/super_admin）可调用；租户 API Key 不可。
- GET  /{tenant_id}  需登录；admin 可查任意租户，普通租户/API Key 仅能查自身归属的 tenant_id。
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Depends, HTTPException

from qihuang_platform.gateway.deps import get_current_principal, get_current_admin
from qihuang_platform.gateway.response import error
from qihuang_platform.billing.wallet import recharge, get_balance

wallet_router = APIRouter(prefix="/billing/v1/wallet", tags=["wallet"])


def _ensure_wallet_scope(request: Request, tenant_id: str) -> None:
    """租户归属校验：admin 放行任意，其余仅能访问自身 tenant_id。

    JWT 路径注入 request.state.roles；API Key 路径不注入 roles → 视为非 admin，
    只能查自己归属的 tenant_id（request.state.tenant_id 由 API Key 校验注入）。
    """
    roles = getattr(request.state, "roles", None) or []
    is_admin = "admin" in roles or "super_admin" in roles
    if is_admin:
        return
    caller_tenant = getattr(request.state, "tenant_id", None)
    if not caller_tenant or caller_tenant != tenant_id:
        raise HTTPException(status_code=403, detail=error("FORBIDDEN", "无权访问该租户钱包"))


@wallet_router.post("/recharge")
def api_recharge(
    request: Request,
    tenant_id: str = Query(..., description="租户ID"),
    pack: str = Query(..., description="充值包 key：pack_50/100/200/500"),
    _admin: dict = Depends(get_current_admin),
):
    """叠加包充值（永久有效）。仅平台管理员可调用。"""
    return recharge(tenant_id, pack)


@wallet_router.get("/{tenant_id}")
def api_balance(
    request: Request,
    tenant_id: str,
    _user: dict = Depends(get_current_principal),
):
    """查询租户积分余额。admin 可查任意，租户仅可查自身。"""
    _ensure_wallet_scope(request, tenant_id)
    return get_balance(tenant_id)
