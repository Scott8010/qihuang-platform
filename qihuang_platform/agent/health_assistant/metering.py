"""
health-assistant · 计量埋点 + 双层配额（T6 对齐）

双层配额（2026-08-22 老黄点破「不是BUG的bug」后定稿）：
  1. 机构级：复用 qihuang_platform.billing.quota.check_quota(tenant_id)
     （与 health-advisor 同款，plan/usage 表维度，机构总量上限）
  2. 终端 C 端用户级：每 (tenant_id, end_user_id, 年-月) 独立计数，
     上限由套餐 features.health_assistant_per_user_monthly 决定
     （体验版默认 10 次/月/用户，见 billing/plans.py）。
     ⚠️ 当前为进程内内存计数（重启清零），真计数中台（Redis/DB 按月清零、
     与 #474 加购计费打通）由 #474 计费中台接管，本模块只留钩子。

埋点：计量成功才计——仅业务成功执行后 record_call（与 health-advisor 同范式）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from qihuang_platform.gateway.metering import CallLog, metering_store
from qihuang_platform.billing.pricing_config import compute_credits

AGENT_KEY = "health-assistant"
MODULE = "agent"
# 1 积分 = ¥0.05 = 5 分
_CENTS_PER_CREDIT = 5

logger = logging.getLogger("health_assistant.metering")

# 终端用户级内存计数： (tenant_id, end_user_id, "YYYY-MM") -> count
# 注：进程内缓存，重启即失；#474 落地后替换为 Redis/DB 持久计数。
_USER_COUNTER: dict = {}


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ───────────────── 机构级配额（与 health-advisor 同款）─────────────────
def check_quota(tenant_id: Optional[str]) -> bool:
    """机构级配额是否可用。True=可用；False=超额应拦截。

    DB 未就绪/异常时降级放行（交由上游 require_agent_in_plan 套餐校验兜底）。
    """
    if not tenant_id:
        return True
    try:
        from qihuang_platform.billing.quota import check_quota as _check
        res = _check(tenant_id)
        if not isinstance(res, dict) or res.get("success") is False:
            logger.warning("[ha-metering] 机构配额返回异常态，放行: %s", res)
            return True
        data = res.get("data") or {}
        if data.get("is_exceeded"):
            logger.info("[ha-metering] 租户 %s 机构配额超额(%.1f%%)，应拦截",
                        tenant_id, data.get("quota_percentage", 0))
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha-metering] 机构配额执行失败(DB未就绪?)，降级放行: %s", e)
        return True


# ───────────────── 终端 C 端用户级配额（双层第二层）─────────────────
def check_user_quota(
    tenant_id: Optional[str],
    end_user_id: Optional[str],
    per_user_limit: Optional[int],
) -> Tuple[bool, int]:
    """终端用户级配额检查。返回 (是否通过, 剩余次数；-1 表示不限/未识别用户)。

    - end_user_id 为空 → 不按用户限（退化为仅机构级兜底，调用方应保证传端用户 ID）
    - per_user_limit 为空/0 → 不按用户限（付费档放开）
    """
    if not end_user_id or not per_user_limit:
        return True, -1
    key = (tenant_id, end_user_id, _month_key())
    used = _USER_COUNTER.get(key, 0)
    remain = per_user_limit - used
    return remain > 0, remain


def record_user_call(tenant_id: Optional[str], end_user_id: Optional[str]) -> None:
    """终端用户级计数 +1（成功应答后调用）。"""
    if not end_user_id:
        return
    key = (tenant_id, end_user_id, _month_key())
    _USER_COUNTER[key] = _USER_COUNTER.get(key, 0) + 1


def reset_user_counters() -> None:
    """测试/运维辅助：清空内存计数。"""
    _USER_COUNTER.clear()


# ───────────────── 业务埋点 ─────────────────
async def record_call(
    *,
    tenant_id: Optional[str],
    end_user_id: Optional[str] = None,
    code: int,
    partial: bool,
    latency_ms: float,
    trace_id: str,
    endpoint: str = "/api/v1/agent/health-assistant/chat",
    status_code: int = 200,
    token_used: int = 0,
    is_multimodal: bool = False,
) -> None:
    """记录一次健康助手调用（业务级计量埋点）。

    CallLog.user_id 对齐 C 端终端用户 ID（end_user_id），便于 #474 按用户维度
    聚合计费；extra.agent_key 标记增值 Agent 模块。
    """
    try:
        # 真实金额：起步价 + LLM token 叠加（1 积分 = 5 分），供看板展示
        cost_credits = compute_credits(AGENT_KEY, token_used, is_multimodal, True)
        cost_cents = cost_credits * _CENTS_PER_CREDIT
        await metering_store.log(CallLog(
            id=uuid.uuid4().hex,
            trace_id=trace_id,
            endpoint=endpoint,
            method="POST",
            tenant_id=tenant_id,
            user_id=end_user_id,
            status_code=status_code,
            latency_ms=round(latency_ms, 1),
            tokens_used=token_used,    # 上游 LLM 链路回传真实 token（#586）
            cost_cents=cost_cents,     # 真实金额（#586 计费成功才计）
            module=MODULE,
            extra={
                "agent_key": AGENT_KEY,
                "code": code,
                "partial": partial,
            },
        ), persist=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha-metering] record_call 失败: %s", e)

    # ── #586 计费中台：成功调用后真扣积分 + 写持久化 CallLog（旁路非阻断）──
    try:
        from qihuang_platform.billing.charge import charge_call
        charge_call(
            tenant_id=tenant_id,
            agent_key=AGENT_KEY,
            token_used=token_used,
            is_multimodal=is_multimodal,
            uses_llm=True,
            user_id=end_user_id,
            endpoint=endpoint,
            trace_id=trace_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha-metering] 积分扣减失败(旁路): %s", e)
