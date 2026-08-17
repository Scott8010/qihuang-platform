"""
health-advisor · L1 原始 JSON → 内部规范模型解析层

核心结论（探查报告第三节）：
  - `syndrome{name,desc}` 在真实 L1 中**无直接字段**（diagnose 结构化证型全空，证型只在推理链自由文本）。
  - sizhen 一次返回 体质+方剂(含 herbs/indication)+调理+外治+舌脉+综述。
  - 所有输出重自由文本，syndrome 提取**必须依赖 LLM**（方案B 决策2：LLM 解析）。
    骨架阶段用规则兜底保证非空，预留 `_extract_syndrome_llm` 接入点。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .schema import Constitution, Formula, Syndrome


def _unwrap(raw: Dict[str, Any]) -> Dict[str, Any]:
    """兼容 proxy.forward 透传（可能包了 {code,data} 或返回 8601 原始 dict）。"""
    if not isinstance(raw, dict):
        return {}
    return raw.get("data", raw) if isinstance(raw.get("data"), dict) else raw


def parse_sizhen(raw: Dict[str, Any]) -> Tuple[Constitution, List[Formula], List[str]]:
    raw = _unwrap(raw)
    # 体质
    c = raw.get("constitution") or {}
    constitution = Constitution(
        type=c.get("type"),
        desc=c.get("description"),
        score=c.get("score"),
    )
    # 方剂
    formulas: List[Formula] = []
    med = raw.get("medication") or {}
    for f in med.get("formulas") or []:
        formulas.append(Formula(
            name=f.get("formula"),
            items=list(f.get("herbs") or []),
            note=f.get("indication") or f.get("caution"),
        ))
    # 调理 + 外治 → suggestions（纯字符串数组，对齐开工文档 3.2 响应契约）
    _CAT_LABEL = {
        "diet": "饮食", "lifestyle": "起居", "exercise": "运动",
        "acupoints": "穴位", "waizhi": "外治",
    }
    suggestions: List[str] = []
    tiaoli = raw.get("tiaoli") or {}
    for cat in ("diet", "lifestyle", "exercise", "acupoints"):
        val = tiaoli.get(cat)
        if val:
            suggestions.append(f"{_CAT_LABEL[cat]}：{val}")
    waizhi = raw.get("waizhi") or {}
    for m in waizhi.get("methods") or []:
        desc = m.get("desc") or m.get("method")
        if desc:
            suggestions.append(f"外治：{desc}")
    return constitution, formulas, suggestions


def parse_formulas(raw: Dict[str, Any]) -> List[Formula]:
    raw = _unwrap(raw)
    out: List[Formula] = []
    for f in raw.get("formulas") or []:
        out.append(Formula(
            name=f.get("formula") or f.get("name"),
            items=list(f.get("herbs") or f.get("items") or []),
            note=f.get("indication") or f.get("note"),
        ))
    return out


def extract_syndrome_rule(sizhen_raw: Dict[str, Any], chat_raw: Dict[str, Any]) -> Syndrome:
    """
    多源融合提取证型（规则版 LLM 替代，骨架阶段）。
    候选来源优先级（探查实证，越靠前越可信）：
      1. chat.diagnosis.zangfu[].常见证候   —— 脏腑辨证
      2. chat.diagnosis.qingzhi[].pattern    —— 情志辨证（desc 取 治法/代表方）
      3. sizhen.tongue_analysis.pulse_type   —— 舌脉分析（real data 实测可靠，如"气血两虚"）
      4. sizhen.constitution.type + "倾向"    —— 体质兜底
    """
    sizhen = _unwrap(sizhen_raw)
    chat = _unwrap(chat_raw)
    diag = chat.get("diagnosis") or {}
    candidates: List[Tuple[str, Optional[str]]] = []
    # 1) 脏腑辨证
    for z in diag.get("zangfu") or []:
        c = z.get("常见证候")
        if c:
            candidates.append((str(c), None))
    # 2) 情志辨证（desc 取治法/代表方）
    for q in diag.get("qingzhi") or []:
        pat = q.get("pattern")
        if pat:
            candidates.append((str(pat), q.get("治法") or q.get("代表方")))
    # 3) sizhen 舌脉分析（真实数据实测 pulse_type 可靠）
    ta = sizhen.get("tongue_analysis") or {}
    if ta.get("pulse_type"):
        candidates.append((str(ta["pulse_type"]), ta.get("tongue_type") or "舌脉分析"))
    # 选定首个候选
    name: Optional[str] = candidates[0][0] if candidates else None
    desc: Optional[str] = candidates[0][1] if candidates else None
    confidence = diag.get("overall_confidence")
    # 4) 兜底：体质倾向
    if not name:
        c = sizhen.get("constitution") or {}
        if c.get("type"):
            name = f"{c.get('type')}倾向"
    return Syndrome(name=name, desc=desc, confidence=confidence)


# TODO(决策2·LLM提取): 接 core/agent/chat 做 reasoning_chain/qingzhi 的 LLM 抽取，
# 替代规则兜底，输出更准的 syndrome.name/desc。接口签名预留：
#   async def _extract_syndrome_llm(sizhen_raw, diagnose_raw, chat_raw) -> Syndrome
