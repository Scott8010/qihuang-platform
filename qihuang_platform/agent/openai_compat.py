"""OpenAI 兼容层（Open WebUI 接入健康助手，2026-08-23 老黄拍板）

端点：
  GET  /v1/models             → 返回 health-assistant 模型
  POST /v1/chat/completions   → OpenAI 协议（非流式 + SSE 流式），转发 health-assistant 核心链路

鉴权：Authorization: Bearer <app_key>（8602 API Key）。
      Open WebUI 连接器只能发标准 Bearer，发不了 8602 的 X-App-Key/X-Signature HMAC 自定义头，
      故本层用 Bearer 简化鉴权：验证 key 存在且 active，租户归属从 key 取。
      定位：内网/演示通道（Open WebUI 运营台），正式 C 端仍走 /health-assistant/chat 双鉴权。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from qihuang_platform.agent.health_assistant.metering import check_quota
from qihuang_platform.agent.health_assistant.router import handle_chat
from qihuang_platform.gateway.auth import get_api_key_info

router = APIRouter(prefix="/v1", tags=["OpenAI 兼容（Open WebUI）"])

_MODEL_ID = "health-assistant"


class OpenAIMessage(BaseModel):
    role: str
    content: Any = None


class OpenAIChatRequest(BaseModel):
    model: str = _MODEL_ID
    messages: List[OpenAIMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    user: Optional[str] = None  # OpenAI user 字段可承载 end_user_id


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _resolve_key(authorization: Optional[str]):
    """解析 Bearer app_key → key_info；无效返回 (None, None)。"""
    app_key = _parse_bearer(authorization)
    if not app_key:
        return None, None
    info = get_api_key_info(app_key)
    if not info or info.get("status") != "active":
        return None, None
    return app_key, info


def _unauthorized():
    return JSONResponse(status_code=401, content={
        "error": {"message": "Invalid API Key", "type": "invalid_request_error",
                  "code": "invalid_api_key"},
    })


def _openai_error(status: int, message: str, code: str = "invalid_request_error"):
    return JSONResponse(status_code=status, content={
        "error": {"message": message, "type": "invalid_request_error", "code": code},
    })


def _chat_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:20]


def _extract_question(messages: List[OpenAIMessage]) -> tuple[Optional[str], List[Dict[str, str]], Optional[str]]:
    """取最后一条 user 消息为问题，其余作历史；支持 OpenAI 多模态数组（提取 text + 首个 image_url）。

    返回 (question, history, image_url)。image_url 为 data URI / http(s) URL，供 handle_chat(image=...) 走视觉链路。
    """
    msgs = [m for m in messages if m.role in ("user", "assistant")]
    user_idx = [i for i, m in enumerate(msgs) if m.role == "user"]
    if not user_idx:
        return None, [], None
    last = user_idx[-1]
    content = msgs[last].content
    image_url = None
    if isinstance(content, list):  # 多模态数组：取 text 部分 + 首个 image_url
        text_parts = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text":
                text_parts.append(p.get("text", ""))
            elif p.get("type") == "image_url":
                url = (p.get("image_url") or {}).get("url")
                if url and not image_url:
                    image_url = url
        question = " ".join(text_parts) or ""
    else:
        question = str(content or "")
    question = question.strip()
    history = [{"role": m.role, "content": str(m.content or "")} for m in msgs[:last]]
    return question, history, image_url


@router.get("/models", summary="OpenAI 兼容：模型列表")
async def openai_models(authorization: Optional[str] = Header(None)):
    app_key, info = _resolve_key(authorization)
    if not info:
        return _unauthorized()
    return {"object": "list", "data": [
        {"id": _MODEL_ID, "object": "model", "created": 0, "owned_by": "qihuang",
         "description": "岐黄智脑·健康助手（C 端健康服务，门店语料 + 合规内建）"},
    ]}


@router.post("/chat/completions", summary="OpenAI 兼容：聊天补全（非流式 + SSE 流式）")
async def openai_chat_completions(
    req: OpenAIChatRequest,
    authorization: Optional[str] = Header(None),
):
    app_key, info = _resolve_key(authorization)
    if not info:
        return _unauthorized()

    tenant_id = info.get("tenant_id")
    if not check_quota(tenant_id):
        return _openai_error(429, "机构本月健康助手配额已用完，请升级套餐或次月恢复。", "quota_exceeded")

    question, history, image_url = _extract_question(req.messages)
    if not question and not image_url:
        return _openai_error(400, "messages 至少需要一条非空 user 消息或图片", "invalid_request")

    end_user_id = req.user or app_key  # OpenAI user 字段优先，缺省按 key 维度计
    try:
        reply, model, _ = await handle_chat(
            tenant_id=tenant_id,
            user_msg=question or "请结合图片回答。",
            history=history,
            end_user_id=end_user_id,
            image=image_url,
            max_tokens=req.max_tokens or 1200,
        )
    except Exception as e:  # noqa: BLE001
        return _openai_error(500, str(e), "internal_error")

    cid = _chat_id()
    created = int(time.time())

    if req.stream:
        def gen():
            for delta in ({"role": "assistant"}, {"content": reply}, {}):
                payload = {
                    "id": cid, "object": "chat.completion.chunk", "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield 'data: {"id":"%s","object":"chat.completion.chunk","created":%d,"model":"%s","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n' % (cid, created, model)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    return {
        "id": cid, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
