"""
content_writer · 路由（Agent 中台接入点）— 8602 自建文案生成能力

端点：
  POST /api/v1/agent/content-writer/generate  生成文案（支持多版本 variants）
  GET  /api/v1/agent/content-writer/dashboard 本租户文案生成用量看板
鉴权：JWT（get_current_principal 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan("content-writer")）
能力引擎：8602 自有 4 引擎 LLM 客户端（engine.generate，DeepSeek→Qwen→GLM→Kimi fallback）
        默认注入「合规约束」system prompt（不夸大疗效/不承诺治愈/符合广告法），
        与 compliance-guard 审核链路咬合（B2 营销智能 = content-writer + compliance）。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("content_writer.router")

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.gateway.metering import metering_store
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.content_writer.engine import generate
from qihuang_platform.agent.content_writer.metering import check_quota, record_call

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

_CONTENT_TYPES = {
    "product": "产品种草/卖点文案（药食同源/养生品）",
    "health_article": "中医科普文章/养生干货",
    "social_post": "朋友圈/社群短文案",
    "wechat": "公众号推文片段",
    "flyer": "门店活动/海报文案",
    "ad_copy": "广告投放文案",
    "consult_reply": "客服/健康顾问话术回复",
    "general": "通用文案",
}

_TONES = {
    "professional": "专业权威、可信赖",
    "warm": "亲切温暖、有温度",
    "fun": "活泼有趣、年轻化",
    "authoritative": "科普严谨、条理清晰",
}

_LENGTH_DESC = {
    "short": "简短精炼，不超过 100 字",
    "medium": "中等篇幅，约 100-300 字",
    "long": "完整篇幅，约 300-800 字",
}


class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., description="文案主题，如 '夏季养心茶饮推荐'")
    content_type: str = Field("general", description="类型: " + "/".join(_CONTENT_TYPES.keys()))
    tone: str = Field("warm", description="语气: " + "/".join(_TONES.keys()))
    audience: Optional[str] = Field(None, description="目标受众，如 '门店周边中老年顾客'")
    length: str = Field("medium", description="篇幅: short/medium/long")
    variants: int = Field(1, ge=1, le=4, description="生成版本数（1-4）")
    extra: Optional[str] = Field(None, description="补充信息（卖点/禁忌/活动规则等）")


# ═══════════════════════════════════════════════════════════════
# 提示词构建（引擎只管生成，业务规则在此）
# ═══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "你是一位资深中医健康内容文案专家，服务于「岐黄智脑」赋能的连锁健康门店。"
    "你的文案必须遵循以下铁律：\n"
    "1) 专业可信，融入中医养生理念（阴阳、气血、脏腑、经络、节气等），不杜撰；\n"
    "2) 严格合规：不夸大疗效、不承诺治愈、不使用绝对化/保证性用语"
    "（如'根治''包好''100%有效'' guaranteed'），符合《广告法》与医疗健康内容规范；\n"
    "3) 口语化、有温度、引发共鸣，避免生硬说教；\n"
    "4) 自然带出品牌/门店的专业可信赖感，但不硬广、不堆砌口号。\n"
    "直接输出文案正文，不要解释、不要 markdown 标题、不要'以下是文案'之类的引导语。"
)


def _build_user_prompt(req: ContentGenerateRequest, variant_index: int) -> str:
    type_desc = _CONTENT_TYPES.get(req.content_type, _CONTENT_TYPES["general"])
    tone_desc = _TONES.get(req.tone, _TONES["warm"])
    length_desc = _LENGTH_DESC.get(req.length, _LENGTH_DESC["medium"])

    variant_hint = ""
    if req.variants > 1:
        variant_hint = f"\n这是第 {variant_index} 个版本，请换一个切入角度或表达风格，保持核心信息一致但呈现不同。"

    audience_line = f"目标受众：{req.audience}\n" if req.audience else "目标受众：未指定（面向大众健康消费者）\n"
    extra_line = f"【补充信息】{req.extra}\n" if req.extra else ""

    return (
        f"请为以下需求撰写【{tone_desc}】风格的【{type_desc}】：\n"
        f"主题：{req.topic}\n"
        f"{audience_line}"
        f"篇幅要求：{length_desc}\n"
        f"{extra_line}"
        f"{variant_hint}"
        f"请直接给出文案。"
    )


# ═══════════════════════════════════════════════════════════════
# 1. 生成文案
# ════════════════════════════════════ 上收入口 ═════════════════════
@router.post(
    "/content-writer/generate",
    summary="生成中医健康营销文案（content-writer 引擎）",
)
async def generate_content(
    req: ContentGenerateRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("content-writer")),
):
    if req.content_type not in _CONTENT_TYPES:
        return error("INVALID_PARAM", f"不支持的 content_type: {req.content_type}，有效值: {list(_CONTENT_TYPES.keys())}")
    if req.tone not in _TONES:
        return error("INVALID_PARAM", f"不支持的 tone: {req.tone}，有效值: {list(_TONES.keys())}")
    if req.length not in _LENGTH_DESC:
        return error("INVALID_PARAM", f"不支持的 length: {req.length}，有效值: {list(_LENGTH_DESC.keys())}")

    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月文案生成调用配额已用完，请升级套餐或次月恢复。")

    trace_id = uuid.uuid4().hex
    start = time.monotonic()
    try:
        variants: List[Dict[str, str]] = []
        used_model: Optional[str] = None
        for i in range(1, req.variants + 1):
            text, model = await generate(
                _SYSTEM_PROMPT,
                _build_user_prompt(req, i),
                temperature=0.8,
                max_tokens=1200,
            )
            if text:
                variants.append({"index": i, "text": text, "model": model})
                used_model = used_model or model
            else:
                variants.append({"index": i, "text": "（AI 文案生成服务暂不可用，请稍后重试）", "model": None})

        latency_ms = (time.monotonic() - start) * 1000
        code = 0 if any(v["text"] and "暂不可用" not in v["text"] for v in variants) else -1
        await record_call(
            tenant_id=tenant_id,
            user_id=user_id,
            code=code,
            latency_ms=latency_ms,
            trace_id=trace_id,
            action="generate",
            variants=req.variants,
        )

        return success(data={
            "topic": req.topic,
            "content_type": req.content_type,
            "tone": req.tone,
            "variants": variants,
            "used_model": used_model,
            "generated_count": len([v for v in variants if v["model"]]),
        })
    except Exception as e:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        await record_call(
            tenant_id=tenant_id,
            user_id=user_id,
            code=-1,
            latency_ms=latency_ms,
            trace_id=trace_id,
            action="generate",
            variants=req.variants,
        )
        logger.exception("[content_writer] generate 异常: %s", e)
        return error("INTERNAL_ERROR", "文案生成失败，请稍后重试。")


# ═══════════════════════════════════════════════════════════════
# 2. 本租户文案生成用量看板
# ═══════════════════════════════════════════════════════════════
@router.get(
    "/content-writer/dashboard",
    summary="本租户文案生成用量看板（content-writer）",
)
async def content_writer_dashboard(
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("content-writer")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    logs = metering_store.query(tenant_id=tenant_id, module="agent", limit=200)
    cw_logs = [l for l in logs if (l.extra or {}).get("agent_key") == "content-writer"]

    total_calls = len(cw_logs)
    total_variants = sum((l.extra or {}).get("variants", 1) for l in cw_logs)
    recent = [{
        "timestamp": l.timestamp,
        "endpoint": l.endpoint,
        "variants": (l.extra or {}).get("variants", 1),
        "latency_ms": l.latency_ms,
    } for l in cw_logs[:20]]

    return success(data={
        "total_generations": total_calls,
        "total_variants": total_variants,
        "recent": recent,
    })
