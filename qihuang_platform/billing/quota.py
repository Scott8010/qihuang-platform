"""
配额控制 — 月度配额检查 / 调用记录 / 预警

子任务5: 配额检查与预警
- check_quota: 检查租户配额是否可用
- record_usage: 记录一次API调用（写CallLog）
- check_and_warn: 使用率>80%预警 / >100%超限
- get_tenant_plan_limits: 获取租户套餐限制

依赖模型:
  Subscription / Plan / CallLog
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import func, and_

from qihuang_platform.db.models import (
    Subscription, CallLog, Plan,
)
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.gateway.response import success, error


# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    """当前UTC时间"""
    return datetime.now(timezone.utc)


def _current_period_str() -> str:
    """当前月份 YYYY-MM（UTC）"""
    return _now().strftime("%Y-%m")


def _period_bounds(period_str: str):
    """
    将 YYYY-MM 转为 [月初, 下月初) 时间区间（UTC）。
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
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


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
        当月 now 落在旧订阅区间，仍按旧套餐计费/鉴权；跨月后新订阅自动生效，无需 cron。
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


def _get_tenant_plan(session, tenant_id: str) -> Optional[Plan]:
    """获取租户当前套餐"""
    subscription = _get_active_subscription(session, tenant_id)
    if not subscription:
        return None
    return (
        session.query(Plan)
        .filter(Plan.id == subscription.plan_id)
        .first()
    )


def _get_month_usage(session, tenant_id: str) -> Dict[str, int]:
    """
    查询当月已用 calls 与 tokens。
    返回 {used_calls, used_tokens}
    """
    period_str = _current_period_str()
    try:
        start, end = _period_bounds(period_str)
    except ValueError:
        return {"used_calls": 0, "used_tokens": 0}

    agg = (
        session.query(
            func.count(CallLog.id).label("calls"),
            func.coalesce(func.sum(CallLog.tokens_used), 0).label("tokens"),
        )
        .filter(
            and_(
                CallLog.tenant_id == tenant_id,
                CallLog.timestamp >= start,
                CallLog.timestamp < end,
            )
        )
        .one()
    )

    return {
        "used_calls": int(agg.calls or 0),
        "used_tokens": int(agg.tokens or 0),
    }


# ──────────────────────────────────────────────────────────────
# 核心业务函数
# ──────────────────────────────────────────────────────────────

def check_quota(tenant_id: str) -> dict:
    """
    检查租户配额是否可用。

    :param tenant_id: 租户ID
    :return: 统一响应，data 含:
        - remaining_calls: 剩余调用次数
        - remaining_tokens: 剩余Token数
        - quota_percentage: 配额使用率（0-100，保留1位小数）
        - is_exceeded: 是否已超限
    """
    session = SessionLocal()
    try:
        plan = _get_tenant_plan(session, tenant_id)
        if not plan:
            return error(
                "NOT_FOUND",
                message=f"租户 {tenant_id} 未找到有效订阅或套餐",
            )

        month_calls_limit = int(plan.month_calls or 0)
        month_tokens_limit = int(plan.month_tokens or 0)

        usage = _get_month_usage(session, tenant_id)
        used_calls = usage["used_calls"]
        used_tokens = usage["used_tokens"]

        remaining_calls = max(0, month_calls_limit - used_calls)
        remaining_tokens = max(0, month_tokens_limit - used_tokens)

        # 使用率取 calls 与 tokens 中的较大值
        calls_pct = round(
            (used_calls / month_calls_limit * 100), 1
        ) if month_calls_limit > 0 else 0.0
        tokens_pct = round(
            (used_tokens / month_tokens_limit * 100), 1
        ) if month_tokens_limit > 0 else 0.0
        quota_percentage = max(calls_pct, tokens_pct)

        is_exceeded = (
            used_calls >= month_calls_limit and month_calls_limit > 0
        ) or (
            used_tokens >= month_tokens_limit and month_tokens_limit > 0
        )

        # P0 append-only 事件日志：旁路记录计费/配额决策（绝不阻断业务）
        try:
            from qihuang_platform.event_log import emit_event
            emit_event(
                tenant_id=tenant_id, agent_key=None, event_type="DECISION",
                payload={
                    "action": "quota_check",
                    "plan_name": plan.plan_name,
                    "remaining_calls": remaining_calls,
                    "remaining_tokens": remaining_tokens,
                    "quota_percentage": quota_percentage,
                    "is_exceeded": is_exceeded,
                },
            )
        except Exception:
            pass

        data = {
            "tenant_id": tenant_id,
            "plan_name": plan.plan_name,
            "month_calls_limit": month_calls_limit,
            "month_tokens_limit": month_tokens_limit,
            "used_calls": used_calls,
            "used_tokens": used_tokens,
            "remaining_calls": remaining_calls,
            "remaining_tokens": remaining_tokens,
            "calls_percentage": calls_pct,
            "tokens_percentage": tokens_pct,
            "quota_percentage": quota_percentage,
            "is_exceeded": is_exceeded,
        }

        return success(data=data, message="配额检查完成")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"配额检查失败: {e}")
    finally:
        session.close()


def record_usage(
    tenant_id: str,
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: float,
    tokens_used: int,
    cost_cents: float,
    user_id: Optional[str] = None,
    is_3d: bool = False,
    trace_id: Optional[str] = None,
    app_key: Optional[str] = None,
    org_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    cdn_traffic_bytes: int = 0,
) -> dict:
    """
    记录一次API调用（创建CallLog记录）。

    :param tenant_id: 租户ID
    :param endpoint: 请求路径
    :param method: HTTP方法 GET/POST/...
    :param status_code: HTTP状态码
    :param latency_ms: 延迟毫秒
    :param tokens_used: 消耗Token数
    :param cost_cents: 本次调用费用（分）
    :param user_id: 用户ID（可选）
    :param is_3d: 是否3D模块调用
    :param trace_id: 链路追踪ID（可选）
    :param app_key: 调用方API Key（可选）
    :param org_id: 机构ID（可选）
    :param ip: 客户端IP（可选）
    :param user_agent: User-Agent（可选）
    :param cdn_traffic_bytes: CDN流量字节（3D模块场景）
    :return: 统一响应，data 为 call_log 记录字典
    """
    session = SessionLocal()
    try:
        call_log = CallLog(
            tenant_id=tenant_id,
            trace_id=trace_id,
            endpoint=endpoint,
            method=method,
            user_id=user_id,
            app_key=app_key,
            org_id=org_id,
            status_code=status_code,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_cents=cost_cents,
            ip=ip,
            user_agent=user_agent,
            is_3d=is_3d,
            cdn_traffic_bytes=cdn_traffic_bytes,
            timestamp=_now(),
        )
        session.add(call_log)
        session.flush()
        session.commit()
        session.refresh(call_log)

        data = {
            "id": call_log.id,
            "trace_id": call_log.trace_id,
            "endpoint": call_log.endpoint,
            "method": call_log.method,
            "tenant_id": call_log.tenant_id,
            "user_id": call_log.user_id,
            "app_key": call_log.app_key,
            "status_code": call_log.status_code,
            "latency_ms": call_log.latency_ms,
            "tokens_used": call_log.tokens_used,
            "cost_cents": call_log.cost_cents,
            "is_3d": call_log.is_3d,
            "cdn_traffic_bytes": call_log.cdn_traffic_bytes,
            "timestamp": call_log.timestamp.isoformat() if call_log.timestamp else None,
        }

        return success(data=data, message="调用记录已保存")
    except Exception as e:
        session.rollback()
        return error("INTERNAL_ERROR", message=f"记录调用失败: {e}")
    finally:
        session.close()


def check_and_warn(tenant_id: str) -> dict:
    """
    检查配额使用率并触发预警。

    - 使用率 > 100%: 返回 exceeded
    - 使用率 > 80%:  返回 warning
    - 否则: 返回 normal

    :param tenant_id: 租户ID
    :return: 统一响应，data 含:
        - should_warn: 是否需要预警
        - warning_level: "normal" / "warning" / "exceeded"
        - message: 预警描述
        - quota_percentage: 使用率
    """
    session = SessionLocal()
    try:
        plan = _get_tenant_plan(session, tenant_id)
        if not plan:
            return error(
                "NOT_FOUND",
                message=f"租户 {tenant_id} 未找到有效订阅或套餐",
            )

        month_calls_limit = int(plan.month_calls or 0)
        month_tokens_limit = int(plan.month_tokens or 0)

        usage = _get_month_usage(session, tenant_id)
        used_calls = usage["used_calls"]
        used_tokens = usage["used_tokens"]

        calls_pct = round(
            (used_calls / month_calls_limit * 100), 1
        ) if month_calls_limit > 0 else 0.0
        tokens_pct = round(
            (used_tokens / month_tokens_limit * 100), 1
        ) if month_tokens_limit > 0 else 0.0
        quota_percentage = max(calls_pct, tokens_pct)

        # 判断预警等级
        if quota_percentage > 100:
            should_warn = True
            warning_level = "exceeded"
            message = (
                f"配额已超限: 调用 {used_calls}/{month_calls_limit}（{calls_pct}%），"
                f"Token {used_tokens}/{month_tokens_limit}（{tokens_pct}%）"
            )
        elif quota_percentage > 80:
            should_warn = True
            warning_level = "warning"
            message = (
                f"配额使用率已达 {quota_percentage}%: 调用 {used_calls}/{month_calls_limit}，"
                f"Token {used_tokens}/{month_tokens_limit}，请关注用量"
            )
        else:
            should_warn = False
            warning_level = "normal"
            message = f"配额使用正常（{quota_percentage}%）"

        data = {
            "tenant_id": tenant_id,
            "plan_name": plan.plan_name,
            "should_warn": should_warn,
            "warning_level": warning_level,
            "message": message,
            "quota_percentage": quota_percentage,
            "calls_percentage": calls_pct,
            "tokens_percentage": tokens_pct,
            "used_calls": used_calls,
            "used_tokens": used_tokens,
            "month_calls_limit": month_calls_limit,
            "month_tokens_limit": month_tokens_limit,
        }

        return success(data=data, message="配额预警检查完成")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"配额预警检查失败: {e}")
    finally:
        session.close()


def get_tenant_plan_limits(tenant_id: str) -> dict:
    """
    获取租户套餐限制。

    :param tenant_id: 租户ID
    :return: 统一响应，data 含:
        - qps: QPS限制
        - month_calls: 月调用次数限制
        - month_tokens: 月Token限制
        - plan_name: 套餐标识名
        - display_name: 套餐显示名
        - features_json: 功能特性开关
    """
    session = SessionLocal()
    try:
        plan = _get_tenant_plan(session, tenant_id)
        if not plan:
            return error(
                "NOT_FOUND",
                message=f"租户 {tenant_id} 未找到有效订阅或套餐",
            )

        data = {
            "tenant_id": tenant_id,
            "plan_id": plan.id,
            "plan_name": plan.plan_name,
            "display_name": plan.display_name,
            "scene_type": plan.scene_type,
            "qps": int(plan.qps or 0),
            "month_calls": int(plan.month_calls or 0),
            "month_tokens": int(plan.month_tokens or 0),
            "price_cents": int(plan.price_cents or 0),
            "features_json": plan.features_json or {},
            "status": plan.status,
        }

        return success(data=data, message="套餐限制查询完成")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"查询套餐限制失败: {e}")
    finally:
        session.close()
