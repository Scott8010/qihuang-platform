"""
health-advisor · 请求/响应与内部规范模型

设计依据：
  - 《岐黄智脑Agent能力建设_开工文档》V1.0（2026-08-16 夜）第三章 接口定义（权威契约）
  - health-advisor_L1契约探查.md（2026-08-16 实测）：真实 L1(8601) 返回非结构化 JSON，
    本 schema 的 ConsultResponse 即「内部规范模型」，由 parser 层从 L1 原始 JSON
    解析/归一化而来（T3/T4 实为解析层，非直接字段映射）。

契约对齐要点（vs 开工文档 3.2）：
  - 请求：question / store_id / profile{age,sex,known_conditions,tongue,pulse} / mode / session_id
  - 响应：reply / ask_more / constitution / syndrome / formulas[] / suggestions[] (字符串数组)
          / recommendation_slot / report_id / disclaimer / partial / trace_id / session_id
  - 注：文档 3.2 响应示例写的是单数 formula，但 sizhen 返回多个方剂，本实现用复数 formulas[]（更贴合真实数据）。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# 外部接口（开工文档 3.2）
# ─────────────────────────────────────────────────────────────
class Profile(BaseModel):
    age: Optional[int] = Field(None, description="年龄")
    sex: Optional[str] = Field(None, description="性别（如 男/女）")
    known_conditions: List[str] = Field(default_factory=list, description="已知病史/慢病（如 胃炎）")
    tongue: Optional[str] = Field(None, description="舌象描述（S2 追问候选）")
    pulse: Optional[str] = Field(None, description="脉象描述（S2 追问候选，缺失将触发追问）")


class ConsultRequest(BaseModel):
    question: str = Field(..., description="用户主诉/咨询文本（如『最近失眠、乏力』）")
    store_id: Optional[str] = Field(None, description="门店 ID（颐掌柜侧传入，用于计量对账，见 T6/3.4）")
    profile: Optional[Profile] = Field(None, description="结构化档案（年龄/性别/病史/舌脉）")
    mode: str = Field("standard", description="standard | full（full 含报告生成，见 S7/T5）")
    session_id: Optional[str] = Field(None, description="多轮会话 ID（缺则新建）")


class Constitution(BaseModel):
    type: Optional[str] = None          # sizhen.constitution.type
    desc: Optional[str] = None          # sizhen.constitution.description
    score: Optional[float] = None       # sizhen.constitution.score


class Syndrome(BaseModel):
    name: Optional[str] = None          # ❌ L1 无直接字段，parser 规则兜底/LLM 提取
    desc: Optional[str] = None
    confidence: Optional[str] = None    # 如 chat.diagnosis.overall_confidence


class Formula(BaseModel):
    name: Optional[str] = None          # sizhen.medication.formulas[].formula
    items: List[str] = []               # .herbs
    note: Optional[str] = None          # .indication / .caution


class ConsultResponse(BaseModel):
    reply: str                          # S6 人话组装
    ask_more: Optional[str] = None      # S2 追问（缺舌脉时）
    constitution: Optional[Constitution] = None
    syndrome: Optional[Syndrome] = None
    formulas: List[Formula] = []        # 复数：sizhen 可返回多个方剂（文档示例写单数，以真实数据为准）
    suggestions: List[str] = []         # 调理建议，纯字符串数组（饮食/起居/运动/穴位/外治）
    recommendation_slot: Optional[str] = None  # 颐掌柜注入占位（跨项目，见 3.1/3.4）
    report_id: Optional[str] = None     # full 模式异步报告（S7/T5）
    partial: bool = False               # 信息不全降级
    disclaimer: str                     # S1 强注入免责
    trace_id: str
    session_id: str
