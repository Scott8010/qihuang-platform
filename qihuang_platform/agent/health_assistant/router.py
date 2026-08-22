"""
health-assistant · 路由（C 端健康服务钩子，2026-08-22 从 health-advisor 拆出独立）

端点：POST /api/v1/agent/health-assistant/chat
鉴权：JWT（get_current_principal）+ 套餐校验（require_agent_in_plan("health-assistant")）

能力（#478 定稿）：
  1. 自由问答（ChatGPT 式，deepseek 文本链路，承接原 health-advisor/chat）
  2. 多模态自动切换：请求带 image → 走共享视觉网关（GEO_VISION_*，qwen-vl-plus）；
     未配置视觉模型或失败 → 安全降级文本并如实标注（fail-open 注明，不造假）
  3. 会话内记忆：session_id 维度服务端保留最近 N 轮（内存，离开页面/重启即失）
  4. 喂料口子：租户级可配置营销引导语料 Tenant.extra["health_assistant_prompt"]，
     每次对话动态读取拼进 system prompt（本机构专属引导，不硬广、不编造）
  5. 双层配额：机构级（billing.quota）+ 终端 C 端用户级（health_assistant_per_user_monthly）
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.health_assistant.metering import (
    check_quota,
    check_user_quota,
    record_call,
    record_user_call,
)
from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import error, success

logger = logging.getLogger("health_assistant.router")

router = APIRouter()

# ── 全局基线提示词（角色边界 + 免责 + 引导基调）──
_CHAT_SYSTEM = (
    "你是「岐黄智脑·健康助手」，一位专业、耐心、说话通俗的中医健康服务助手，"
    "主要服务 C 端用户（普通消费者）。"
    "回答要求：① 用大白话，避免堆砌术语；② 先说结论再展开；③ 涉及用药/诊疗一定提醒"
    "「以上为辅助参考，具体请咨询执业中医师」；④ 信息不足时明确说明缺什么（如舌象/脉象/"
    "年龄），不要硬编；⑤ 可以闲聊，但话题跑偏健康养生时温和拉回；"
    "⑥ 你是健康服务钩子：在合适时机自然引导用户了解平台的理疗项目与健康产品，"
    "但不硬广、不编造优惠，不承诺疗效。"
)

# 会话内记忆上限（服务端保留最近 N 轮，每轮 = user + assistant 两条）
_MAX_SESSION_TURNS = 12
_SESSIONS: Dict[str, List[Dict[str, str]]] = {}


class ChatRequest(BaseModel):
    """健康助手自由问答请求"""
    question: str = Field(..., description="用户问题（messages 缺省时用此字段）")
    messages: Optional[List[Dict[str, str]]] = Field(
        None, description="原始消息（含 role/content），与 question 二选一")
    history: List[Dict[str, str]] = Field(
        default_factory=list, description="客户端自带历史（多轮上下文，无 session_id 时生效）")
    session_id: Optional[str] = Field(
        None, description="会话 ID；传入则服务端保留会话内记忆（上限 N 轮，重启即失）")
    end_user_id: Optional[str] = Field(
        None, description="C 端终端用户 ID；双层配额按用户限次，建议必传")
    store_id: Optional[str] = Field(
        None, description="门店 ID（8602 = Org.id）；传入则拼该门店专属营销语料，"
                          "未传或门店无专属语料时回落平台默认语料")
    image: Optional[str] = Field(
        None, description="图片引用（data URI / http(s) URL / 本地路径）；传入则自动切换视觉模型")
    max_tokens: int = Field(1200, ge=200, le=3000)


def _resolve_session_messages(req: ChatRequest) -> List[Dict[str, str]]:
    """合并会话上下文：优先 session_id 服务端记忆；无则退回客户端 history。"""
    if req.session_id:
        return list(_SESSIONS.get(req.session_id, []))
    return list(req.history or [])


def _persist_session(session_id: Optional[str], convo: List[Dict[str, str]]) -> None:
    if not session_id:
        return
    _SESSIONS[session_id] = convo[-(_MAX_SESSION_TURNS * 2):]


# ── 喂料口子：门店级（Org）营销引导语料，平台默认兜底 ──
def _load_marketing_prompt(tenant_id: Optional[str], store_id: Optional[str] = None) -> str:
    """读取营销引导语料（#482 门店级语料槽）：

    解析优先级：① 门店专属（Org.extra.health_assistant_prompt）
                → ② 平台默认（Tenant.extra.health_assistant_prompt）
                → ③ 空串。
    老黄 2026-08-22 定：「有口子给它灌语料」——运营把理疗项目/产品/卖点写成
    一段话存进配置，每次对话动态拼入 system prompt，改完即生效、无需发版。
    """
    if not tenant_id:
        return ""

    # ① 门店专属语料（store_id 维度，挂在 Org.extra，零迁移）
    if store_id:
        try:
            from qihuang_platform.db.config import SessionLocal
            from qihuang_platform.db.models import Org
            db = SessionLocal()
            try:
                org = db.query(Org).filter_by(id=store_id).first()
                if org:
                    store_prompt = (org.extra or {}).get("health_assistant_prompt") or ""
                    if store_prompt.strip():
                        return store_prompt.strip()
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("[ha] 读取门店营销语料失败，回落平台默认: %s", e)

    # ② 平台默认语料（tenant 级）
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import Tenant
        db = SessionLocal()
        try:
            tenant = db.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return ""
            extra = tenant.extra or {}
            return (extra.get("health_assistant_prompt") or "").strip()
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha] 读取平台默认营销语料失败，跳过: %s", e)
        return ""


def _build_system(marketing: str) -> str:
    if not marketing:
        return _CHAT_SYSTEM
    return (
        _CHAT_SYSTEM
        + "\n\n【本机构专属引导语料（自然融入回答，不硬广、不编造、不承诺疗效）】\n"
        + marketing
    )


# ── 双层配额：终端用户级上限来源（套餐 features） ──
def _plan_per_user_limit(tenant_id: Optional[str]) -> Optional[int]:
    """从当前生效套餐 features.health_assistant_per_user_monthly 取每用户月限次。
    无订阅/未配置/为 0 → None（不按用户限）。"""
    if not tenant_id:
        return None
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import Plan, Subscription
        db = SessionLocal()
        try:
            sub = db.query(Subscription).filter_by(
                tenant_id=tenant_id, status="active").first()
            if not sub:
                return None
            plan = db.query(Plan).filter_by(id=sub.plan_id).first()
            if not plan:
                return None
            val = (plan.features_json or {}).get("health_assistant_per_user_monthly")
            if val in (None, 0, ""):
                return None
            return int(val)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha] 读取套餐每用户限次失败: %s", e)
        return None


# ── 应答链路 ──
async def _text_reply(
    user_msg: str,
    history: List[Dict[str, str]],
    system: str,
    max_tokens: int,
) -> tuple[str, str]:
    """纯文本链路：deepseek 自由问答（承接原 health-advisor/chat 逻辑）。"""
    from qihuang_platform.agent.refine_llm import _PROVIDERS, _chat_once
    provider = next((p for p in _PROVIDERS if p["key"] == "deepseek"), _PROVIDERS[0])
    convo = list(history or [])
    if not any(m.get("role") == "system" for m in convo):
        convo.insert(0, {"role": "system", "content": system})
    convo.append({"role": "user", "content": user_msg})
    ctx = "\n".join(
        f"{'用户' if m.get('role') == 'user' else '助手' if m.get('role') == 'assistant' else '系统'}: {m.get('content', '')}"
        for m in convo
    )
    raw = await _chat_once(provider, system, ctx, max_tokens=max_tokens)
    reply = (raw or "").strip()
    if not reply:
        raise RuntimeError("模型未返回内容")
    return reply, provider["key"]


async def _vision_reply(
    image_ref: str,
    user_msg: str,
    system: str,
) -> tuple[str, str]:
    """多模态链路：共享视觉网关（GEO_VISION_*，qwen-vl-plus）。

    未配置视觉模型 → 降级文本并如实标注（不造假）；视觉调用失败 → 同样降级。
    """
    from qihuang_platform.agent.clients.vision import vision_chat_json
    base = os.environ.get("GEO_VISION_API_BASE", "").strip()
    key = os.environ.get("GEO_VISION_API_KEY", "").strip()
    model = os.environ.get("GEO_VISION_MODEL", "qwen-vl-plus").strip()

    question = (user_msg or "").strip() or "请结合这张图片，给出健康相关的建议。"
    vision_prompt = (
        "你是「岐黄智脑·健康助手」。请结合用户提供的图片，用大白话回答用户的问题。"
        "若是健康/舌象/体质相关图片，只做健康特征描述与养生建议，"
        "并明确提示「以上为辅助参考，具体请咨询执业中医师」；不诊断、不开方。"
        "若图片与健康无关，自然作答即可。\n\n"
        f"用户问题：{question}\n\n{system}"
    )

    if not (base and key):
        return (
            "（我收到了您的图片，但当前视觉模型尚未配置，只能先按文字回答：）\n"
            + question,
            "text-fallback",
        )
    try:
        # vision_chat_json 为同步实现（urllib），放线程池避免阻塞事件循环
        raw = await asyncio.to_thread(
            vision_chat_json, base, key, model, image_ref, vision_prompt)
        reply = (raw or "").strip()
        if not reply:
            raise RuntimeError("视觉模型未返回内容")
        return reply, model
    except Exception as e:  # noqa: BLE001
        logger.warning("[ha] 视觉链路失败，降级文本: %s", e)
        return (
            "（很抱歉，图片识别暂时不可用，我先按文字回答：）\n"
            + question,
            "text-fallback",
        )


# ── 核心应答链路（chat 端点与 OpenAI 兼容层共用，避免逻辑重复）──
async def handle_chat(
    tenant_id: Optional[str],
    user_msg: str,
    history: List[Dict[str, str]],
    store_id: Optional[str] = None,
    end_user_id: Optional[str] = None,
    image: Optional[str] = None,
    max_tokens: int = 1200,
    session_id: Optional[str] = None,
) -> tuple[str, str, bool]:
    """健康助手核心链路：语料注入 → 文本/视觉链路 → 会话记忆 → 配额计数 → 埋点。

    配额检查由调用方负责（chat 端点双层配额；OpenAI 兼容层机构级配额）。
    返回 (reply, model, multimodal)。
    """
    system = _build_system(_load_marketing_prompt(tenant_id, store_id))
    t0 = time.time()
    trace_id = uuid.uuid4().hex

    if image:
        reply, model = await _vision_reply(image, user_msg, system)
    else:
        reply, model = await _text_reply(user_msg, history, system, max_tokens)

    # 会话内记忆落盘（文本轮与多模态轮都记文本侧）
    if session_id and user_msg:
        convo = list(history)
        convo.append({"role": "user", "content": user_msg})
        convo.append({"role": "assistant", "content": reply})
        _persist_session(session_id, convo)

    # 配额计数 + 业务埋点
    record_user_call(tenant_id, end_user_id)
    await record_call(
        tenant_id=tenant_id,
        end_user_id=end_user_id,
        code=0,
        partial=False,
        latency_ms=(time.time() - t0) * 1000,
        trace_id=trace_id,
    )
    return reply, model, bool(image)


# ── 端点 ──
@router.post(
    "/health-assistant/chat",
    summary="健康助手自由问答（多模态自动切换 + 会话记忆 + 双层配额 + 营销语料口子）",
)
async def chat(
    req: ChatRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("health-assistant")),
):
    tenant_id = getattr(request.state, "tenant_id", None)

    # 双层配额 · 第一层：机构级
    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月健康助手机构配额已用完，请升级套餐或次月恢复。")

    # 双层配额 · 第二层：终端 C 端用户级（体验版默认 10 次/月/用户）
    per_user_limit = _plan_per_user_limit(tenant_id)
    if per_user_limit:
        ok, _remain = check_user_quota(tenant_id, req.end_user_id, per_user_limit)
        if not ok:
            return error(
                "QUOTA_EXCEEDED",
                f"该用户本月健康助手使用次数已用完（上限 {per_user_limit} 次），"
                "请次月恢复或升级套餐。",
            )

    user_msg = (req.question or "").strip() or (
        next((m["content"] for m in (req.messages or []) if m.get("role") == "user"), "")
    )
    if not user_msg and not req.image:
        return error("INVALID_PARAM", "question 不能为空（或提供 image）")

    try:
        reply, model, multimodal = await handle_chat(
            tenant_id=tenant_id,
            user_msg=user_msg,
            history=_resolve_session_messages(req),
            store_id=req.store_id,
            end_user_id=req.end_user_id,
            image=req.image,
            max_tokens=req.max_tokens,
            session_id=req.session_id,
        )
        return success({"reply": reply, "model": model, "multimodal": multimodal})
    except Exception as e:  # noqa: BLE001
        logger.exception("[ha] chat 失败")
        return error("INTERNAL_ERROR", str(e))
