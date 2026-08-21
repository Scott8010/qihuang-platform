"""舌象健康特征分析引擎（MindSen 路 A：8602 视觉网关 + 舌象结构化 prompt）。

设计（对齐 HB 契约 `tongue_face_analysis.md` §3.5 与颐掌柜 2026-08-21 交接）：
  - 复用共享视觉客户端 `agent/clients/vision.py`（fortune 户型图 / compliance 图片审核同款网关），
    仅新增一类"舌象结构化分析"prompt，不引入任何 CV 模型自研/ONNX 部署；
  - 视觉模型经 env 读取：GEO_VISION_API_BASE / GEO_VISION_API_KEY / GEO_VISION_MODEL
    （生产已配 qwen-vl-plus@DashScope，与 fortune 同源）；
  - 输出对齐 15 类标签 + TongueAnalysis 字段（含 petechiae/texture/deviation/corrosion/peeling 5 新字段），
    返回结构 {engine, tongue, face, combined_syndrome}；
  - 铁律：未配置视觉模型 / 调用失败 → mode=image_pending / image_error，绝不回退造假数据
    （去静态化 fail-closed，与 HB mind_sen/client.py 口径一致）。

仅供健康特征分析参考，不构成医疗诊断（去医疗化）。
"""
from __future__ import annotations

import os

from qihuang_platform.agent.clients.vision import (
    normalize_vision_json,
    vision_chat_json,
)
from qihuang_platform.agent.tongue.rules import derive_syndrome_hints

# ───────────────── 舌象结构化分析 prompt ─────────────────
# 契约口径（tongue_face_analysis.md §3.5，颐掌柜 2026-08-21 升级）：
#   15 类标签：绛_舌胖_有齿痕_有裂纹_有点刺_瘀斑_瘀点_老嫩_歪斜_苔色_厚薄_腻润_腐_剥脱
TONGUE_VISION_PROMPT = (
    "你是中医舌象健康特征分析助手（仅供健康评估参考，不作诊断）。请仔细审视这张舌面照片，"
    "仅输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），严格按以下字段与枚举取值：\n"
    "{\n"
    '  "tongue_body": {\n'
    '    "color": "淡红|红|绛|青紫|淡白",\n'
    '    "shape": "正常|胖大|瘦薄|齿痕|裂纹|芒刺(点刺)",\n'
    '    "petechiae": "无瘀斑|有瘀斑|有瘀点",\n'
    '    "texture": "无老嫩|老|嫩",\n'
    '    "deviation": "无歪斜|歪斜"\n'
    "  },\n"
    '  "coating": {\n'
    '    "color": "白|黄|灰黑|无苔",\n'
    '    "thickness": "薄|厚|无苔",\n'
    '    "quality": "润|腻|燥|正常",\n'
    '    "corrosion": "无腐苔|腐苔",\n'
    '    "peeling": "无剥脱|剥脱"\n'
    "  },\n"
    '  "labels": ["绛","舌胖","有齿痕","有裂纹","有点刺","无瘀斑","无瘀点","无老嫩","无歪斜","黄","厚苔","无腐苔","有腻苔","润","无剥脱"],\n'
    '  "syndrome_hints": ["脾虚湿盛","湿热内蕴","阴虚火旺"等 1-3 条中医证候倾向提示，若图片质量差可输出空数组]\n'
    "}\n"
    "要求：只描述照片可见特征；图片不清晰或非舌象图时，fields 输出\"未识别\"占位并保持结构完整；"
    "labels 必须从 15 类标签中逐项给出（每项取其实际状态，含\"无\"前缀表示未检出）。"
)

# 面色图（可选，两图齐全时综合）结构化 prompt
FACE_VISION_PROMPT = (
    "你是中医面色健康特征分析助手（仅供健康评估参考，不作诊断）。请仔细审视这张面部照片，"
    "仅输出一个 JSON 对象（不要 markdown 代码块、不要多余文字）：\n"
    "{\n"
    '  "complexion": "正常红润|淡白|萎黄|潮红|青暗|黧黑",\n'
    '  "lustre": "有光泽|少泽|无泽",\n'
    '  "note": "观察到的其它可见面色特征，如眼睑、唇色等（无则空字符串）"\n'
    "}\n"
    "要求：只描述照片可见特征；不清晰或非人像时输出\"未识别\"占位并保持结构完整。"
)

_ENGINE_NAME = "qwen-vl-plus"  # 生产实际模型，engine 字段如实回显

# 视觉模型常输出的变体 → 契约枚举归一（2026-08-21 探针实测：qwen 会输出「厚苔」而枚举为「厚」）
_ENUM_ALIASES = {
    "厚苔": "厚", "薄苔": "薄", "黄苔": "黄", "白苔": "白",
    "有腻苔": "腻", "腻苔": "腻", "有剥脱": "剥脱", "有腐苔": "腐苔",
}


def _norm_field(value, default="未识别") -> str:
    """字段取值归一：去空白/引号，空值补占位，变体映射到契约枚举。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return "有" if value else "无"
    s = str(value).strip().strip('"').strip("'")
    if not s:
        return default
    return _ENUM_ALIASES.get(s, s)


def _normalize_tongue(content: str) -> dict:
    """视觉模型输出 → TongueAnalysis 结构化字段（容错 key 别名/缺省补占位）。"""
    raw = normalize_vision_json(content)
    if not isinstance(raw, dict) or not raw:
        return {
            "tongue_body": {
                "color": "未识别", "shape": "未识别",
                "petechiae": "未识别", "texture": "未识别", "deviation": "未识别",
            },
            "coating": {
                "color": "未识别", "thickness": "未识别", "quality": "未识别",
                "corrosion": "未识别", "peeling": "未识别",
            },
            "labels": [], "syndrome_hints": [],
        }

    body_raw = raw.get("tongue_body") or {}
    coat_raw = raw.get("coating") or {}
    tongue = {
        "tongue_body": {
            "color": _norm_field(body_raw.get("color") or raw.get("color")),
            "shape": _norm_field(body_raw.get("shape") or raw.get("shape")),
            "petechiae": _norm_field(body_raw.get("petechiae")),
            "texture": _norm_field(body_raw.get("texture")),
            "deviation": _norm_field(body_raw.get("deviation")),
        },
        "coating": {
            "color": _norm_field(coat_raw.get("color") or raw.get("coating_color")),
            "thickness": _norm_field(coat_raw.get("thickness")),
            "quality": _norm_field(coat_raw.get("quality")),
            "corrosion": _norm_field(coat_raw.get("corrosion")),
            "peeling": _norm_field(coat_raw.get("peeling")),
        },
    }
    labels = raw.get("labels") or raw.get("tags") or []
    if not isinstance(labels, list):
        labels = []
    hints = raw.get("syndrome_hints") or raw.get("combined_syndrome") or []
    if isinstance(hints, str):
        hints = [hints]
    tongue["labels"] = [str(x) for x in labels if x]
    tongue["syndrome_hints"] = [str(x) for x in hints if x]
    return tongue


def _normalize_face(content: str) -> dict:
    """面色图输出 → FaceAnalysis 字段（可选，未提供面色图时为 None）。"""
    raw = normalize_vision_json(content)
    if not isinstance(raw, dict) or not raw:
        return {"complexion": "未识别", "lustre": "未识别", "note": ""}
    return {
        "complexion": _norm_field(raw.get("complexion")),
        "lustre": _norm_field(raw.get("lustre")),
        "note": _norm_field(raw.get("note"), ""),
    }


def analyze_tongue(
    image_ref: str,
    face_image: str | None = None,
    profile: dict | None = None,
    env_prefix: str = "GEO_VISION",
    fallback_prefix: str = "GEO_VISION",
) -> dict:
    """舌象健康特征分析：舌面照片 → 结构化 JSON（对齐 HB 契约 §3.5）。

    返回 dict：
      - mode="vision"       ：成功，含 engine/vision_model/tongue/face/combined_syndrome
      - mode="image_pending"：未配置视觉模型 / 未提供图片（fail-closed 不造假）
      - mode="image_error"  ：视觉调用失败（安全回退，如实标注）
    """
    if not image_ref:
        return {
            "engine": None, "mode": "image_pending", "provided": False,
            "note": "未提供舌象图片，无法分析。",
            "tongue": None, "face": None, "combined_syndrome": [],
        }

    base = os.environ.get(f"{env_prefix}_API_BASE") or os.environ.get(f"{fallback_prefix}_API_BASE", "")
    key = os.environ.get(f"{env_prefix}_API_KEY") or os.environ.get(f"{fallback_prefix}_API_KEY", "")
    model = os.environ.get(f"{env_prefix}_MODEL") or os.environ.get(f"{fallback_prefix}_MODEL", _ENGINE_NAME)
    if not (base and key):
        return {
            "engine": None, "mode": "image_pending", "provided": True,
            "note": f"图片已接收，但未配置视觉模型（{env_prefix}_API_BASE/KEY），"
                    "当前无法完成舌象结构化分析（fail-closed，不返回假数据）。",
            "tongue": None, "face": None, "combined_syndrome": [],
        }

    try:
        content = vision_chat_json(base, key, model, image_ref, TONGUE_VISION_PROMPT)
        tongue = _normalize_tongue(content)

        face = None
        if face_image:
            try:
                fcontent = vision_chat_json(base, key, model, face_image, FACE_VISION_PROMPT)
                face = _normalize_face(fcontent)
            except Exception:
                face = None  # 面色图为可选增强，失败不阻断舌象主结果

        # Layer2：标签 → 健康状态倾向（规则兜底 P1，协助单 T2）。
        # 视觉模型自报 hints 实测为万能牌（探针 2026-08-21：全图输出脾虚湿盛/湿热内蕴），
        # 不再采用；规则输出如实标 source=rule，健康舌 → 空（不硬编结论）。
        rule_hints = derive_syndrome_hints(tongue)
        tongue["syndrome_hints"] = rule_hints
        combined = [h["name"] for h in rule_hints]
        return {
            "engine": model,
            "mode": "vision",
            "vision_model": model,
            "tongue": tongue,
            "face": face,
            "combined_syndrome": combined,
            "note": "舌象健康特征分析（去医疗化，仅供健康评估参考，不构成诊断）。",
        }
    except Exception as e:  # 任意异常均安全回退（不造假）
        return {
            "engine": None, "mode": "image_error", "provided": True,
            "note": f"视觉模型解析失败（{e}），舌象分析不可用。",
            "tongue": None, "face": None, "combined_syndrome": [],
        }
