"""
insight · 路由（Agent 中台接入点）— 8602 自建数据诊断能力

端点：
  POST /api/v1/agent/insight/diagnose  经营数据诊断（哪有问题+为什么+怎么救）
  GET  /api/v1/agent/insight/dashboard 本租户诊断用量看板
鉴权：JWT（get_current_principal 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan("insight")）
能力引擎：8602 自有 4 引擎 LLM 客户端（engine.diagnose，DeepSeek→Qwen→GLM→Kimi fallback）
护栏（对齐方案七风险表）：insight 只给「数据诊断 + 建议」，决策权在人，每条结论附数据依据；
        不夸大、不承诺经营效果、不做医疗/辨证（B1 经营风控 / 经营管理 = insight + compliance）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("insight.router")

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.gateway.metering import metering_store
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.insight.engine import diagnose
from qihuang_platform.agent.insight.metering import check_quota, record_call
from qihuang_platform.billing.wallet import charge_agent

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class InsightMetric(BaseModel):
    """单个经营指标。key 如 revenue/orders/members/conversion 等，value 为数值，unit 可选。"""
    key: str = Field(..., description="指标键，如 revenue/orders/members/conversion")
    label: str = Field(..., description="指标名称，如 '本月营业额'")
    value: float = Field(..., description="指标数值")
    unit: Optional[str] = Field(None, description="单位，如 元/单/人/%")
    prev_value: Optional[float] = Field(None, description="对比期数值（如上月/上周），用于环比")
    prev_label: Optional[str] = Field(None, description="对比期名称，如 '上月'")
    note: Optional[str] = Field(None, description="补充说明（如 门店反馈：客流下降）")


class InsightDiagnoseRequest(BaseModel):
    """经营数据诊断请求。传入本店/本租户的经营指标快照，AI 给出诊断与建议。"""
    store_id: Optional[str] = Field(None, description="门店ID（行级隔离）")
    title: Optional[str] = Field(None, description="诊断主题，如 '7月门店经营诊断'")
    metrics: List[InsightMetric] = Field(..., description="经营指标列表（至少 1 项）")
    context: Optional[str] = Field(None, description="补充背景（门店状态/活动/异常事件等）")


# ═══════════════════════════════════════════════════════════════
# 提示词构建（引擎只管诊断，业务规则与护栏在此）
# ═══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "你是一位资深连锁健康门店经营数据分析顾问，服务于「岐黄智脑」赋能的连锁健康门店。"
    "你的诊断必须遵循以下铁律：\n"
    "1) 只做数据诊断与经营建议（客流/流水/会员/转化/复购等），不做医疗诊断、不辨证、不开方；\n"
    "2) 每条结论必须附数据依据（点名指标 key 与数值），不得无数据空谈；\n"
    "3) 结构清晰：先总判断，再逐条列问题（严重度 高/中/低 + 为什么），最后给可执行建议（怎么救）；\n"
    "4) 语气务实、不夸大、不承诺经营效果（如'保证翻倍''必定扭亏'禁用），决策权在老板；\n"
    "5) 若数据不足，明确指出缺哪些指标，不强行下结论。\n"
    "以 JSON 输出，格式：\n"
    "{\"summary\":\"一句话总判断\",\"issues\":[{\"severity\":\"高|中|低\",\"title\":\"问题标题\","
    "\"reason\":\"为什么（附数据依据）\",\"evidence\":[\"依据1\",\"依据2\"]}],"
    "\"suggestions\":[{\"action\":\"建议动作\",\"reason\":\"理由\",\"priority\":\"高|中|低\"}],"
    "\"missing_data\":[\"缺失的关键指标\"]}\n"
    "只输出 JSON，不要 markdown 代码块包裹，不要额外解释。"
)


def _build_user_prompt(req: InsightDiagnoseRequest) -> str:
    lines: List[str] = []
    if req.title:
        lines.append(f"诊断主题：{req.title}")
    if req.store_id:
        lines.append(f"门店：{req.store_id}")
    lines.append("【经营指标】")
    for m in req.metrics:
        unit = m.unit or ""
        prev = ""
        if m.prev_value is not None:
            p_label = m.prev_label or "上期"
            delta = (m.value - m.prev_value) / m.prev_value * 100 if m.prev_value else 0
            prev = f"（{p_label}: {m.prev_value}{unit}，环比 {delta:+.1f}%）"
        note = f"；备注: {m.note}" if m.note else ""
        lines.append(f"- {m.label}({m.key}): {m.value}{unit}{prev}{note}")
    if req.context:
        lines.append(f"【补充背景】{req.context}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 1. 经营数据诊断
# ════════════════════════════════════ 上收入口 ═════════════════════
@router.post(
    "/insight/diagnose",
    summary="经营数据诊断（哪有问题+为什么+怎么救）",
)
async def insight_diagnose(
    req: InsightDiagnoseRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("insight")),
):
    if not req.metrics:
        return error("INVALID_PARAM", "至少需要 1 项经营指标。")

    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月数据诊断调用配额已用完，请升级套餐或次月恢复。")

    trace_id = uuid.uuid4().hex
    start = time.monotonic()
    try:
        raw, model, tokens = await diagnose(
            _SYSTEM_PROMPT,
            _build_user_prompt(req),
            temperature=0.4,
            max_tokens=2000,
        )
        latency_ms = (time.monotonic() - start) * 1000

        if not raw:
            await record_call(
                tenant_id=tenant_id, user_id=user_id, store_id=req.store_id,
                code=-1, latency_ms=latency_ms, trace_id=trace_id,
                action="diagnose", metric_count=len(req.metrics),
            )
            return error("LLM_UNAVAILABLE", "AI 诊断服务暂不可用，请稍后重试。")

        # 兼容 LLM 偶发用 ```json 包裹
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # 解析失败仍返回原文，不丢弃诊断
            parsed = {"summary": text, "issues": [], "suggestions": [], "missing_data": []}

        await record_call(
            tenant_id=tenant_id, user_id=user_id, store_id=req.store_id,
            code=0, latency_ms=latency_ms, trace_id=trace_id,
            action="diagnose", metric_count=len(req.metrics),
            token_used=tokens,
        )

        charge_agent(tenant_id, "insight", uses_llm=True, token_used=tokens, endpoint="/api/v1/agent/insight/diagnose")
        return success(data={
            "diagnosis": parsed,
            "model": model,
            "metric_count": len(req.metrics),
        })
    except Exception as e:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        await record_call(
            tenant_id=tenant_id, user_id=user_id, store_id=req.store_id,
            code=-1, latency_ms=latency_ms, trace_id=trace_id,
            action="diagnose", metric_count=len(req.metrics),
        )
        logger.exception("[insight] diagnose 异常: %s", e)
        return error("INTERNAL_ERROR", "数据诊断失败，请稍后重试。")


# ═══════════════════════════════════════════════════════════════
# 2. 本租户诊断用量看板
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/insight/dashboard",
    summary="本租户数据诊断用量看板（insight）",
)
async def insight_dashboard(
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("insight")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    logs = metering_store.query(tenant_id=tenant_id, module="agent", limit=200)
    ins_logs = [l for l in logs if (l.extra or {}).get("agent_key") == "insight"]

    total_calls = len(ins_logs)
    total_metrics = sum((l.extra or {}).get("metric_count", 0) for l in ins_logs)
    recent = [{
        "timestamp": l.timestamp,
        "endpoint": l.endpoint,
        "metric_count": (l.extra or {}).get("metric_count", 0),
        "latency_ms": l.latency_ms,
    } for l in ins_logs[:20]]

    return success(data={
        "total_diagnoses": total_calls,
        "total_metrics": total_metrics,
        "recent": recent,
    })
