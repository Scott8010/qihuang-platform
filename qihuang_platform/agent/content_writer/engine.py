"""
content_writer · 文案生成引擎（8602 自有 4 引擎 LLM 客户端）

复用 refine_llm 验证过的 4 引擎 fallback 链路（DeepSeek→通义千问→GLM-4→Kimi），
key 从 os.environ 读（8602 进程经 geo_vision.env 在 main.py 启动时 load_dotenv 注入，
与 refine_llm 同源，生产已验证可用）。

设计铁律：
- 零新增 LLM SDK 依赖，直接 httpx 调 OpenAI 兼容 /chat/completions；
- 任何引擎全挂 → 返回 error 标记，绝不抛异常中断上游；
- 文案生成的「合规约束」由 router 的 system prompt 注入（不夸大疗效/不承诺治愈/符合广告法），
  与 compliance-guard 审核链路咬合（B2 营销智能 = content-writer + compliance）。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("content_writer.engine")

# 与 refine_llm._PROVIDERS 完全对齐（4 引擎优先级 fallback）
_PROVIDERS: List[Dict[str, str]] = [
    {
        "key": "deepseek",
        "name": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    {
        "key": "qwen",
        "name": "通义千问",
        "env": "QWEN_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
    },
    {
        "key": "glm",
        "name": "GLM-4",
        "env": "GLM_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
    },
    {
        "key": "kimi",
        "name": "Kimi",
        "env": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
    },
]


async def _chat_once(
    provider: Dict[str, str],
    system: str,
    user: str,
    *,
    temperature: float = 0.8,
    max_tokens: int = 1500,
) -> Tuple[Optional[str], int]:
    """单次调用某引擎的 chat/completions，失败返回 (None, 0)（交由上层 fallback）。

    返回 (文本, 本次消耗 token)；token 取自响应 usage.total_tokens（#586 真扣费用）。
    """
    api_key = os.environ.get(provider["env"])
    if not api_key:
        return None, 0
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage") or {}
            tokens = int((usage.get("total_tokens") or 0) or 0)
            return content, tokens
    except Exception as e:  # noqa: BLE001 - 任一引擎失败都降级到下一个
        logger.warning("[content_writer] %s 调用失败: %s", provider["name"], e)
        return None, 0


async def generate(
    system: str,
    user: str,
    *,
    temperature: float = 0.8,
    max_tokens: int = 1500,
) -> Tuple[Optional[str], Optional[str], int]:
    """依次尝试 4 引擎生成文案，返回 (文本, 命中引擎key, 消耗token)。全失败返回 (None, None, 0)。"""
    for provider in _PROVIDERS:
        text, tok = await _chat_once(provider, system, user, temperature=temperature, max_tokens=max_tokens)
        if text and text.strip():
            return text.strip(), provider["key"], tok
    return None, None, 0
