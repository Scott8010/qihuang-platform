"""
health-advisor · 计量埋点（T6）

复用平台两套现成能力（零新依赖、贴合既有范式）：
  1. 配额校验：qihuang_platform.billing.quota.check_quota(tenant_id)
       - 返回 success(data={is_exceeded, quota_percentage, remaining_calls, ...})
         或 error(...)（如租户无订阅）
       - 骨架阶段该路径依赖 DB SessionLocal（plan/usage 表）；若运行环境未就绪，
         降级为放行（True）并记录 warning，不阻断主流程，交由上游套餐校验兜底。
  2. 调用记录：qihuang_platform.gateway.metering.metering_store.log(CallLog(...))
       - CallLog 支持 module="agent" + extra 任意 JSON（增值模块独立计量维度）
       - 字段对齐《开工文档》T6：tenant_id / store_id / agent_key / code / partial / 耗时 / trace_id

设计原则：计费成功才计——仅在业务成功执行后 record_call（partial 仍计 1 次有效调用）。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from qihuang_platform.gateway.metering import CallLog, metering_store

AGENT_KEY = "health-advisor"
MODULE = "agent"

logger = logging.getLogger("health_advisor.metering")


def check_quota(tenant_id: Optional[str]) -> bool:
    """配额是否可用。True=可用（未超额）；False=超额应拦截。

    骨架阶段：billing.quota.check_quota 依赖 DB（plan/usage 表）。DB 未就绪时
    降级放行并记录 warning，交由上游套餐校验（require_agent_in_plan）兜底。
    """
    if not tenant_id:
        return True
    try:
        from qihuang_platform.billing.quota import check_quota as _check
        res = _check(tenant_id)
        if not isinstance(res, dict) or res.get("success") is False:
            # 错误返回（如租户无订阅）→ 不拦截，交给上游套餐校验
            logger.warning("[metering] check_quota 返回异常态，放行: %s", res)
            return True
        data = res.get("data") or {}
        if data.get("is_exceeded"):
            logger.info(
                "[metering] 租户 %s 配额超额(%.1f%%)，应拦截",
                tenant_id, data.get("quota_percentage", 0),
            )
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[metering] check_quota 执行失败(DB未就绪?)，降级放行: %s", e)
        return True


async def record_call(
    *,
    tenant_id: Optional[str],
    store_id: Optional[str],
    code: int,
    partial: bool,
    latency_ms: float,
    trace_id: str,
    endpoint: str = "/api/v1/agent/health-advisor/consult",
    status_code: int = 200,
) -> None:
    """记录一次 health-advisor 咨询调用（业务级计费埋点）。

    对齐 T6 字段：tenant_id / store_id / agent_key / code / partial / 耗时 / trace_id。
    仅业务成功执行后调用；partial 仍计 1 次有效调用。

    注意：metering_store.log 是 async 协程，必须在事件循环内 await。
    """
    try:
        await metering_store.log(CallLog(
            id=uuid.uuid4().hex,
            trace_id=trace_id,
            endpoint=endpoint,
            method="POST",
            tenant_id=tenant_id,
            status_code=status_code,
            latency_ms=round(latency_ms, 1),
            tokens_used=0,   # 真实 token 由 8601 链路产生，联调阶段接入
            cost_cents=0,    # 单价待定，计费成功才计
            module=MODULE,
            extra={
                "agent_key": AGENT_KEY,
                "store_id": store_id,
                "code": code,
                "partial": partial,
            },
        ), persist=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[metering] record_call 失败: %s", e)
