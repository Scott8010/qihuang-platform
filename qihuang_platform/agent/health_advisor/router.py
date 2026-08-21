"""
health-advisor · 路由（Agent 中台接入点）

端点：POST /api/v1/agent/health-advisor/consult
鉴权：JWT（get_current_user 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan）
响应：success(ConsultResponse) / error(code_key)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_user, get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.health_advisor.metering import check_quota
from qihuang_platform.agent.health_advisor.reports import get_report
from qihuang_platform.agent.health_advisor.schema import ConsultRequest, ConsultResponse
from qihuang_platform.agent.health_advisor.orchestrator import HealthAdvisor

router = APIRouter()
_advisor = HealthAdvisor()


@router.post(
    "/health-advisor/consult",
    summary="中医健康顾问咨询（固定专业辨证链 + partial 降级）",
)
async def consult(
    req: ConsultRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("health-advisor")),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月健康顾问调用配额已用完，请升级套餐或次月恢复。")
    try:
        resp = await _advisor.consult(req, tenant_id)
        return success(resp.model_dump())
    except Exception as e:  # noqa: BLE001
        return error("INTERNAL_ERROR", str(e))


@router.get(
    "/health-advisor/report/{report_id}",
    summary="获取健康顾问辨证报告（full 模式生成）",
)
async def get_report_endpoint(report_id: str):
    rep = get_report(report_id)
    if not rep:
        return error("NOT_FOUND", "报告不存在或已过期")
    return success(rep)


# ═══════════════════════════════════════════════════════════════
# 自由问答（2026-08-22 老黄吐槽「Open WebUI 里只会固定流程很鸡肋」）
# ═══════════════════════════════════════════════════════════════
# 定位：health-advisor 固定辨证链之外的「ChatGPT 式自由中医问答」——
# 复用 health-advisor 的套餐授权通道（免注册新能力），引擎走 refine_llm 的
# deepseek（key 留在 8602 服务器，不外泄），系统提示词约束中医角色。
# 请求：POST /api/v1/agent/health-advisor/chat  { "messages": [{"role":"user","content":"..."}], "history": [...] }
# 响应：success({ reply, model })  —— reply 即自由问答文本

class ChatRequest(BaseModel):
    """自由问答请求"""
    messages: Optional[List[Dict[str, str]]] = Field(None, description="本次消息（含 role/content）")
    question: str = Field(..., description="用户问题（messages 缺省时用此字段）")
    history: List[Dict[str, str]] = Field(default_factory=list, description="历史对话（多轮上下文）")
    max_tokens: int = Field(1200, ge=200, le=3000)


_CHAT_SYSTEM = (
    "你是「岐黄智脑·中医健康顾问」，一位专业、耐心、说话通俗的中医健康助手。"
    "回答要求：① 用大白话，避免堆砌术语；② 先说结论再展开；③ 涉及用药/诊疗一定提醒"
    "「以上为辅助参考，具体请咨询执业中医师」；④ 信息不足时明确说明缺什么（如舌象/脉象/"
    "年龄），不要硬编；⑤ 可以闲聊，但话题跑偏健康养生时温和拉回。"
)


@router.post(
    "/health-advisor/chat",
    summary="健康顾问自由问答（ChatGPT 式，非固定辨证链）",
)
async def free_chat(
    req: ChatRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("health-advisor")),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月健康顾问调用配额已用完，请升级套餐或次月恢复。")
    try:
        # 拼多轮上下文：history + 本次 question
        user_msg = (req.question or "").strip() or (
            next((m["content"] for m in (req.messages or []) if m.get("role") == "user"), "")
        )
        if not user_msg:
            return error("INVALID_PARAM", "question 不能为空")
        from qihuang_platform.agent.refine_llm import _PROVIDERS, _chat_once
        provider = next((p for p in _PROVIDERS if p["key"] == "deepseek"), _PROVIDERS[0])
        convo = list(req.history or [])
        if not any(m.get("role") == "system" for m in convo):
            convo.insert(0, {"role": "system", "content": _CHAT_SYSTEM})
        convo.append({"role": "user", "content": user_msg})
        # _chat_once 只收单段 system+user → 拼成对话体文本
        ctx = "\n".join(f"{'用户' if m.get('role')=='user' else '助手' if m.get('role')=='assistant' else '系统'}: {m.get('content','')}" for m in convo)
        raw = await _chat_once(provider, _CHAT_SYSTEM, ctx, max_tokens=req.max_tokens)
        reply = (raw or "").strip()
        if not reply:
            return error("INTERNAL_ERROR", "模型未返回内容，请稍后重试")
        return success({"reply": reply, "model": provider["key"]})
    except Exception as e:  # noqa: BLE001
        return error("INTERNAL_ERROR", str(e))
