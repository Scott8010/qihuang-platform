"""
crawler/classify · 语料 → 5 类实体 规则分类器

不依赖 LLM，纯关键词/结构启发式，可离线、可测、可解释。
5 类标签与 KgReviewItem 审核回流桥（kg_bridge.ENTITY_LABEL_MAP）强一致：
  herb      中药/药材
  syndrome  证候/证型
  formula   方剂/组方
  disease   疾病/病名
  drug      成药/中成药/西药
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

# 5 类固化标签
CANONICAL_TYPES = ("herb", "syndrome", "formula", "disease", "drug")

# 各类关键词（命中越多越置信）。取"强特征词"优先。
_KEYWORDS: Dict[str, List[str]] = {
    "herb": [
        "性味", "归经", "功效", "主治", "用法用量", "药材", "本草", "采制", "炮制",
        "性味归经", "入药部位", "禁忌", "用量", "饮片",
    ],
    "syndrome": [
        "证候", "证型", "辨证", "病机", "舌苔", "脉象", "辨证论治", "证属",
        "证候分析", "舌象", "治法", "证见",
    ],
    "formula": [
        "方剂", "组方", "组成", "君药", "臣药", "佐药", "使药", "煎服法", "方解",
        "方歌", "用法", "剂量", "加减", "水煎服",
    ],
    "disease": [
        "疾病", "病名", "诊断", "病因", "症状", "临床表现", "鉴别诊断", "西医",
        "预后", "流行病学", "体征",
    ],
    "drug": [
        "国药准字", "中成药", "西药", "制剂", "批准文号", "规格", "适应症",
        "不良反应", "国药准字Z", "国药准字H", "OTC",
    ],
}

# 单类命中达到该次数即视为"高置信"
_HIGH_CONF_HITS = 3


@dataclass
class Classification:
    entity_type: str          # 5 类之一；无法判定为 "unknown"
    confidence: float         # 0.0 - 1.0
    rationale: str           # 命中关键词，便于审核追溯
    scores: Dict[str, int]    # 各类命中计数


def classify_entry(
    name: str = "",
    text: str = "",
    hints: Optional[List[str]] = None,
) -> Classification:
    """对一条语料做 5 类分类。

    name/text 任意提供即可；hints 为可选人工/上游提示（须为 5 类标签之一，
    命中则加权）。返回置信度 0-1 与命中理由。
    """
    blob = f"{name or ''}\n{text or ''}"
    scores: Dict[str, int] = {t: 0 for t in CANONICAL_TYPES}
    matched: Dict[str, List[str]] = {t: [] for t in CANONICAL_TYPES}

    for t, kws in _KEYWORDS.items():
        for kw in kws:
            if kw in blob:
                scores[t] += 1
                matched[t].append(kw)

    # 人工/上游提示加权（命中加权 +2，相当于强特征）
    for h in (hints or []):
        if h in scores:
            scores[h] += 2

    winner = max(scores, key=lambda t: scores[t])
    total = sum(scores.values())

    if scores[winner] == 0:
        return Classification(
            entity_type="unknown",
            confidence=0.0,
            rationale="无关键词命中，无法归类",
            scores=scores,
        )

    # 置信度：胜者命中 /（胜者命中 + 0.5*其余命中），并参考绝对命中数
    others = total - scores[winner]
    base = scores[winner] / (scores[winner] + 0.5 * others) if total else 0.0
    # 绝对命中数饱和：>=3 命中视为高置信
    sat = min(1.0, scores[winner] / _HIGH_CONF_HITS)
    confidence = round(min(1.0, 0.6 * base + 0.4 * sat), 3)

    rationale = f"{winner}: {', '.join(matched[winner])}"
    return Classification(
        entity_type=winner,
        confidence=confidence,
        rationale=rationale,
        scores=scores,
    )
