"""
真计费对账模块（#656 收尾摊 · 运行时真计费对账）

真值链三层：
  CallLog(实时真扣费真值源)  →  Order(type=usage 月度快照单)  →  Bill(月度结算单)

对账目标：核对三层一致 + 抓异常
  1) 漏结算  —— CallLog 有费用但无对应 usage 快照单（Order）
  2) 数值漂移 —— CallLog 聚合值 vs usage 单 / Bill 不一致（> 阈值）
  3) 裸 0    —— 成功(200)的 agent 调用 cost_cents<=0（引擎漏回传 usage，兜底也未生效）
  4) 双写嫌疑 —— 同 trace_id 在时间窗内出现 >1 条 CallLog（历史双写残留）

设计原则：旁路非阻断。本模块只读 + 按需补 usage 快照单，绝不触碰钱包/扣费主链路。
异常仅 logger.warning，调用方自行决定告警/展示。

复用：period 边界用 quota._period_bounds（与配额/计费口径严格一致）。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func

from qihuang_platform.db.models import CallLog, Order, Bill
from qihuang_platform.billing.order import (
    ORDER_USAGE,
    ensure_usage_snapshot,
)
from qihuang_platform.billing.quota import _period_bounds

logger = logging.getLogger("billing.reconcile")

# 数值漂移阈值：CallLog 聚合金额 vs 聚合层(usage单/Bill) 偏差超过该值视为不一致
#   - 绝对差 > 1 分（分是最小货币单位，1 分内视为取整对齐）
#   - 或 相对差 > 1%（量级较大时防浮点/舍入累积）
DRIFT_ABS_CENTS = 1
DRIFT_REL_RATIO = 0.01

# agent 调用前缀（与 agent/__init__.py 挂载前缀一致）
_AGENT_EP_PREFIX = "/api/v1/agent/"


def _period_bounds_safe(period: str):
    """包一层 quota._period_bounds，坏格式返回 None（调用方跳过）。"""
    try:
        return _period_bounds(period)
    except (ValueError, AttributeError, TypeError) as e:
        logger.warning("[reconcile] 周期格式错误 %s: %s", period, e)
        return None


def aggregate_calllog(session, tenant_id: str, period: str) -> dict:
    """从 CallLog 聚合某租户某月真扣费真值。

    返回 {calls, tokens, cost_cents, ok}。cost_cents 四舍五入到 2 位小数。
    """
    bounds = _period_bounds_safe(period)
    if bounds is None:
        return {"calls": 0, "tokens": 0, "cost_cents": 0.0, "ok": False}
    start, end = bounds
    agg = (
        session.query(
            func.count(CallLog.id),
            func.coalesce(func.sum(CallLog.tokens_used), 0),
            func.coalesce(func.sum(CallLog.cost_cents), 0.0),
        )
        .filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= start,
            CallLog.timestamp < end,
        )
        .one()
    )
    calls = int(agg[0] or 0)
    tokens = int(agg[1] or 0)
    cost = round(float(agg[2] or 0.0), 2)
    return {"calls": calls, "tokens": tokens, "cost_cents": cost, "ok": True}


def _load_usage_order(session, tenant_id: str, period: str) -> Optional[Order]:
    """查某租户某月 usage 月度快照单（幂等键：tenant+type+period）。"""
    return (
        session.query(Order)
        .filter(
            Order.tenant_id == tenant_id,
            Order.order_type == ORDER_USAGE,
            Order.period_month == period,
        )
        .first()
    )


def _load_bill(session, tenant_id: str, period: str) -> Optional[Bill]:
    """查某租户某月结算单。"""
    return (
        session.query(Bill)
        .filter(Bill.tenant_id == tenant_id, Bill.bill_period == period)
        .first()
    )


def reconcile_tenant(session, tenant_id: str, period: str) -> dict:
    """单租户三层对账：CallLog 真值 vs usage 单 vs Bill。

    返回：
      {
        tenant_id, period, ok,
        calllog: {calls, tokens, cost_cents},
        usage_order: {exists, order_no, cost_cents, calls} | None,
        bill: {exists, bill_period, total_cost_cents, total_calls} | None,
        healthy: bool,
        gaps: [ {type, severity, detail} ... ]
      }
    """
    cl = aggregate_calllog(session, tenant_id, period)
    if not cl["ok"]:
        return {
            "tenant_id": tenant_id,
            "period": period,
            "ok": False,
            "calllog": cl,
            "usage_order": None,
            "bill": None,
            "healthy": False,
            "gaps": [{"type": "bad_period", "severity": "error",
                       "detail": f"周期格式错误: {period}"}],
        }

    usage = _load_usage_order(session, tenant_id, period)
    bill = _load_bill(session, tenant_id, period)
    gaps: list = []

    # 1) 漏结算：CallLog 有调用/费用，但无 usage 快照单
    if cl["calls"] > 0 and usage is None:
        gaps.append({
            "type": "missing_usage_order",
            "severity": "warning",
            "detail": (
                f"CallLog 有 {cl['calls']} 笔调用/¥{cl['cost_cents']/100:.2f}，"
                f"但无 usage 月度快照单（漏结算）"
            ),
        })
    # 2) 数值漂移：CallLog 费用 vs usage 单金额
    if usage is not None:
        o_cost = float(usage.amount_cents or 0)
        if _is_drift(cl["cost_cents"], o_cost):
            gaps.append({
                "type": "cost_drift_vs_usage_order",
                "severity": "warning",
                "detail": (
                    f"CallLog 费用 ¥{cl['cost_cents']/100:.2f} vs "
                    f"usage 单 ¥{o_cost/100:.2f} 偏差超阈值"
                ),
            })
        o_calls = int((usage.extra or {}).get("total_calls", 0) or 0)
        if o_calls and o_calls != cl["calls"]:
            gaps.append({
                "type": "calls_mismatch_vs_usage_order",
                "severity": "info",
                "detail": f"CallLog 调用 {cl['calls']} 笔 vs usage 单 {o_calls} 笔",
            })

    # 3) 数值漂移：CallLog vs Bill（若已出结算单）
    if bill is not None:
        b_cost = float(bill.total_cost_cents or 0)
        if _is_drift(cl["cost_cents"], b_cost):
            gaps.append({
                "type": "cost_drift_vs_bill",
                "severity": "warning",
                "detail": (
                    f"CallLog 费用 ¥{cl['cost_cents']/100:.2f} vs "
                    f"Bill ¥{b_cost/100:.2f} 偏差超阈值"
                ),
            })
        if bill.total_calls and bill.total_calls != cl["calls"]:
            gaps.append({
                "type": "calls_mismatch_vs_bill",
                "severity": "info",
                "detail": f"CallLog 调用 {cl['calls']} 笔 vs Bill {bill.total_calls} 笔",
            })

    return {
        "tenant_id": tenant_id,
        "period": period,
        "ok": True,
        "calllog": cl,
        "usage_order": (
            {
                "exists": True,
                "order_no": usage.order_no,
                "cost_cents": float(usage.amount_cents or 0),
                "calls": int((usage.extra or {}).get("total_calls", 0) or 0),
            }
            if usage is not None else None
        ),
        "bill": (
            {
                "exists": True,
                "bill_period": bill.bill_period,
                "total_cost_cents": int(bill.total_cost_cents or 0),
                "total_calls": int(bill.total_calls or 0),
                "status": bill.status,
            }
            if bill is not None else None
        ),
        "healthy": len(gaps) == 0,
        "gaps": gaps,
    }


def _is_drift(a: float, b: float) -> bool:
    """判断两金额是否偏差超阈值（绝对或相对）。"""
    a = float(a or 0.0)
    b = float(b or 0.0)
    if a == 0 and b == 0:
        return False
    abs_diff = abs(a - b)
    if abs_diff <= DRIFT_ABS_CENTS:
        return False
    rel = abs_diff / max(abs(a), abs(b))
    return rel > DRIFT_REL_RATIO


def detect_calllog_anomalies(session, tenant_id: str, period: str) -> dict:
    """检测 CallLog 异常：裸 0 + 双写嫌疑。

    裸 0：成功(200)的 agent 调用 cost_cents<=0（引擎漏回传 usage 且兜底也未生效）。
    双写嫌疑：同 trace_id 在时间窗内出现 >1 条（历史双写残留 / 重试重复）。

    返回：
      {
        tenant_id, period, ok,
        bare_zero: {count, samples:[trace_id,...]},
        double_write_suspect: {trace_ids_with_dup, count, samples:[trace_id,...]},
      }
    """
    bounds = _period_bounds_safe(period)
    if bounds is None:
        return {
            "tenant_id": tenant_id,
            "period": period,
            "ok": False,
            "bare_zero": {"count": 0, "samples": []},
            "double_write_suspect": {"trace_ids_with_dup": 0, "count": 0, "samples": []},
        }
    start, end = bounds

    # 裸 0：成功 agent 调用但费用为 0
    bare_rows = (
        session.query(CallLog.trace_id)
        .filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= start,
            CallLog.timestamp < end,
            CallLog.endpoint.startswith(_AGENT_EP_PREFIX),
            CallLog.status_code == 200,
            func.coalesce(CallLog.cost_cents, 0) <= 0,
        )
        .limit(50)
        .all()
    )
    bare_samples = [r.trace_id for r in bare_rows if r.trace_id]

    # 双写嫌疑：同 trace_id 出现 >1 条
    dup_rows = (
        session.query(CallLog.trace_id, func.count(CallLog.id).label("c"))
        .filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= start,
            CallLog.timestamp < end,
            CallLog.trace_id.isnot(None),
        )
        .group_by(CallLog.trace_id)
        .having(func.count(CallLog.id) > 1)
        .all()
    )
    dup_trace_ids = [r.trace_id for r in dup_rows]
    dup_q = (
        session.query(func.count(CallLog.id))
        .filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= start,
            CallLog.timestamp < end,
        )
    )
    if dup_trace_ids:
        dup_q = dup_q.filter(CallLog.trace_id.in_(dup_trace_ids))
    dup_total = dup_q.scalar() or 0

    return {
        "tenant_id": tenant_id,
        "period": period,
        "ok": True,
        "bare_zero": {"count": len(bare_rows), "samples": bare_samples[:10]},
        "double_write_suspect": {
            "trace_ids_with_dup": len(dup_trace_ids),
            "count": int(dup_total),
            "samples": dup_trace_ids[:10],
        },
    }


def ensure_usage_snapshot_for(session, tenant_id: str, period: str) -> dict:
    """补漏结算：把 CallLog 月聚合落成 usage 月度快照单（幂等，随调用方 session 提交）。

    仅当 CallLog 有调用时才建单；已存在则 ensure_usage_snapshot 自行返回现有不覆盖。
    返回 order.ensure_usage_snapshot 的统一响应。
    """
    cl = aggregate_calllog(session, tenant_id, period)
    if not cl["ok"]:
        return {"ok": False, "message": f"周期格式错误: {period}"}
    if cl["calls"] <= 0:
        return {"ok": True, "skipped": True, "message": "无调用，跳过建单"}
    res = ensure_usage_snapshot(
        session,
        tenant_id,
        period,
        total_calls=cl["calls"],
        total_tokens=cl["tokens"],
        cost_cents=int(round(cl["cost_cents"])),
    )
    created = res.get("code", -1) == 0
    return {
        "ok": created,
        "skipped": False,
        "message": res.get("message"),
        "order": res.get("data"),
    }


def reconcile_all(session, period: str, fix: bool = False) -> dict:
    """全租户对账（旁路）。

    fix=True 时对「漏结算」租户自动补 usage 快照单（幂等）。
    返回汇总：
      {
        period, ok,
        tenants: [ reconcile_tenant 结果 ... ],
        summary: {total, healthy, with_gaps, total_gaps, fixed},
      }
    """
    bounds = _period_bounds_safe(period)
    if bounds is None:
        return {"period": period, "ok": False, "tenants": [],
                "summary": {"error": f"周期格式错误: {period}"}}
    start, end = bounds

    # 取该周期有 CallLog 的租户集合（按真值源）
    tenant_rows = (
        session.query(CallLog.tenant_id)
        .filter(CallLog.timestamp >= start, CallLog.timestamp < end)
        .distinct()
        .all()
    )
    tenant_ids = [r.tenant_id for r in tenant_rows if r.tenant_id]

    tenants_out = []
    fixed_count = 0
    for tid in tenant_ids:
        res = reconcile_tenant(session, tid, period)
        if fix and not res["healthy"]:
            for gap in res["gaps"]:
                if gap["type"] == "missing_usage_order":
                    fix_res = ensure_usage_snapshot_for(session, tid, period)
                    if fix_res.get("ok") and not fix_res.get("skipped"):
                        fixed_count += 1
                        # 重建单租户结果（补单后已健康）
                        res = reconcile_tenant(session, tid, period)
                    break
        tenants_out.append(res)

    total = len(tenants_out)
    with_gaps = sum(1 for t in tenants_out if not t.get("healthy"))
    total_gaps = sum(len(t.get("gaps", [])) for t in tenants_out)
    return {
        "period": period,
        "ok": True,
        "tenants": tenants_out,
        "summary": {
            "total": total,
            "healthy": total - with_gaps,
            "with_gaps": with_gaps,
            "total_gaps": total_gaps,
            "fixed": fixed_count,
        },
    }


def list_reconcilable_tenants(session, period: str) -> list:
    """返回某周期有 CallLog 的租户 ID 列表（供 CLI / 前端选择器）。"""
    bounds = _period_bounds_safe(period)
    if bounds is None:
        return []
    start, end = bounds
    rows = (
        session.query(CallLog.tenant_id)
        .filter(CallLog.timestamp >= start, CallLog.timestamp < end)
        .distinct()
        .all()
    )
    return [r.tenant_id for r in rows if r.tenant_id]
