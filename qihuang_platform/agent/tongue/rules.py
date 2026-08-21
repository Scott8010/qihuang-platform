"""舌象标签 → 健康状态倾向 · 确定性规则映射（Layer2 P1 兜底）。

对应 HB 舌诊三层解耦协助单（2026-08-21）T2「短期兜底」：
  - 输入：Layer1 归一化后的结构化舌象（tongue_body / coating / labels）
  - 输出：syndrome_hints 数组，每项 {name, confidence, source:"rule"}
    （name 用中医证候表述；对外白话名由 HB Layer3 interpreter 做 mapping）
  - 铁律（协助单 T4 硬指标 #5）：
      * 健康舌（淡红/薄白润/舌形正常/无瘀斑歪斜）→ 空数组，不对健康舌硬编结论；
      * 未识别字段（"未识别"）不作为任何规则的触发信号（fail-closed，不臆断）；
      * 规则输出必须标 source="rule"，绝不伪装成模型结论。

规则表由 8602 组与 HB 组共同维护（协助单 T2），后续可替换为 L1 文本引擎真输出。
仅供健康评估参考，不构成医疗诊断（去医疗化）。
"""
from __future__ import annotations

# ───────────────── 规则表：单信号 → (倾向名, 基础置信度) ─────────────────
# 置信度口径：确定性规则，非统计概率；多信号相互印证时 +0.1（上限 0.9），输出前按置信度降序、截前 3 条。

_SHAPE_RULES = {
    "齿痕": ("脾虚湿盛倾向", 0.75),
    "胖大": ("脾虚湿盛倾向", 0.60),
    "瘦薄": ("气血不足倾向", 0.65),
    "裂纹": ("阴液不足倾向", 0.65),
    "芒刺": ("热盛伤津倾向", 0.60),
    "点刺": ("热盛伤津倾向", 0.60),
}

_BODY_COLOR_RULES = {
    "淡白": ("气血两虚倾向", 0.60),
    "绛": ("阴虚火旺倾向", 0.60),
    "青紫": ("血瘀倾向", 0.70),
    "红": ("热象倾向", 0.50),
}

_PETECHIAE_RULES = {
    "有瘀斑": ("血瘀倾向", 0.70),
    "有瘀点": ("血瘀倾向", 0.60),
}

_COAT_COLOR_RULES = {
    "黄": ("湿热内蕴倾向", 0.55),
    "灰黑": ("阳虚寒盛或里热炽盛倾向", 0.45),  # 灰黑苔寒热两读，低置信度如实标注
}

_QUALITY_RULES = {
    "腻": ("湿浊内蕴倾向", 0.55),
    "燥": ("阴液不足倾向", 0.55),
    "腐": ("湿浊内蕴倾向", 0.50),
}

# 组合信号（苔色 × 苔厚 × 苔质）→ 倾向；键为 (color, thickness, quality) 的宽松匹配
_COMBO_RULES = [
    (("黄", None, "腻"), ("湿热内蕴倾向", 0.80)),
    (("黄", "厚", None), ("湿热内蕴倾向", 0.70)),
    (("白", "厚", "腻"), ("湿浊内蕴倾向", 0.70)),
    (("白", "厚", None), ("湿浊内蕴倾向", 0.60)),
    (("白", None, "腻"), ("湿浊内蕴倾向", 0.60)),
]

# 苔剥脱类
_PEELING_RULES = {"剥脱": ("胃阴不足倾向", 0.60)}

_MAX_HINTS = 3
_CORROBORATE_BONUS = 0.10
_CONF_CAP = 0.90


def _has(value: str, keyword: str) -> bool:
    """字段值包含关键词且非未识别占位，才算有效信号。"""
    if not value or value == "未识别":
        return False
    return keyword in str(value)


def _positive(value: str, keyword: str) -> bool:
    """阳性信号：包含关键词，且未被「无关键词」否定形式覆盖（如「无剥脱」≠ 剥脱）。"""
    if not _has(value, keyword):
        return False
    s = str(value)
    return ("无" + keyword) not in s


def _is_healthy(body: dict, coat: dict, labels: list[str]) -> bool:
    """健康舌判定：淡红舌 + 薄白润苔 + 舌形正常 + 无瘀斑/歪斜/剥脱/腐苔。"""
    color = str(body.get("color") or "")
    shape = str(body.get("shape") or "")
    c_color = str(coat.get("color") or "")
    thickness = str(coat.get("thickness") or "")
    quality = str(coat.get("quality") or "")
    healthy = (
        ("淡红" in color)
        and ("正常" in shape)
        and ("白" in c_color)
        and ("薄" in thickness)
        and ("润" in quality or "正常" in quality)
        and not _positive(body.get("petechiae") or "", "瘀")
        and not _positive(body.get("deviation") or "", "歪斜")
        and not _positive(coat.get("peeling") or "", "剥脱")
        and not _positive(coat.get("corrosion") or "", "腐")
    )
    # labels 里出现明确异常标签则否决健康判定（如「有齿痕」「有裂纹」）
    abnormal_marks = ("有齿痕", "有裂纹", "有点刺", "瘀斑", "瘀点", "厚苔", "黄", "腻苔", "剥脱", "腐苔")
    if any(m in str(x) for x in labels for m in abnormal_marks):
        return False
    return healthy


def derive_syndrome_hints(tongue: dict) -> list[dict]:
    """Layer1 归一化舌象 → Layer2 健康状态倾向（规则兜底，P1）。

    输入 tongue 结构（engine._normalize_tongue 产物）：
        {"tongue_body": {...}, "coating": {...}, "labels": [...], "syndrome_hints": [...]}
    输出：[{name, confidence, source:"rule"}]，健康舌 → []。
    """
    body = tongue.get("tongue_body") or {}
    coat = tongue.get("coating") or {}
    labels = [str(x) for x in (tongue.get("labels") or [])]

    if _is_healthy(body, coat, labels):
        return []

    scores: dict[str, float] = {}

    def add(name: str, conf: float) -> None:
        if name in scores:
            scores[name] = min(_CONF_CAP, max(scores[name], conf) + _CORROBORATE_BONUS)
        else:
            scores[name] = conf

    # ── 舌形 ──
    shape = str(body.get("shape") or "")
    for kw, (name, conf) in _SHAPE_RULES.items():
        if _has(shape, kw):
            add(name, conf)

    # ── 舌色 ──
    color = str(body.get("color") or "")
    for kw, (name, conf) in _BODY_COLOR_RULES.items():
        if _has(color, kw):
            add(name, conf)

    # ── 瘀斑瘀点 ──
    pet = str(body.get("petechiae") or "")
    for kw, (name, conf) in _PETECHIAE_RULES.items():
        if _has(pet, kw):
            add(name, conf)

    # ── 苔：无苔/剥脱优先（互斥于颜色厚度判断） ──
    c_color = str(coat.get("color") or "")
    thickness = str(coat.get("thickness") or "")
    quality = str(coat.get("quality") or "")
    peeling = str(coat.get("peeling") or "")

    if "无苔" in c_color or "无苔" in thickness:
        add("阴液不足倾向", 0.65)
    if _positive(peeling, "剥脱"):
        for kw, (name, conf) in _PEELING_RULES.items():
            if kw in peeling:
                add(name, conf)
    else:
        # ── 苔色/苔质单信号 ──
        for kw, (name, conf) in _COAT_COLOR_RULES.items():
            if _has(c_color, kw):
                add(name, conf)
        for kw, (name, conf) in _QUALITY_RULES.items():
            if _has(quality, kw):
                add(name, conf)
        # ── 组合信号（苔色 × 厚 × 质） ──
        for (rc, rt, rq), (name, conf) in _COMBO_RULES:
            hit_color = rc is None or (rc and rc in c_color)
            hit_thick = rt is None or (rt and rt in thickness)
            hit_qual = rq is None or (rq and rq in quality)
            if hit_color and hit_thick and hit_qual:
                add(name, conf)

    # ── labels 兜底信号：结构化字段未识别但标签有明确异常时，低置信度补充 ──
    label_signals = {
        "有齿痕": ("脾虚湿盛倾向", 0.55),
        "有裂纹": ("阴液不足倾向", 0.50),
        "有点刺": ("热盛伤津倾向", 0.50),
        "瘀斑": ("血瘀倾向", 0.60),
        "瘀点": ("血瘀倾向", 0.50),
        "厚苔": ("湿浊内蕴倾向", 0.50),
        "黄": ("湿热内蕴倾向", 0.45),
        "有腻苔": ("湿浊内蕴倾向", 0.50),
        "剥脱": ("胃阴不足倾向", 0.50),
    }
    for mark, (name, conf) in label_signals.items():
        if any(mark in x and not x.startswith("无") for x in labels):
            add(name, conf)

    hints = [
        {"name": name, "confidence": round(conf, 2), "source": "rule"}
        for name, conf in sorted(scores.items(), key=lambda kv: -kv[1])[:_MAX_HINTS]
    ]
    return hints
