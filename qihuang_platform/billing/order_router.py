"""
结算中心订单端点（#B 方案）— 订单查询。
挂载：main.py include_router(order_router) → /billing/v1/orders

鉴权（对齐 wallet_router）：
- GET /         平台管理员（JWT admin/super_admin）可查任意租户/全部；普通租户/API Key 仅能查自身 tenant_id
- GET /{order_no} 需登录；admin 任意，租户仅能查自己归属的订单
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Depends, HTTPException

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import error
from qihuang_platform.billing.order import list_orders, get_order

order_router = APIRouter(prefix="/billing/v1/orders", tags=["orders"])


def _ensure_scope(request: Request, tenant_id: str | None) -> None:
    """租户归属校验：admin 放行任意（含查全部），其余仅能访问自身 tenant_id。"""
    roles = getattr(request.state, "roles", None) or []
    is_admin = "admin" in roles or "super_admin" in roles
    if is_admin:
        return
    caller_tenant = getattr(request.state, "tenant_id", None)
    if not caller_tenant:
        raise HTTPException(status_code=403, detail=error("FORBIDDEN", "无权访问订单"))
    if tenant_id and tenant_id != caller_tenant:
        raise HTTPException(status_code=403, detail=error("FORBIDDEN", "无权访问该租户订单"))


@order_router.get("")
def api_list_orders(
    request: Request,
    tenant_id: str | None = Query(None, description="租户ID；admin 可空=查全部"),
    order_type: str | None = Query(None, description="订单类型：recharge/addon/usage/plan"),
    period: str | None = Query(None, description="归属月份 YYYY-MM"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user: dict = Depends(get_current_principal),
):
    """订单列表（admin 可查任意，租户仅自身）。"""
    _ensure_scope(request, tenant_id)
    effective_tenant = tenant_id
    if not ("admin" in (getattr(request.state, "roles", None) or [])) and \
       not ("super_admin" in (getattr(request.state, "roles", None) or [])):
        effective_tenant = getattr(request.state, "tenant_id", None)
    return list_orders(effective_tenant, order_type=order_type, period_month=period, page=page, page_size=page_size)


@order_router.get("/{order_no}")
def api_get_order(
    request: Request,
    order_no: str,
    _user: dict = Depends(get_current_principal),
):
    """订单详情。"""
    resp = get_order(order_no)
    roles = getattr(request.state, "roles", None) or []
    is_admin = "admin" in roles or "super_admin" in roles
    if not is_admin and resp.get("data"):
        if resp["data"].get("tenant_id") != getattr(request.state, "tenant_id", None):
            raise HTTPException(status_code=403, detail=error("FORBIDDEN", "无权访问该订单"))
    return resp
