"""
结算中心订单核心（#B 方案）— 所有收费动作先落订单再处理。

订单类型 order_type：
  - recharge  充值包购买（积分 +N，成功即 PAID）
  - addon     agent 单加订阅（积分 -N，成功即 PAID）
  - usage     用量月度快照单（积分 -N，PAID，结算时生成）
  - plan      套餐变更/升级（预留）

状态 status：PENDING → PAID（成功）/ CANCELLED（失败/取消）
billed 标记：是否已并入月度结算单（阶段⑤结算聚合消费，PAID 且 billed=False 才入结算）
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Order
from qihuang_platform.gateway.response import success, error

logger = logging.getLogger("billing.order")

# 订单类型
ORDER_RECHARGE = "recharge"
ORDER_ADDON = "addon"
ORDER_USAGE = "usage"
ORDER_PLAN = "plan"

# 状态
ORDER_PENDING = "PENDING"
ORDER_PAID = "PAID"
ORDER_CANCELLED = "CANCELLED"

VALID_TYPES = {ORDER_RECHARGE, ORDER_ADDON, ORDER_USAGE, ORDER_PLAN}


def _month_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def gen_order_no() -> str:
    """订单号：ORD + yyyymmddHHMMSS + 4 位随机大写（唯一约束兜底，冲突极少）。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ORD{ts}{secrets.token_hex(2).upper()}"


def _serialize(o: Order) -> dict:
    return {
        "id": o.id,
        "order_no": o.order_no,
        "tenant_id": o.tenant_id,
        "order_type": o.order_type,
        "item_key": o.item_key,
        "item_label": o.item_label,
        "amount_cents": o.amount_cents,
        "credits": o.credits,
        "status": o.status,
        "billed": bool(o.billed),
        "period_month": o.period_month,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "extra": o.extra,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def create_order(
    tenant_id: str,
    order_type: str,
    item_key: str = "",
    item_label: str = "",
    *,
    amount_cents: int = 0,
    credits: int = 0,
    period_month: str | None = None,
    status: str = ORDER_PENDING,
    extra: dict | None = None,
) -> dict:
    """创建订单（独立会话提交）。返回统一响应，data 为订单字典。

    业务侧流程：先 create_order(PENDING) → 业务成功 mark_order_paid → 失败 mark_order_cancelled。
    中途崩溃留 PENDING 单可人工排查（结算只统计 PAID，安全）。
    """
    if order_type not in VALID_TYPES:
        return error("INVALID_PARAM", message=f"未知订单类型: {order_type}")
    db = SessionLocal()
    try:
        o = Order(
            order_no=gen_order_no(),
            tenant_id=tenant_id,
            order_type=order_type,
            item_key=item_key or "",
            item_label=item_label or "",
            amount_cents=int(amount_cents or 0),
            credits=int(credits or 0),
            status=status,
            period_month=period_month or _month_str(),
            extra=extra,
        )
        db.add(o)
        db.commit()
        db.refresh(o)
        return success(data=_serialize(o), message=f"订单 {o.order_no} 已创建")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[order] create_order 失败: %s", e)
        return error("INTERNAL_ERROR", message=f"创建订单失败: {e}")
    finally:
        db.close()


def mark_order_paid(order_no: str) -> dict:
    """订单支付成功：PENDING → PAID（记录 paid_at）。"""
    db = SessionLocal()
    try:
        o = db.query(Order).filter_by(order_no=order_no).first()
        if not o:
            return error("NOT_FOUND", message=f"订单不存在: {order_no}")
        if o.status == ORDER_PAID:
            return success(data=_serialize(o), message="订单已支付")
        if o.status == ORDER_CANCELLED:
            return error("INVALID_STATE", message=f"订单已取消，不可支付: {order_no}")
        o.status = ORDER_PAID
        o.paid_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(o)
        return success(data=_serialize(o), message=f"订单 {order_no} 已支付")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[order] mark_order_paid 失败: %s", e)
        return error("INTERNAL_ERROR", message=f"支付标记失败: {e}")
    finally:
        db.close()


def mark_order_cancelled(order_no: str) -> dict:
    """订单取消：PENDING → CANCELLED。"""
    db = SessionLocal()
    try:
        o = db.query(Order).filter_by(order_no=order_no).first()
        if not o:
            return error("NOT_FOUND", message=f"订单不存在: {order_no}")
        if o.status == ORDER_PAID:
            return error("INVALID_STATE", message=f"订单已支付，不可取消: {order_no}")
        o.status = ORDER_CANCELLED
        db.commit()
        db.refresh(o)
        return success(data=_serialize(o), message=f"订单 {order_no} 已取消")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[order] mark_order_cancelled 失败: %s", e)
        return error("INTERNAL_ERROR", message=f"取消订单失败: {e}")
    finally:
        db.close()


def list_orders(
    tenant_id: str | None = None,
    *,
    order_type: str | None = None,
    period_month: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询订单（按创建时间倒序）。admin 可传 tenant_id=None 查全部。"""
    page = max(1, page or 1)
    page_size = min(max(1, page_size or 20), 100)
    db = SessionLocal()
    try:
        q = db.query(Order)
        if tenant_id:
            q = q.filter(Order.tenant_id == tenant_id)
        if order_type:
            q = q.filter(Order.order_type == order_type)
        if period_month:
            q = q.filter(Order.period_month == period_month)
        total = q.count()
        rows = (
            q.order_by(Order.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return success(data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_serialize(o) for o in rows],
        }, message="订单列表")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[order] list_orders 失败: %s", e)
        return error("INTERNAL_ERROR", message=f"查询订单失败: {e}")
    finally:
        db.close()


def get_order(order_no: str) -> dict:
    """按订单号查详情。"""
    db = SessionLocal()
    try:
        o = db.query(Order).filter_by(order_no=order_no).first()
        if not o:
            return error("NOT_FOUND", message=f"订单不存在: {order_no}")
        return success(data=_serialize(o), message="订单详情")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[order] get_order 失败: %s", e)
        return error("INTERNAL_ERROR", message=f"查询订单失败: {e}")
    finally:
        db.close()
