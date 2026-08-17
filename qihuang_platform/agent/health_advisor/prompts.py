"""
health-advisor · 问诊话术与意图工程（T2：S1 意图理解 + S2 信息补齐）

设计背景（探查 8601 /chat/api/ask）：
  - 平台 chat 端点是「固定 prompt」透传，不支持注入自定义 system/intent 指令，
    只返回 reply + extracted_symptoms + diagnosis + suggestions（suggestions 含「请补充舌象/脉象」）。
  - 因此 S1/S2 的「prompt 工程」由 health-advisor 编排器自己掌控：
    ① 意图分类（健康咨询 vs 闲聊）——规则命中，避免误把症状咨询当闲聊丢掉；
    ② 缺失项检测（舌/脉/病程/年龄/性别）——基于 profile 完整性 + 病程时间词，按需追问；
    ③ 追问上限 2 次（总纲 3.2 / 风险表「问诊过长流失顾客」），超限按已知 partial 出结果。

所有面向用户的中文话术集中在此，便于后续合规/运营调优。
"""
from __future__ import annotations

import re
from typing import List, Optional

# ── S1 意图分类词库 ──────────────────────────────────────────────
# 健康/症状/中医相关词（命中即视为健康咨询，避免误判）
HEALTH_HINTS = (
    "失眠", "睡不", "睡不着", "多梦", "乏力", "疲倦", "头晕", "头痛", "头昏",
    "心慌", "心悸", "胸闷", "气短", "口苦", "口干", "咽干", "口苦", "胃", "腹胀",
    "肚子", "腹泻", "拉肚子", "便秘", "怕冷", "怕热", "发热", "发烧", "咳嗽",
    "腰酸", "腰痛", "腿", "肩", "颈", "关节", "月经", "心烦", "焦虑", "没胃口",
    "食欲不振", "舌苔", "舌淡", "脉象", "脉弦", "脉滑", "中医", "调理", "体质",
    "方剂", "药", "养生", "健脾", "祛湿", "上火", "畏寒", "盗汗", "耳鸣", "眼花",
)
# 纯闲聊/问候词（仅当无健康词且短时才判闲聊）
CHITCHAT_HINTS = (
    "你好", "您好", "在吗", "在不在", "你是谁", "你干嘛", "哈哈", "呵呵",
    "谢谢", "感谢", "好的", "哦哦", "嗯嗯", "介绍一下", "怎么用", "干嘛的",
)

CHITCHAT_REPLY = (
    "您好！我是岐黄智脑 AI 中医健康顾问 😊\n"
    "我可以基于中医理论，帮您做体质辨识、辨证参考和调理建议。\n"
    "请直接描述您的身体情况，例如：\n"
    "· 最近睡眠不好、乏力、没胃口\n"
    "· 容易上火、口苦、心烦\n"
    "· 胃胀、拉肚子、怕冷\n"
    "补充舌象（如舌淡红苔薄白）和脉象（如脉细）会更精准哦～"
)

# 病程时间词（message 命中即视为已说明病程，不再追问）
_DURATION_RE = re.compile(r"(昨天|前天|今天|近|最近|一直|平时|长期|反复|持续|"
                          r"\d+\s*(天|日|周|星期|个月|月|年)|许久|很久|刚|刚才)")


def classify_intent(text: str) -> str:
    """返回 'health'（健康咨询）或 'chitchat'（闲聊/问候）。

    规则：含健康词 → health；纯闲聊词且短且无健康词 → chitchat；
    无健康词但描述较长（>4字，疑似自由描述症状）→ 仍归 health（宁错判为咨询，不丢需求）。
    """
    t = (text or "").strip()
    if any(k in t for k in HEALTH_HINTS):
        return "health"
    if any(k in t for k in CHITCHAT_HINTS) and len(t) <= 12:
        return "chitchat"
    return "health" if len(t) > 4 else "chitchat"


def detect_missing(*, question: str,
                   tongue: Optional[str], pulse: Optional[str],
                   age: Optional[int], sex: Optional[str]) -> List[str]:
    """基于 profile 完整性 + 病程时间词，返回缺失项列表（顺序即追问优先级）。"""
    miss: List[str] = []
    if not tongue:
        miss.append("舌象")
    if not pulse:
        miss.append("脉象")
    if not _DURATION_RE.search(question or ""):
        miss.append("病程")
    if not age:
        miss.append("年龄")
    if not sex:
        miss.append("性别")
    return miss


# 各缺失项的话术片段（按优先级拼接）
_MISS_PROMPT = {
    "舌象": "【舌象】（如舌淡红、苔薄白/黄腻）",
    "脉象": "【脉象】（如细/弦/滑/数）",
    "病程": "症状持续多久了（如近一周 / 反复半年）",
    "年龄": "您的年龄",
    "性别": "您的性别",
}


def build_ask_more(missing: List[str], round_no: int) -> Optional[str]:
    """生成第 round_no 轮追问文本（round_no 从 1 开始）。超 2 次由调用方控制不传。"""
    if not missing:
        return None
    segs = [_MISS_PROMPT[m] for m in missing if m in _MISS_PROMPT]
    if not segs:
        return None
    prefix = "为了更精准地辨证，麻烦您补充"
    body = "、".join(segs)
    if round_no <= 1:
        suffix = "。补充后我立即给出更有针对性的建议～"
    else:
        suffix = "（这是最后一次追问，您也可直接回复「就按现有信息给建议」，我将基于已知情况给出参考）"
    return f"{prefix}{body}{suffix}"
