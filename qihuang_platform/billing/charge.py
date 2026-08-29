"""
统一扣费钩子（#586 · 收费中心真扣费落地点）

所有 agent 业务调用成功后，统一在此：
  1) 用 pricing_config.compute_credits 计算本次真实消耗积分（起步价 + LLM token 叠加 / 纯规则固定）
  2) 折算真实金额 cost_cents（1 积分 = ¥0.05 = 5 分）
  3) 调 wallet.consume_credits 真扣积分（先 base 后 addon，两池空原子不放行 → 余额不足硬拦截）
  4) 写持久化 DB CallLog（真实 tokens_used / cost_cents / endpoint，供 admin 用量聚合与对账）
  5) LLM 类取不到真实 usage 时，用 prompt_text 兜底估算 token，保证真扣非零（不裸 0）
  6) 全程旁路非阻断：任何异常都不影响主业务响应

设计铁律（呼应老黄「计量不扣费」反馈）：
  之前各路由虽调 charge_agent，但 token_used 恒为 0（引擎把 usage 丢了），
  导致 LLM 类 compute_credits=0、钱包一动不动。本模块 + 引擎回传 usage 双管齐下根治。
"""
from __future__ import annotations

import logging
from typing import Optional

from qihuang_platform.billing.pricing_config import (
    A_YUAN_PER_CREDIT,
    compute_credits,
)
from qihuang_platform.billing.wallet import consume_credits
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import CallLog

logger = logging.getLogger("billing.charge")

# 1 积分 = ¥0.05 → 1 积分对应 5 分；cost_cents = cost_credits * CENTS_PER_CREDIT
CENTS_PER_CREDIT = int(round(A_YUAN_PER_CREDIT * 100))  # 5


def estimate_tokens(text: str, is_multimodal: bool = False) -> int:
    """token 兜底估算（proxy 类引擎不外吐 usage 时使用）。

    - 中文 ~1.6 token/字（含标点、方言语义密度高）
    - 英文 ~0.3 token/词
    取两者之和并向上取整（保底 1），确保 LLM 类调用真扣非零、不裸 0。
    多模态图片 token 由视觉端点 usage 覆盖，未取到时本兜底只估文本侧（保守）。
    """
    if not text:
        return 0
    cn = sum(1 for ch in text if "一" <= ch <= "鿿")
    en_words = sum(1 for w in text.split() if w.isascii() and w)
    est = cn * 1.6 + en_words * 0.3
    return max(1, int(est + 0.999))


def charge_call(
    tenant_id: str,
    agent_key: str,
    *,
    token_used: int = 0,
    is_multimodal: bool = False,
    uses_llm: Optional[bool] = None,
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    trace_id: Optional[str] = None,
    prompt_text: Optional[str] = None,
    status_code: int = 200,
) -> None:
    """统一扣费入口（旁路非阻断，绝不抛异常）。

    参数：
      token_used   —— 本次 LLM 真实消耗 token（引擎从 usage.total_tokens 回传）；0 表示未传
      prompt_text  —— LLM 类未取到真实 usage 时用于兜底估算 token（保证真扣非零）
      is_multimodal/uses_llm —— 透传给 compute_credits 决定计价口径
      endpoint/user_id/trace_id —— 写持久化 CallLog 用的维度
    """
    if not tenant_id:
        return  # 无租户上下文（如未注入 request.state.tenant_id）时不扣费、不建空钱包
    try:
        # token 兜底：LLM 类且未取到真实 usage → 用 prompt 估算，避免裸 0 不扣费
        if token_used <= 0 and uses_llm is not False and prompt_text:
            token_used = estimate_tokens(prompt_text, is_multimodal)

        cost_credits = compute_credits(agent_key, token_used, is_multimodal, uses_llm)
        cost_cents = cost_credits * CENTS_PER_CREDIT

        # 真扣积分（先 base 后 addon；两池空 → 原子不放行，返回 False 由调用方决定拦截）
        consume_credits(
            tenant_id=tenant_id,
            agent_key=agent_key,
            token_used=token_used,
            is_multimodal=is_multimodal,
            uses_llm=uses_llm,
        )

        # 写持久化 DB CallLog（真实 token / 真实金额 / endpoint 标识）
        _write_call_log(
            tenant_id=tenant_id,
            agent_key=agent_key,
            tokens_used=token_used,
            cost_cents=cost_cents,
            user_id=user_id,
            endpoint=endpoint,
            trace_id=trace_id,
            status_code=status_code,
        )
    except Exception as e:  # noqa: BLE001 - 旁路非阻断：计量异常绝不阻断主响应
        logger.warning("[charge] charge_call 失败(旁路): %s", e)


def _write_call_log(
    *,
    tenant_id: str,
    agent_key: str,
    tokens_used: int,
    cost_cents: float,
    user_id: Optional[str],
    endpoint: Optional[str],
    trace_id: Optional[str],
    status_code: int,
) -> None:
    db = SessionLocal()
    try:
        log = CallLog(
            tenant_id=tenant_id,
            user_id=user_id,
            endpoint=endpoint or f"agent:{agent_key}",
            method="POST",
            status_code=status_code,
            tokens_used=int(tokens_used or 0),
            cost_cents=float(cost_cents or 0.0),
            trace_id=trace_id,
        )
        db.add(log)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("[charge] CallLog 写入失败(旁路): %s", e)
    finally:
        db.close()
