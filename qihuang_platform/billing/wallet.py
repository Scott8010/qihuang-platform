"""
计费中台钱包核心（#474）— 积分池增删查 + 基本包按月清零 + 叠加包永久。

设计（老板 2026-08-25 拍板）：
  - 通用余额池（tenant 单桶，不绑 agent）：base_credits（基本包当月清）+ addon_credits（叠加包永久）
  - 计价：调 LLM token×A（多模态×1.5）/ 不调 LLM 固定积分/次（pricing_config.FLAT_CREDITS_PER_CALL）
  - 扣费顺序：先 base_credits，不足再 addon_credits；两池皆空 → QUOTA_EXCEEDED 不放行
  - 旁路非阻断：计量异常不阻断主响应（best-effort）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Wallet, Subscription, Plan
from qihuang_platform.gateway.response import success, error
from qihuang_platform.billing.pricing_config import (
    compute_credits, get_base_credits, get_pack,
)

logger = logging.getLogger("billing.wallet")


def _month_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_or_create(db, tenant_id: str) -> Wallet:
    w = db.query(Wallet).filter_by(tenant_id=tenant_id).first()
    if w is None:
        w = Wallet(tenant_id=tenant_id)
        db.add(w)
        db.flush()
    return w


def _current_plan_id(db, tenant_id: str) -> str:
    sub = (
        db.query(Subscription)
        .filter_by(tenant_id=tenant_id, status="active")
        .order_by(Subscription.start_date.desc())
        .first()
    )
    if not sub:
        return ""
    plan = db.query(Plan).filter_by(id=sub.plan_id).first()
    return plan.id if plan else ""


def maybe_reset_base_monthly(db, w: Wallet) -> None:
    """基本包按月清零：跨月则 base_credits 归零并按当前套餐重新赠送。"""
    cur = _month_str()
    if w.period_month != cur:
        w.base_credits = get_base_credits(_current_plan_id(db, w.tenant_id))
        w.period_month = cur
        db.flush()


def recharge(tenant_id: str, pack_key: str) -> dict:
    """叠加包充值（永久有效）。"""
    pack = get_pack(pack_key)
    if not pack:
        return error("INVALID_PARAM", message=f"未知充值包: {pack_key}")
    db = SessionLocal()
    try:
        w = _get_or_create(db, tenant_id)
        w.addon_credits += pack["credits"]
        w.total_bought += pack["credits"]
        w.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(w)
        return success(data={
            "tenant_id": tenant_id,
            "pack": pack_key,
            "added_credits": pack["credits"],
            "addon_credits": w.addon_credits,
            "base_credits": w.base_credits,
            "total_bought": w.total_bought,
        }, message=f"充值成功：{pack['label']} +{pack['credits']}积分")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=f"充值失败: {e}")
    finally:
        db.close()


def get_balance(tenant_id: str) -> dict:
    """查询余额（顺带触发基本包按月清零）。"""
    db = SessionLocal()
    try:
        w = _get_or_create(db, tenant_id)
        maybe_reset_base_monthly(db, w)
        db.commit()
        return success(data={
            "tenant_id": tenant_id,
            "base_credits": w.base_credits,
            "addon_credits": w.addon_credits,
            "total_credits": w.base_credits + w.addon_credits,
            "period_month": w.period_month,
        }, message="余额查询")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=f"查询失败: {e}")
    finally:
        db.close()


def consume_credits(
    tenant_id: str,
    agent_key: str,
    token_used: int = 0,
    is_multimodal: bool = False,
    uses_llm: Optional[bool] = None,
) -> Tuple[bool, int]:
    """扣减积分（旁路非阻断）。返回 (是否放行, 消耗积分)。

    - uses_llm 未传则从 registry 取（默认 True）
    - 先扣 base_credits，不足再扣 addon_credits
    - 两池皆不足 → 不放行（返回 False），原子回滚不扣任何
    """
    if uses_llm is None:
        from qihuang_platform.agent.registry import get_agent
        spec = get_agent(agent_key)
        uses_llm = bool(spec and spec.get("uses_llm", True))
    cost = compute_credits(agent_key, token_used, is_multimodal, uses_llm)
    db = SessionLocal()
    try:
        w = _get_or_create(db, tenant_id)
        maybe_reset_base_monthly(db, w)
        if w.base_credits >= cost:
            w.base_credits -= cost
        else:
            rem = cost - w.base_credits
            w.base_credits = 0
            if w.addon_credits >= rem:
                w.addon_credits -= rem
            else:
                db.rollback()  # 两池皆不足，原子不放行
                return False, cost
        w.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True, cost
    except Exception as e:
        db.rollback()
        logger.warning("[wallet] consume_credits 失败(降级放行): %s", e)
        return True, 0  # 旁路非阻断：计量异常不阻断主响应
    finally:
        db.close()
