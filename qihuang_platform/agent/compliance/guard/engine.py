"""hb-compliance-guard 扫描引擎 — 规则命中检测与四态判定。

四态判定口径（严格按最高严重度，可解释、可复现）：
    存在 RED    -> 违规拦截      （硬违规，禁止上架）
    存在 ORANGE -> 存疑待复核    （高风险，需人工复核）
    存在 YELLOW -> 待审查        （轻微提示，人工确认即可）
    零命中      -> 已通过        （引擎判定合规）

E 类（缺失禁忌）特殊逻辑：命中项目关键词后，仅当文中「缺少」必要风险提示时才判为命中。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from rules import GLOBAL_EXEMPT_CONTEXT, SEVERITY_ORDER, compiled_rules

# 否定/免责上下文窗口（字符数）
_EXEMPT_LOOKBEHIND = 14  # 往前看：全局否定词 + 规则级豁免词
_EXEMPT_LOOKAHEAD = 10   # 往后看：仅规则级豁免词（防止后置免责声明洗白违规）

STATE_BLOCKED = "违规拦截"
STATE_REVIEW = "存疑待复核"
STATE_PENDING = "待审查"
STATE_PASSED = "已通过"

ALL_STATES = [STATE_BLOCKED, STATE_PENDING, STATE_REVIEW, STATE_PASSED]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_exempt(text: str, start: int, end: int, rule: dict[str, Any]) -> bool:
    """判断命中是否处于「免责/否定」语境，避免把合规声明误判为违规。

    典型误伤（真实踩过）：
        「不作为医疗诊断依据」 命中「诊断」  -> 免责声明反被判 RED
        「本品不能替代药物」   命中「替代药物」-> 合规必备声明反被罚
        「糖尿病患者慎用」     命中「患者」   -> 禁忌提示被当医疗越界

    窗口设计（关键，别改成简单双向）：
      * 前窗口：查【全局否定词】+ 规则级豁免词 —— 否定语通常前置（不能替代/不作为）。
      * 后窗口：只查【规则级豁免词】 —— 后置修饰仅限本规则语境（患者「慎用」）。
        若后窗口也查全局否定词，「包治百病，不作为医疗建议」这类
        “先违规再补免责声明”的洗白写法会被错误放过。
    """
    rule_exempt = tuple(rule.get("exempt_context", ()))
    before = text[max(0, start - _EXEMPT_LOOKBEHIND):end]
    if any(w in before for w in GLOBAL_EXEMPT_CONTEXT) or any(w in before for w in rule_exempt):
        return True
    if rule_exempt:
        after = text[start:end + _EXEMPT_LOOKAHEAD]
        if any(w in after for w in rule_exempt):
            return True
    return False


def scan_text(text: str) -> list[dict[str, Any]]:
    """对文本执行全量规则扫描，返回命中列表（按严重度排序）。"""
    hits: list[dict[str, Any]] = []

    for rule, patterns in compiled_rules():
        matched_snippet: str | None = None
        for pat in patterns:
            # 同一规则可能多处命中，逐一检查直到找到「非免责语境」的命中
            for m in pat.finditer(text):
                if _is_exempt(text, m.start(), m.end(), rule):
                    continue
                matched_snippet = m.group(0)
                break
            if matched_snippet is not None:
                break
        if matched_snippet is None:
            continue

        # E 类：命中项目词后，若文中已含必要风险提示则不算违规
        requires_missing = rule.get("requires_missing")
        if requires_missing and any(kw in text for kw in requires_missing):
            continue

        hits.append({
            "rule_id": rule["rule_id"],
            "category": rule["category"],
            "severity": rule["severity"],
            "confidence": rule["confidence"],
            "effective_action": rule["effective_action"],
            "dispatch": rule["severity"] == "RED",
            "title": rule["title"],
            "suggested_replace": rule["suggested_replace"],
            "snippet": matched_snippet,
        })

    hits.sort(key=lambda h: (SEVERITY_ORDER.get(h["severity"], 9), h["rule_id"]))
    return hits


def judge_state(hits: list[dict[str, Any]]) -> str:
    """按最高严重度判定四态。"""
    if not hits:
        return STATE_PASSED
    severities = {h["severity"] for h in hits}
    if "RED" in severities:
        return STATE_BLOCKED
    if "ORANGE" in severities:
        return STATE_REVIEW
    return STATE_PENDING


def make_material_id(text: str, institution_id: str, material_key: str | None = None) -> str:
    """内容指纹 ID —— 同门店同文本重复提交视为同一物料（幂等）。

    material_key 给定时（门店同业务文案反复重提的场景），按「业务键」而非文本 hash
    生成指纹，使同业务不同措辞的修订始终覆盖同一条 guard 物料，避免平台看板堆积
    历史版本（material_id 按 text hash 的固有问题）。不给定则沿用 text hash，向后兼容。
    """
    seed = material_key if material_key else text
    digest = hashlib.sha1(f"{institution_id}::{seed}".encode("utf-8")).hexdigest()[:12]
    return f"MAT-{digest.upper()}"


def analyze(text: str, material_type: str, port: str, institution_id: str,
            material_key: str | None = None) -> dict[str, Any]:
    """完整分析：扫描 + 判定 + 组装引擎响应体。"""
    hits = scan_text(text)
    state = judge_state(hits)
    return {
        "material_id": make_material_id(text, institution_id, material_key),
        "institution_id": institution_id,
        "text": text,
        "port": port,
        "material_type": material_type,
        "state": state,
        "hit_count": len(hits),
        "hits": hits,
        "scanned_at": _now_iso(),
    }


# ==================== 人工结论 -> 状态流转 ====================
# decision:     keep / override / remediated / ignore / escalate
# action_taken: none / released / replaced / removed / ticket_created
_DECISION_STATE = {
    "keep": STATE_PASSED,        # 维持原文（人工判定无问题）
    "remediated": STATE_PASSED,  # 已整改
    "ignore": STATE_PASSED,      # 忽略该告警
    "override": STATE_BLOCKED,   # 人工推翻，判定违规
    "escalate": STATE_REVIEW,    # 升级复核
}


def apply_feedback_state(decision: str, current_state: str) -> str:
    """根据人工结论推导新状态；未知 decision 保持原状态。"""
    return _DECISION_STATE.get(decision, current_state)
