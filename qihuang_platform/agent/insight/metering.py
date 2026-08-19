"""
insight · 计量埋点（对齐 coach/content-writer metering 范式）

复用平台两套现成能力（零新依赖、贴合既有范式）：
  1. 配额校验：qihuang_platform.billing.quota.check_quota(tenant_id)
       - 骨架阶段依赖 DB（plan/usage 表）；未就绪时降级放行，交上游套餐校验兜底。
  2. 调用记录：qihuang_platform.gateway.metering.metering_store.log(CallLog(...))
       - module="agent" + extra 任意 JSON（增值模块独立计量维度）
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from qihuang_platform.gateway.metering import CallLog, metering_store

AGENT_KEY = "insight"
MODULE = "agent"

logger = logging.getLogger("insight.metering")


def check_quota(tenant_id: Optional[str]) -> bool:
    """配额是否可用。True=可用（未超额）；False=超额应拦截。"""
    if not tenant_id:
        return True
    try:
        from qihuang_platform.billing.quota import check_quota as _check
        res = _check(tenant_id)
        if not isinstance(res, dict) or res.get("success") is False:
            logger.warning("[insight.metering] check_quota 返回异常态，放行: %s", res)
            return True
        data = res.get("data") or {}
        if data.get("is_exceeded"):
            logger.info(
                "[insight.metering] 租户 %s 配额超额(%.1f%%)，应拦截",
                tenant_id, data.get("quota_percentage", 0),
            )
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[insight.metering] check_quota 执行失败(DB未就绪?)，降级放行: %s", e)
        return True


async def record_call(
    *,
    tenant_id: Optional[str],
    user_id: Optional[str] = None,
    store_id: Optional[str] = None,
    code: int,
    latency_ms: float,
    trace_id: str,
    endpoint: str = "/api/v1/agent/insight/diagnose",
    status_code: int = 200,
    action: str = "diagnose",
    metric_count: int = 0,
) -> None:
    """记录一次 insight 调用（业务级计费埋点）。仅业务成功执行后调用。"""
    try:
        await metering_store.log(CallLog(
            id=uuid.uuid4().hex,
            trace_id=trace_id,
            endpoint=endpoint,
            method="POST",
            tenant_id=tenant_id,
            user_id=user_id,
            status_code=status_code,
            latency_ms=round(latency_ms, 1),
            tokens_used=0,
            cost_cents=0,
            module=MODULE,
            extra={
                "agent_key": AGENT_KEY,
                "store_id": store_id,
                "code": code,
                "action": action,
                "metric_count": metric_count,
            },
        ))
    except Exception as e:  # noqa: BLE001
        logger.warning("[insight.metering] record_call 失败: %s", e)
