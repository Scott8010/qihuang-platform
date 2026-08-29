"""
岐黄智脑 · 内容管控 AI 提炼客户端
================================
用途：把 8602 审核队列里「原始、难读」的待审条目（尤其是英文学术文献摘录）
加工成审核人可直接决策的结构化中文摘要。

设计铁律：
- 复用 8601 多模型 LLM 的 OpenAI 兼容协议（base_url / model 完全一致），
  但**不依赖 8601 在线**，也不引入 openai SDK —— 直接用 8602 已有的 httpx 调
  POST {base_url}/chat/completions，零新增依赖、零镜像 rebuild。
- 4 个引擎按优先级 fallback：DeepSeek → 通义千问 → GLM-4 → Kimi。
- key 从 os.environ 读（8602 .env 由 main.py 启动时 load_dotenv 注入）。
- 任何引擎全挂 → 返回带 error 标记的字典，绝不抛异常中断审核台。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("qihuang.refine_llm")


# ── 引擎注册表（与 8601 core/llm_client.py 完全对齐）──
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


# 万方等站点抓取时混入的浏览器警告垃圾文本（应跳过，不当作文献正文）
_JUNK_PATTERNS = [
    "检测到您的浏览器版本过低",
    "万方数据知识服务平台",
    "Google Chrome",
    "Microsoft Edge",
    "Firefox",
    "Safari 浏览器",
    "建议使用更高版本的浏览器",
]


def is_mostly_chinese(text: str) -> bool:
    """中文字符占比 > 30% 视为中文为主（铁律#10：外文先翻译再处理）。"""
    if not text:
        return True
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    total = len(text.strip())
    if total == 0:
        return True
    return (chinese / total) > 0.3


def _is_junk(text: str) -> bool:
    return any(p in (text or "") for p in _JUNK_PATTERNS)


def is_classics_content(content: Dict[str, Any]) -> bool:
    """检测是否为「典籍抽取」来源的待审条目。
    主依据：含 entity_name（自生长引擎用 name，不用 entity_name），
    且非自生长文献（无 clause_text / ai_extracted）。
    props.source_text 是否有值只决定是否可提炼，不影响类型判定，
    因此空源典籍条目也会被前端当作典籍面板渲染（仅无提炼结果）。
    """
    if not isinstance(content, dict):
        return False
    has_entity_name = isinstance(content.get("entity_name"), str) and bool(content.get("entity_name", "").strip())
    if not has_entity_name:
        return False
    is_auto_growth = bool(content.get("clause_text") or content.get("ai_extracted"))
    return not is_auto_growth


def _build_source_text(content: Dict[str, Any]) -> Optional[str]:
    """
    选出最适合提炼的原文。
    优先级：ai_extracted（AI 已萃取的摘要/标题）> 干净 clause_text > original_text > source_doc。
    跳过万方浏览器警告等 junk；返回最长且非空者作为主源。
    """
    cands: List[str] = []
    for field in ("ai_extracted", "clause_text", "original_text", "source_doc"):
        v = content.get(field)
        if isinstance(v, str) and v.strip() and not _is_junk(v):
            cands.append(v.strip())
    if not cands:
        return None
    # 取信息量最大（最长）的一段作为主源
    cands.sort(key=len, reverse=True)
    return cands[0]


def _parse_refined_json(raw: str) -> Optional[Dict[str, Any]]:
    """容错解析 LLM 返回的 JSON（去掉 markdown 代码块包裹）。"""
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    # 兜底：截取第一个 { 到最后一个 }
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s != -1 and e != -1 and e > s:
        cleaned = cleaned[s : e + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("refine LLM 返回非 JSON: %s", raw[:200])
        return None
    if not isinstance(data, dict):
        return None
    # 规范化字段：列表类缺省为 []，字符串类缺省为 None/空串
    for list_field in ("key_findings_zh", "consensus_points", "divergence_points"):
        val = data.get(list_field)
        if isinstance(val, str):
            val = [v for v in val.split("\n") if v.strip()] or [val]
        data[list_field] = val if isinstance(val, list) else []
    for str_field in ("research_title_zh", "final_conclusion_zh", "original_text_zh"):
        v = data.get(str_field)
        data[str_field] = v if isinstance(v, str) else None
    return data


def _parse_classics_json(raw: str) -> Optional[Dict[str, Any]]:
    """容错解析典籍 AI 返回的 JSON（与 _parse_refined_json 同策略）。"""
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s != -1 and e != -1 and e > s:
        cleaned = cleaned[s : e + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("classics 提炼返回非 JSON: %s", raw[:200])
        return None
    if not isinstance(data, dict):
        return None
    # 规范化字段：列表类缺省为 []，字符串类缺省为 None
    for list_field in ("key_components_zh",):
        val = data.get(list_field)
        if isinstance(val, str):
            val = [v for v in val.split("\n") if v.strip()] or [val]
        data[list_field] = val if isinstance(val, list) else []
    for str_field in ("entry_name_zh", "entry_type_zh", "source_text_zh", "fangyi_zh", "source_attribution_zh", "indication_zh"):
        v = data.get(str_field)
        data[str_field] = v if isinstance(v, str) else None
    return data


async def _chat_once(provider: Dict[str, str], system: str, user: str, max_tokens: int = 1500) -> Tuple[Optional[str], int]:
    """单次调用某引擎的 chat/completions，失败返回 (None, 0)。

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
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
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
        logger.warning("%s 提炼调用失败: %s", provider["name"], e)
        return None, 0


_REFINE_PROMPT_ZH = """你是一位中医知识图谱的审校助手，负责把待审核知识条目整理成可直接用于人工审核的结构化中文摘要。
请基于【原文】完成：
1) 提炼「研究题目」（中文，若原文无明确题目则据内容概括）
2) 提炼「最终结论」（中文，一段话总结核心结论）
3) 列出「核心发现」（3-5 条要点）
4) 列出「共识点」（不同来源/模型一致认同的结论，2-4 条）
5) 列出「分歧点」（存在争议或尚未一致的结论，1-3 条；无则填“无明显分歧”）
若原文信息不足（如仅有标题、无摘要），在对应字段注明“原文信息不足”。

严格只输出如下 JSON，不要任何解释性文字：
{{
  "research_title_zh": "研究题目",
  "final_conclusion_zh": "最终结论",
  "key_findings_zh": ["发现1", "发现2"],
  "consensus_points": ["共识1", "共识2"],
  "divergence_points": ["分歧1"]
}}"""

_REFINE_PROMPT_EN = """你是一位精通中医术语的医学翻译专家兼文献审校助手。下面是一段英文学术/中医相关文献摘录。
请完成：
1) 把【原文】翻译为专业中文（字段 original_text_zh）
2) 提炼「研究题目」（中文）
3) 提炼「最终结论」（中文，一段话总结核心结论）
4) 列出「核心发现」（3-5 条要点，中文）
5) 列出「共识点」（不同来源/模型一致认同的结论，2-4 条，中文）
6) 列出「分歧点」（存在争议或尚未一致的结论，1-3 条，中文；无则填“无明显分歧”）
中医术语须用标准中文（如 Psoriasis→银屑病、TNF-α→肿瘤坏死因子α）。若原文信息不足（如仅有标题），在对应字段注明“原文信息不足”。

严格只输出如下 JSON，不要任何解释性文字：
{{
  "research_title_zh": "研究题目",
  "final_conclusion_zh": "最终结论",
  "original_text_zh": "原文中文翻译",
  "key_findings_zh": ["发现1", "发现2"],
  "consensus_points": ["共识1", "共识2"],
  "divergence_points": ["分歧1"]
}}"""


_CLASSICS_PROMPT_ZH = """你是一位中医典籍审校助手，负责把「典籍抽取」得到的待审条目整理成可直接用于人工审核的结构化中文摘要。
请基于【原文摘录】与中医典籍知识完成：
1) 标注「条目名称」（中文标准名，忠于原条）
2) 标注「条目类型」（如：经方 / 证候 / 中药 / 症状 / 治法，用中文，若无把握据原样标注）
3) 精校「原文摘录」（保持典籍原貌，纠正明显错字；若与原文一致则注明“与原文一致”）
4) 阐释「方义/释义」（该条目的核心含义、组方意义或病机解释，2-4 句）
5) 注明「出处」（所属典籍/篇章，如《伤寒论·太阳病篇》；若原文未提供则据常识标注并注明“据常识推断”）
6) 列出「关键组成/要点」（方剂则列组成药味 3-6 味；证候则列关键症状；非方剂条目可填“—”）
7) 说明「主治/适用」（该条目对应的主治病证或适用场景，1-3 句）
若字段信息不足，在对应位置注明“信息不足”。

严格只输出如下 JSON，不要任何解释性文字：
{{
  "entry_name_zh": "条目名称",
  "entry_type_zh": "条目类型",
  "source_text_zh": "原文摘录（精校）",
  "fangyi_zh": "方义/释义",
  "source_attribution_zh": "出处",
  "key_components_zh": ["组成1", "组成2"],
  "indication_zh": "主治/适用"
}}"""


async def refine_review_content(content: Dict[str, Any]) -> Dict[str, Any]:
    """
    把一条待审条目的原始 content 加工为 _refined 结构化摘要。
    自动按 content 形状分流：
    - 典籍抽取条目（entity_name + props.source_text）→ 典籍专用 schema
    - 自生长引擎文献（clause_text / ai_extracted）→ 文献翻译+提炼 schema
    任何引擎不可用都优雅降级，绝不抛异常。
    """
    content = content or {}
    if is_classics_content(content):
        return await _refine_classics(content)
    return await _refine_literature(content)


async def _refine_literature(content: Dict[str, Any]) -> Dict[str, Any]:
    """原自生长引擎文献提炼逻辑（行为保持不变）。"""
    source = _build_source_text(content)
    is_english = bool(source) and not is_mostly_chinese(source)
    meta = {
        "entry_kind": "literature",
        "is_english": is_english,

        "provider": None,
        "model": None,
        "refined_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }

    # 无可用原文：直接返回空壳，前端提示“无提炼素材”
    if not source:
        meta["error"] = "NO_SOURCE"
        return {
            "research_title_zh": None,
            "final_conclusion_zh": None,
            "original_text_zh": None,
            "key_findings_zh": [],
            "consensus_points": [],
            "divergence_points": [],
            **meta,
        }

    system = "你是中医文献审校助手，所有输出必须为中文。" if is_english else "你是中医文献审校助手，所有输出必须为中文。"
    user = (_REFINE_PROMPT_EN if is_english else _REFINE_PROMPT_ZH) + f"\n\n【原文】\n{source[:3500]}"

    for provider in _PROVIDERS:
        raw, _tok = await _chat_once(provider, system, user, max_tokens=1500)
        if not raw:
            continue
        parsed = _parse_refined_json(raw)
        if not parsed:
            continue
        meta["provider"] = provider["name"]
        meta["model"] = provider["model"]
        return {**parsed, **meta}

    # 全部引擎不可用
    meta["error"] = "LLM_UNAVAILABLE"
    return {
        "research_title_zh": None,
        "final_conclusion_zh": None,
        "original_text_zh": None,
        "key_findings_zh": [],
        "consensus_points": [],
        "divergence_points": [],
        **meta,
    }


def _empty_classics(meta: Dict[str, Any]) -> Dict[str, Any]:
    """典籍提炼空壳（NO_SOURCE / LLM_UNAVAILABLE 时返回）。"""
    return {
        "entry_name_zh": None,
        "entry_type_zh": None,
        "source_text_zh": None,
        "fangyi_zh": None,
        "source_attribution_zh": None,
        "key_components_zh": [],
        "indication_zh": None,
        **meta,
    }


async def _refine_classics(content: Dict[str, Any]) -> Dict[str, Any]:
    """典籍抽取条目专用提炼：基于 props.source_text 生成结构化中文审校摘要。"""
    props = content.get("props") or {}
    source = (props.get("source_text") if isinstance(props, dict) else "") or ""
    source = source.strip()
    entity_name = (content.get("entity_name") if isinstance(content.get("entity_name"), str) else "") or ""
    entity_type = (content.get("entity_type") if isinstance(content.get("entity_type"), str) else "") or ""

    meta = {
        "entry_kind": "classics",
        "is_english": False,  # 典籍几乎必为中文
        "provider": None,
        "model": None,
        "refined_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }

    # 无可用原文：直接返回空壳，前端提示“无提炼素材”
    if not source:
        meta["error"] = "NO_SOURCE"
        return _empty_classics(meta)

    system = "你是中医典籍审校助手，所有输出必须为中文，且须忠于典籍原意与标准术语。"
    user = (
        _CLASSICS_PROMPT_ZH
        + f"\n\n【条目名称】{entity_name}\n【条目类型】{entity_type}\n【原文摘录】\n{source[:3500]}"
    )

    for provider in _PROVIDERS:
        raw, _tok = await _chat_once(provider, system, user, max_tokens=1500)
        if not raw:
            continue
        parsed = _parse_classics_json(raw)
        if not parsed:
            continue
        meta["provider"] = provider["name"]
        meta["model"] = provider["model"]
        return {**parsed, **meta}

    # 全部引擎不可用
    meta["error"] = "LLM_UNAVAILABLE"
    return _empty_classics(meta)
