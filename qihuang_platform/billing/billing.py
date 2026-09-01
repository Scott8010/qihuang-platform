"""
计费账单 — 月度账单生成与状态流转

子任务4: 月账单生成
- 按月汇总 call_log（总调用数/总Token/总费用）
- 查询订阅与套餐，计算应付金额
- 状态流转: DRAFT → ISSUED → PAID 或 ISSUED → OVERDUE

依赖模型:
  Bill / Subscription / Plan / CallLog / AuditLog
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import func, and_

from qihuang_platform.db.models import (
    Subscription, CallLog, Bill, Plan, AuditLog,
)
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.billing.order import (
    ensure_usage_snapshot, paid_orders_in_period,
    _serialize as serialize_order,
)


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    """当前UTC时间"""
    return datetime.now(timezone.utc)


def _period_bounds(period_str: str) -> (datetime, datetime):
    """
    将 YYYY-MM 字符串转换为 [月初, 下月初) 的时间区间。
    period_str 例: "2026-07"
    返回 (start_utc, end_utc)，end 为下月1号0点（UTC）。
    """
    try:
        year, month = period_str.split("-")
        year = int(year)
        month = int(month)
    except (ValueError, AttributeError):
        raise ValueError(f"账单周期格式错误，应为 YYYY-MM，实际: {period_str}")

    if month < 1 or month > 12:
        raise ValueError(f"账单周期月份非法: {period_str}")

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    # 下月1号
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _current_period_str() -> str:
    """当前月份的 YYYY-MM 字符串（UTC）"""
    return _now().strftime("%Y-%m")


def _serialize_bill(bill: Bill) -> Dict[str, Any]:
    """将 Bill ORM 对象序列化为字典"""
    return {
        "id": bill.id,
        "tenant_id": bill.tenant_id,
        "bill_period": bill.bill_period,
        "total_calls": bill.total_calls,
        "total_tokens": bill.total_tokens,
        "total_cost_cents": bill.total_cost_cents,
        "status": bill.status,
        "issued_at": bill.issued_at.isoformat() if bill.issued_at else None,
        "paid_at": bill.paid_at.isoformat() if bill.paid_at else None,
        "extra": bill.extra or {},
        "created_at": bill.created_at.isoformat() if bill.created_at else None,
    }


def _norm_dt(dt):
    """统一时间：aware 转 naive UTC，便于与库中 naive 时间比较"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _get_active_subscription(session, tenant_id: str, now=None) -> Optional[Subscription]:
    """获取租户「当前生效」的订阅（按时间区间生效，兼容次月生效的预约升级）。

    生效条件：status in (active, scheduled) 且 start_date <= now < (end_date 或无限)。
      - 普通订阅 end_date 为空 → 一直生效。
      - 预约升级：新建 status=scheduled，start_date=次月1号；当前订阅 end_date 设为次月1号。
        当月仍按旧套餐计费/出账；跨月后新订阅自动生效，无需 cron。
    """
    if now is None:
        now = _now()
    now = _norm_dt(now)
    rows = (
        session.query(Subscription)
        .filter(
            and_(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_(["active", "scheduled"]),
                Subscription.start_date <= now,
            )
        )
        .order_by(Subscription.start_date.desc())
        .all()
    )
    for s in rows:
        end = _norm_dt(s.end_date)
        if end is None or end > now:
            return s
    return None


def _get_period_usage(session, tenant_id: str, start: datetime, end: datetime) -> Dict[str, int]:
    """
    汇总指定时间区间内租户的 call_log 用量。
    返回 {total_calls, total_tokens, total_cost_cents}
    """
    # 调用次数（直接count行数）
    # #B 修复：排除单加订阅费 CallLog（endpoint 含 addon_subscribe），它属订单/结算项，不是用量
    total_calls = (
        session.query(func.count(CallLog.id))
        .filter(
            and_(
                CallLog.tenant_id == tenant_id,
                CallLog.timestamp >= start,
                CallLog.timestamp < end,
                CallLog.endpoint.notlike("%addon_subscribe"),
            )
        )
        .scalar()
    ) or 0

    # token 与费用汇总（SUM）
    agg = (
        session.query(
            func.coalesce(func.sum(CallLog.tokens_used), 0).label("total_tokens"),
            func.coalesce(func.sum(CallLog.cost_cents), 0).label("total_cost"),
        )
        .filter(
            and_(
                CallLog.tenant_id == tenant_id,
                CallLog.timestamp >= start,
                CallLog.timestamp < end,
                CallLog.endpoint.notlike("%addon_subscribe"),
            )
        )
        .one()
    )

    return {
        "total_calls": int(total_calls),
        "total_tokens": int(agg.total_tokens or 0),
        "total_cost_cents": int(round(float(agg.total_cost or 0))),
    }


# ──────────────────────────────────────────────────────────────
# 核心业务函数
# ──────────────────────────────────────────────────────────────

def generate_monthly_bill(tenant_id: str, period_str: str) -> dict:
    """
    按月汇总 call_log 生成账单（状态 DRAFT）。

    :param tenant_id: 租户ID
    :param period_str: 账单周期 YYYY-MM，例如 "2026-07"
    :return: 统一响应，data 为账单字典

    流程:
      1. 校验周期格式
      2. 若该租户该月已有非 DRAFT 状态账单，直接返回已有账单
      3. 查询当月 call_log 汇总（calls/tokens/cost）
      4. 查询订阅与套餐，计算应付金额（套餐价 + 超额用量）
      5. 创建 Bill 记录，状态 DRAFT
    """
    session = SessionLocal()
    try:
        # 1. 校验周期格式
        try:
            start, end = _period_bounds(period_str)
        except ValueError as e:
            return error("INVALID_FORMAT", message=str(e))

        # 2. 检查是否已有账单
        existing = (
            session.query(Bill)
            .filter(
                and_(
                    Bill.tenant_id == tenant_id,
                    Bill.bill_period == period_str,
                )
            )
            .first()
        )
        if existing and existing.status != "DRAFT":
            # 已出账/已付款/已逾期，不重复生成
            return success(
                data=_serialize_bill(existing),
                message=f"账单 {period_str} 已存在（状态: {existing.status}）",
            )

        # 3. 汇总当月用量
        usage = _get_period_usage(session, tenant_id, start, end)

        # 3.5 结算中心 #B：确保用量快照单 + 聚合当月全部 PAID 订单
        ensure_usage_snapshot(
            session, tenant_id, period_str,
            total_calls=usage["total_calls"],
            total_tokens=usage["total_tokens"],
            cost_cents=usage["total_cost_cents"],
        )
        orders = paid_orders_in_period(session, tenant_id, period_str)
        order_items = [serialize_order(o) for o in orders]
        recharge_cents = sum(o.amount_cents or 0 for o in orders if o.order_type == "recharge")
        addon_cents = sum(o.amount_cents or 0 for o in orders if o.order_type == "addon")
        usage_cents = sum(o.amount_cents or 0 for o in orders if o.order_type == "usage")

        # 4. 查询订阅与套餐，计算应付金额
        subscription = _get_active_subscription(session, tenant_id)
        plan = None
        plan_price_cents = 0
        overage_cost_cents = 0
        plan_name = ""
        features_json = {}

        if subscription:
            plan = (
                session.query(Plan)
                .filter(Plan.id == subscription.plan_id)
                .first()
            )
            if plan:
                plan_price_cents = int(plan.price_cents or 0)
                plan_name = plan.plan_name

                # 计算超额用量费用（超出套餐月配额部分）
                # 注意: cost_cents 已经在 call_log 中按调用记录累计，
                # 这里把套餐价 + 已记录的调用成本合并为应付总额
                # 超额逻辑由 quota.py 在调用时控制，此处账单以实际发生的 cost 为准
                overage_cost_cents = usage["total_cost_cents"]

        # 应付金额 = 套餐订阅费 + 实际调用产生的费用 + 单加 agent 订阅费
        # （充值订单为预付款，不计入应付，单独在 summary 列出供对账）
        total_payable_cents = plan_price_cents + overage_cost_cents + addon_cents

        # 5. 创建或更新账单
        extra = {
            "plan_name": plan_name,
            "plan_price_cents": plan_price_cents,
            "overage_cost_cents": overage_cost_cents,
            "subscription_id": subscription.id if subscription else None,
            "generated_at": _now().isoformat(),
            "orders": order_items,
            "summary": {
                "recharge_cents": recharge_cents,
                "addon_cents": addon_cents,
                "usage_cents": usage_cents,
            },
        }

        if existing and existing.status == "DRAFT":
            # 已有草稿，刷新汇总数据
            existing.total_calls = usage["total_calls"]
            existing.total_tokens = usage["total_tokens"]
            existing.total_cost_cents = total_payable_cents
            existing.extra = extra
            session.flush()
            bill = existing
        else:
            bill = Bill(
                tenant_id=tenant_id,
                bill_period=period_str,
                total_calls=usage["total_calls"],
                total_tokens=usage["total_tokens"],
                total_cost_cents=total_payable_cents,
                status="DRAFT",
                extra=extra,
            )
            session.add(bill)
            session.flush()

        session.commit()
        session.refresh(bill)

        # 审计日志
        session.add(AuditLog(
            tenant_id=tenant_id,
            action="BILL_GENERATE",
            target_type="Bill",
            target_id=bill.id,
            detail={"bill_period": period_str, "total_cost_cents": total_payable_cents},
            success=True,
        ))
        session.commit()

        return success(
            data=_serialize_bill(bill),
            message=f"账单 {period_str} 生成成功",
        )
    except Exception as e:
        session.rollback()
        return error("INTERNAL_ERROR", message=f"生成账单失败: {e}")
    finally:
        session.close()


def issue_bill(bill_id: str) -> dict:
    """
    确认出账: DRAFT → ISSUED。

    :param bill_id: 账单ID
    :return: 统一响应，data 为更新后的账单字典
    """
    session = SessionLocal()
    try:
        bill = session.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return error("NOT_FOUND", message=f"账单不存在: {bill_id}")

        if bill.status != "DRAFT":
            return error(
                "INVALID_PARAM",
                message=f"账单状态非DRAFT，无法出账（当前: {bill.status}）",
            )

        bill.status = "ISSUED"
        bill.issued_at = _now()
        session.flush()
        session.commit()
        session.refresh(bill)

        # 审计日志
        session.add(AuditLog(
            tenant_id=bill.tenant_id,
            action="BILL_ISSUE",
            target_type="Bill",
            target_id=bill.id,
            detail={"bill_period": bill.bill_period},
            success=True,
        ))
        session.commit()

        return success(data=_serialize_bill(bill), message="账单已出账")
    except Exception as e:
        session.rollback()
        return error("INTERNAL_ERROR", message=f"出账失败: {e}")
    finally:
        session.close()


def mark_paid(bill_id: str) -> dict:
    """
    标记已付: ISSUED → PAID。

    :param bill_id: 账单ID
    :return: 统一响应
    """
    session = SessionLocal()
    try:
        bill = session.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return error("NOT_FOUND", message=f"账单不存在: {bill_id}")

        if bill.status != "ISSUED":
            return error(
                "INVALID_PARAM",
                message=f"账单状态非ISSUED，无法标记已付（当前: {bill.status}）",
            )

        bill.status = "PAID"
        bill.paid_at = _now()
        session.flush()
        session.commit()
        session.refresh(bill)

        session.add(AuditLog(
            tenant_id=bill.tenant_id,
            action="BILL_PAID",
            target_type="Bill",
            target_id=bill.id,
            detail={"bill_period": bill.bill_period},
            success=True,
        ))
        session.commit()

        return success(data=_serialize_bill(bill), message="账单已标记为已付款")
    except Exception as e:
        session.rollback()
        return error("INTERNAL_ERROR", message=f"标记付款失败: {e}")
    finally:
        session.close()


def mark_overdue(bill_id: str) -> dict:
    """
    标记逾期: ISSUED → OVERDUE。

    :param bill_id: 账单ID
    :return: 统一响应
    """
    session = SessionLocal()
    try:
        bill = session.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return error("NOT_FOUND", message=f"账单不存在: {bill_id}")

        if bill.status != "ISSUED":
            return error(
                "INVALID_PARAM",
                message=f"账单状态非ISSUED，无法标记逾期（当前: {bill.status}）",
            )

        bill.status = "OVERDUE"
        session.flush()
        session.commit()
        session.refresh(bill)

        session.add(AuditLog(
            tenant_id=bill.tenant_id,
            action="BILL_OVERDUE",
            target_type="Bill",
            target_id=bill.id,
            detail={"bill_period": bill.bill_period},
            success=True,
        ))
        session.commit()

        return success(data=_serialize_bill(bill), message="账单已标记为逾期")
    except Exception as e:
        session.rollback()
        return error("INTERNAL_ERROR", message=f"标记逾期失败: {e}")
    finally:
        session.close()


def list_bills(tenant_id: str, page: int = 1, page_size: int = 20) -> dict:
    """
    分页查询租户的账单列表（按创建时间倒序）。

    :param tenant_id: 租户ID
    :param page: 页码（从1开始）
    :param page_size: 每页条数
    :return: 统一分页响应
    """
    session = SessionLocal()
    try:
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        query = (
            session.query(Bill)
            .filter(Bill.tenant_id == tenant_id)
            .order_by(Bill.created_at.desc())
        )

        total = query.count()
        offset = (page - 1) * page_size
        bills = query.offset(offset).limit(page_size).all()

        items = [_serialize_bill(b) for b in bills]
        return paginated(items=items, total=total, page=page, page_size=page_size)
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"查询账单列表失败: {e}")
    finally:
        session.close()


def get_bill_detail(bill_id: str) -> dict:
    """
    账单详情（含 call_log 明细汇总: 按endpoint聚合 + 按是否3D聚合）。

    :param bill_id: 账单ID
    :return: 统一响应，data 含账单基础信息 + usage_breakdown
    """
    session = SessionLocal()
    try:
        bill = session.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return error("NOT_FOUND", message=f"账单不存在: {bill_id}")

        # 解析账单周期时间区间
        try:
            start, end = _period_bounds(bill.bill_period)
        except ValueError:
            start, end = None, None

        detail = _serialize_bill(bill)

        if start and end:
            # 按 endpoint 聚合
            endpoint_rows = (
                session.query(
                    CallLog.endpoint,
                    func.count(CallLog.id).label("calls"),
                    func.coalesce(func.sum(CallLog.tokens_used), 0).label("tokens"),
                    func.coalesce(func.sum(CallLog.cost_cents), 0).label("cost"),
                )
                .filter(
                    and_(
                        CallLog.tenant_id == bill.tenant_id,
                        CallLog.timestamp >= start,
                        CallLog.timestamp < end,
                    )
                )
                .group_by(CallLog.endpoint)
                .all()
            )
            by_endpoint = [
                {
                    "endpoint": row.endpoint or "(unknown)",
                    "calls": int(row.calls or 0),
                    "tokens": int(row.tokens or 0),
                    "cost_cents": int(round(float(row.cost or 0))),
                }
                for row in endpoint_rows
            ]

            # 按 is_3d 聚合
            three_d_rows = (
                session.query(
                    CallLog.is_3d,
                    func.count(CallLog.id).label("calls"),
                    func.coalesce(func.sum(CallLog.tokens_used), 0).label("tokens"),
                    func.coalesce(func.sum(CallLog.cost_cents), 0).label("cost"),
                    func.coalesce(func.sum(CallLog.cdn_traffic_bytes), 0).label("cdn_bytes"),
                )
                .filter(
                    and_(
                        CallLog.tenant_id == bill.tenant_id,
                        CallLog.timestamp >= start,
                        CallLog.timestamp < end,
                    )
                )
                .group_by(CallLog.is_3d)
                .all()
            )
            by_module = {
                "3d": {"calls": 0, "tokens": 0, "cost_cents": 0, "cdn_bytes": 0},
                "standard": {"calls": 0, "tokens": 0, "cost_cents": 0, "cdn_bytes": 0},
            }
            for row in three_d_rows:
                key = "3d" if row.is_3d else "standard"
                by_module[key]["calls"] = int(row.calls or 0)
                by_module[key]["tokens"] = int(row.tokens or 0)
                by_module[key]["cost_cents"] = int(round(float(row.cost or 0)))
                by_module[key]["cdn_bytes"] = int(row.cdn_bytes or 0)

            detail["usage_breakdown"] = {
                "by_endpoint": by_endpoint,
                "by_module": by_module,
            }
        else:
            detail["usage_breakdown"] = None

        return success(data=detail, message="账单详情")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"查询账单详情失败: {e}")
    finally:
        session.close()


def get_usage_summary(tenant_id: str) -> dict:
    """
    当月用量汇总: 总调用数 / 总Token / 配额使用率。

    :param tenant_id: 租户ID
    :return: 统一响应，data 含 usage 与 quota 字段
    """
    session = SessionLocal()
    try:
        period_str = _current_period_str()
        start, end = _period_bounds(period_str)
        usage = _get_period_usage(session, tenant_id, start, end)

        # 查询套餐配额
        subscription = _get_active_subscription(session, tenant_id)
        plan = None
        month_calls_limit = 0
        month_tokens_limit = 0
        plan_name = ""

        if subscription:
            plan = (
                session.query(Plan)
                .filter(Plan.id == subscription.plan_id)
                .first()
            )
            if plan:
                month_calls_limit = int(plan.month_calls or 0)
                month_tokens_limit = int(plan.month_tokens or 0)
                plan_name = plan.plan_name

        # 使用率（保留1位小数）
        calls_pct = round(
            (usage["total_calls"] / month_calls_limit * 100), 1
        ) if month_calls_limit > 0 else 0.0
        tokens_pct = round(
            (usage["total_tokens"] / month_tokens_limit * 100), 1
        ) if month_tokens_limit > 0 else 0.0

        # 综合使用率（取较大值作为配额使用率）
        quota_percentage = max(calls_pct, tokens_pct)

        data = {
            "period": period_str,
            "plan_name": plan_name,
            "usage": {
                "total_calls": usage["total_calls"],
                "total_tokens": usage["total_tokens"],
                "total_cost_cents": usage["total_cost_cents"],
            },
            "quota": {
                "month_calls_limit": month_calls_limit,
                "month_tokens_limit": month_tokens_limit,
                "calls_percentage": calls_pct,
                "tokens_percentage": tokens_pct,
                "quota_percentage": quota_percentage,
                "remaining_calls": max(0, month_calls_limit - usage["total_calls"]),
                "remaining_tokens": max(0, month_tokens_limit - usage["total_tokens"]),
                "is_exceeded": quota_percentage >= 100,
            },
        }

        return success(data=data, message="当月用量汇总")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"查询用量汇总失败: {e}")
    finally:
        session.close()
