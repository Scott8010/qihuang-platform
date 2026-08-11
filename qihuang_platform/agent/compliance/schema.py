"""
L1 合规知识底座 · 标准条款 Schema

这是「横向知识库标准范式」的第一个实例（合规库）。每条 ComplianceClause 即一个
权威合规条款，与 8601 中医知识库的 Herb/Formula 标签**并列、隔离**——落地形态是
Neo4j 中的独立 label `ComplianceClause`（见 kb.Neo4jBackend）。

字段设计原则（呼应设计文档「标准 Schema」）：
  - kg_id        底座稳定 UUID 标识（与 8601 节点一致，uuid5 派生，写一次定终身）
  - clause_id    业务稳定键（人类可读，如 HC-A-001），便于回写溯源与跨系统对齐
  - source_ref   法条级溯源（如《广告法》第九条第(三)项），合规库红线：必须可考据
  - aligns_to    实体对齐 MVP 字段：关联的中医/领域实体关键词，桥接 8601 标签（见 kb.aligned_entities）
  - version/status 版本留痕 + 状态（active/deprecated），与岐黄自动演化「分道扬镳」
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

# 合规库命名空间（用于 uuid5 派生 kg_id，与中医库命名空间隔离）
_COMPLIANCE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "qihuang://compliance-clause")

# 严重度（与规则引擎一致）
SEVERITY_RED = "RED"      # 硬违规，拦截
SEVERITY_ORANGE = "ORANGE"  # 高风险，建议整改
SEVERITY_YELLOW = "YELLOW"  # 提示，人工确认

CATEGORY_LABELS = {
    "A": "夸大/绝对化用语",
    "B": "疗效/功效承诺",
    "C": "医疗用语越界",
    "D": "虚假描述/无依据数据",
    "E": "缺失禁忌/风险提示",
    "F": "敏感/违禁表述",
}


def make_kg_id(clause_id: str) -> str:
    """由 clause_id 确定性派生底座 UUID（写一次定终身，可复现）。"""
    return str(uuid.uuid5(_COMPLIANCE_NS, clause_id))


class ComplianceClause(BaseModel):
    """L1 合规知识底座单条条款。"""
    clause_id: str = Field(..., description="业务稳定键，如 HC-A-001")
    kg_id: str = Field(..., description="底座 UUID 稳定标识")
    title: str = Field(..., description="给人看的违规理由/要求")
    content: str = Field("", description="合规要求正文（权威表述）")
    source_ref: str = Field("", description="法条级溯源，如《广告法》第九条第(三)项")
    category: str = Field(..., description="A~F 六大类")
    category_label: str = Field("", description="类别中文名")
    severity: str = Field(SEVERITY_ORANGE, description="RED/ORANGE/YELLOW")
    effective_action: str = Field("advise", description="block/advise")
    keywords: list[str] = Field(default_factory=list, description="检索触发词（由规则字面量派生）")
    confidence: float = Field(0.9, description="该条款被判违的基准置信度")
    version: int = Field(1, description="版本号（版本留痕）")
    effective_date: str = Field("2026-01-01", description="生效日期")
    status: str = Field("active", description="active/deprecated")
    aligns_to: list[str] = Field(
        default_factory=list,
        description="实体对齐 MVP：关联的中医/领域实体关键词，桥接 8601 标签",
    )

    @classmethod
    def build(
        cls,
        clause_id: str,
        title: str,
        content: str = "",
        source_ref: str = "",
        category: str = "A",
        severity: str = SEVERITY_ORANGE,
        effective_action: str = "advise",
        keywords: Optional[list[str]] = None,
        confidence: float = 0.9,
        aligns_to: Optional[list[str]] = None,
    ) -> "ComplianceClause":
        return cls(
            clause_id=clause_id,
            kg_id=make_kg_id(clause_id),
            title=title,
            content=content,
            source_ref=source_ref or CATEGORY_LABELS.get(category, ""),
            category=category,
            category_label=CATEGORY_LABELS.get(category, ""),
            severity=severity,
            effective_action=effective_action,
            keywords=keywords or [],
            confidence=confidence,
            aligns_to=aligns_to or [],
        )
