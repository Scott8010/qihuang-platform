"""
store_coach · 门店话术对练引擎（8602 自有 4 引擎 LLM 客户端 · 双角色）

场景：门店店员话术训练——AI 扮演顾客角色，店员练习接待/推荐/异议处理/促成话术，
AI 同时给四维话术评估（完整性/专业性/亲和力/合规性）。

复用 refine_llm 验证过的 4 引擎 fallback 链路（DeepSeek→通义千问→GLM-4→Kimi），
key 从 os.environ 读（8602 进程经 geo_vision.env 在 main.py 启动时 load_dotenv 注入，
与 refine_llm 同源，生产已验证可用）。

设计铁律：
- 零新增 LLM SDK 依赖，直接 httpx 调 OpenAI 兼容 /chat/completions；
- 任何引擎全挂 → 返回 error 标记，绝不抛异常中断上游；
- 双角色：customer（扮演顾客接话）+ evaluate（四维话术评估），各自独立 prompt；
- 话术合规由 router 注入合规约束 + compliance-guard 审核链路横切（护栏）。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("store_coach.engine")

# 与 refine_llm._PROVIDERS / content_writer.engine 完全对齐（4 引擎优先级 fallback）
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
    temperature: float = 0.7,
    max_tokens: int = 800,
) -> Optional[str]:
    """单次调用某引擎的 chat/completions，失败返回 None（交由上层 fallback）。"""
    api_key = os.environ.get(provider["env"])
    if not api_key:
        return None
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
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001 - 任一引擎失败都降级到下一个
        logger.warning("[store_coach] %s 调用失败: %s", provider["name"], e)
        return None


async def _generate(
    system: str,
    user: str,
    *,
    temperature: float,
    max_tokens: int,
) -> Tuple[Optional[str], Optional[str]]:
    """依次尝试 4 引擎生成，返回 (文本, 命中引擎key)。全失败返回 (None, None)。"""
    for provider in _PROVIDERS:
        text = await _chat_once(provider, system, user, temperature=temperature, max_tokens=max_tokens)
        if text and text.strip():
            return text.strip(), provider["key"]
    return None, None


# ═══════════════════════════════════════════════════════════════
# 角色 1：AI 扮演顾客（像真人对练一样接话/追问）
# ═══════════════════════════════════════════════════════════════

_CUSTOMER_SYSTEM_PROMPT = (
    "你是一家中医健康门店的顾客，正在与店员对话。你的任务是真实地扮演顾客角色：\n"
    "1) 保持人设：根据给定的顾客画像自然回应，像普通顾客一样说话（口语化、有情绪、会追问）；\n"
    "2) 不要替店员说话、不要替店员完成话术，你只作为顾客回应店员；\n"
    "3) 对店员的推荐保持合理质疑（价格/效果/必要性），考验店员的专业与诚意；\n"
    "4) 回答要简短自然（不超过 3 句），像微信聊天一样，不要长篇大论；\n"
    "5) 直接输出你的回应，不要解释、不要加'顾客说：'前缀。"
)

# 话术场景 → 顾客初始画像
_SCENE_PROFILES: Dict[str, str] = {
    "reception": "50 岁阿姨，进店想了解养生调理，对中医有基本信任但不太懂，注重性价比",
    "recommend": "40 岁上班族女性，睡眠不好想调理，对产品功效有疑虑，怕被推销",
    "objection": "55 岁大叔，觉得产品价格贵，怀疑效果，想讨价还价",
    "close": "30 岁年轻妈妈，给孩子调理脾胃，比较犹豫，需要店员促成下单",
}


def build_customer_user_prompt(scene: str, topic: str, customer_profile: str, history: List[dict]) -> str:
    """构建顾客角色 user prompt（含对练历史）。"""
    lines = [f"场景：{topic}（{scene}）"]
    lines.append(f"你的顾客画像：{customer_profile}")
    if history:
        lines.append("【对话历史】")
        for m in history[-6:]:  # 最近 6 轮，控制上下文
            role = "顾客" if m.get("role") == "assistant" else "店员"
            lines.append(f"{role}：{m.get('content', '')}")
        lines.append("【现在轮到顾客回应】请以顾客身份自然接话：")
    else:
        lines.append("【这是对话开始】顾客先开口：")
    return "\n".join(lines)


async def customer_reply(
    scene: str,
    topic: str,
    customer_profile: str,
    history: List[dict],
) -> Tuple[Optional[str], Optional[str]]:
    """AI 扮演顾客接话/开场。返回 (顾客回应, 引擎key)。"""
    profile = customer_profile or _SCENE_PROFILES.get(scene, _SCENE_PROFILES["reception"])
    user = build_customer_user_prompt(scene, topic, profile, history)
    return await _generate(
        _CUSTOMER_SYSTEM_PROMPT,
        user,
        temperature=0.8,
        max_tokens=300,
    )


# ═══════════════════════════════════════════════════════════════
# 角色 2：话术四维评估（完整性/专业性/亲和力/合规性）
# ═══════════════════════════════════════════════════════════════

_EVALUATE_SYSTEM_PROMPT = (
    "你是一位门店店长兼培训教练，负责评估店员对顾客的话术质量。\n"
    "评分维度（各 0-100）：\n"
    "1) completeness 完整性：是否覆盖开场-介绍-回应异议-促成全流程；\n"
    "2) professional 专业性：产品/项目知识准确、不夸大功效、符合中医养生常识；\n"
    "3) affinity 亲和力：语气自然有温度、像真人聊天而非机械背稿；\n"
    "4) compliance 合规性：无绝对化承诺（根治/包好/100%）、无疗效夸大、无诱导消费。\n"
    "输出 JSON：{\"evaluation\":{\"completeness\":0-100,\"professional\":0-100,\"affinity\":0-100,\"compliance\":0-100},\"score\":加权总分0-100,\"feedback\":\"3-5条具体改进建议（中文）\",\"summary\":\"一句话总评\"}\n"
    "加权：score = completeness*0.25 + professional*0.30 + affinity*0.20 + compliance*0.25。\n"
    "只输出 JSON，不要 markdown 包裹，不要额外解释。"
)


async def evaluate(
    scene: str,
    topic: str,
    customer_profile: str,
    history: List[dict],
    staff_answer: str,
) -> Tuple[Optional[str], Optional[str]]:
    """四维话术评估。返回 (JSON文本, 引擎key)。"""
    profile = customer_profile or _SCENE_PROFILES.get(scene, _SCENE_PROFILES["reception"])
    lines = [
        f"场景：{topic}（{scene}）",
        f"顾客画像：{profile}",
    ]
    if history:
        lines.append("【此前的对话】")
        for m in history[-6:]:
            role = "顾客" if m.get("role") == "assistant" else "店员"
            lines.append(f"{role}：{m.get('content', '')}")
    lines.append(f"【店员最新话术】{staff_answer}")
    lines.append("请评估该话术质量并给出 JSON。")
    return await _generate(
        _EVALUATE_SYSTEM_PROMPT,
        "\n".join(lines),
        temperature=0.3,
        max_tokens=800,
    )
