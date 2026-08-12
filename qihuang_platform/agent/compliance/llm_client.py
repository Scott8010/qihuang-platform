"""
L2 语义推理 · LLM 客户端（复用 8602 既有 LLMFallbackChain 降级链）

生产实现 `chat()`：把检索到的条款 + 待审文本拼成提示词，交给降级链；
解析返回结构化的违规判定。测试可注入 `mock_llm_call`（见 engine_l2 的 llm_call 契约）。

llm_call 契约（engine_l2 依赖）：callable(prompt:str, system:str) -> Optional[dict]
  返回 dict 形如：
    {"violations":[{"clause_id":str,"severity":str,"confidence":float,
                    "explanation":str,"suggested_replace":str}], "summary":str}
  返回 None 表示 LLM 不可用（引擎降级为仅 L0）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from qihuang_platform.gateway.llm_fallback import llm_fallback

SYSTEM_PROMPT = (
    "你是一名大健康行业内容合规审查员。依据给定合规条款库，判断待审文本是否违规。"
    "只输出与条款库匹配的判定，不要臆造条款；对免责声明/禁忌提示等合规表述不得误判。"
    "返回 JSON：{violations:[{clause_id,severity,confidence,explanation,suggested_replace}], summary}"
)


def _parse_llm(raw: dict) -> Optional[dict]:
    """从降级链结果中抽取结构化违规判定。"""
    if not raw:
        return None
    content = raw.get("content", "")
    if not content:
        return None
    try:
        import json
        import re
        # 优先尝试剥离 markdown 代码块 ```json ... ``` 或 ``` ... ```
        md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if md_match:
            return json.loads(md_match.group(1))
        # 容错：截取首个 {...} JSON 块
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(content[start:end + 1])
    except Exception:
        return None


async def chat(prompt: str, system: str = SYSTEM_PROMPT,
               mock_llm_call: Optional[Callable] = None) -> Optional[dict]:
    """生产 LLM 调用（含降级，异步）。mock_llm_call 注入时走模拟路径。"""
    res = await llm_fallback.call_with_fallback(
        prompt=prompt, system_prompt=system,
        is_generative=False, mock_llm_call=mock_llm_call,
    )
    if res.error:
        return None
    return _parse_llm(res.data)
