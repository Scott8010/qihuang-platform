"""活态化反馈闭环 — ORM 模型（KgFeedback）

知识反馈事件表：记录用户/专家对某个知识点的反馈（采纳/点赞/纠偏/缺口等）。
聚合层据此计算 confidence 增量并回写 8601；纠偏/缺口类事件走独立处理通道。
"""
from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Column, String, DateTime, Text, Index, Float, Integer,
)
from qihuang_platform.db.config import Base


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class KgFeedback(Base):
    """知识反馈事件。

    feedback_type 取值：
      adopt / like / dislike            → 普通用户信号（计入 confidence）
      expert_adopt / expert_reject      → 专家信号（计入 confidence，权重更高）
      expert_correction                 → 专家纠偏（改字段，走 /kg/api/correction）
      gap                               → 知识缺口/矛盾（走 /kg/api/gap）

    活态化 B（业务实证加权回路三）架构预留字段：
      source            → 反馈来源通道：'user'（默认，C端用户/专家）| 'business'
                         （预留：真实租户业务实证数据回灌，当前租户数据为仿真，暂不使用）
      business_weight   → 该反馈对应的业务实证权重（预留，回路三激活时由业务信号计算填充；
                         当前恒为 0.0，不参与 delta 计算）
    """
    __tablename__ = "kg_feedback"

    id = Column(String(36), primary_key=True, default=_uid)
    # kg_id: 正式图谱节点 UUID；也可为 'pending:{name}' 表示该知识点尚未完成图谱结构化
    kg_id = Column(String(100), nullable=False, index=True)
    target = Column(String(10), default="node")          # node | rel
    tenant_id = Column(String(36), index=True)
    user_id = Column(String(36))
    # 待补全节点的原始名称/类型，供管理员识别并补录
    entity_name = Column(String(100))
    entity_type = Column(String(20))

    feedback_type = Column(String(30), nullable=False, index=True)

    # 活态化 B 架构预留：反馈来源通道（user / business）
    source = Column(String(20), default="user", server_default="user", index=True)
    # 活态化 B 架构预留：业务实证权重（回路三激活前恒为 0.0）
    business_weight = Column(Float, default=0.0, server_default="0.0")

    # 纠偏类（expert_correction）：new_value 以 JSON 字符串存储
    field = Column(String(50))
    new_value = Column(Text)
    expert_id = Column(String(50))
    reason = Column(Text)

    # 缺口类（gap）
    kg_id_b = Column(String(36))
    conflict_type = Column(String(50))
    evidence = Column(Text)

    comment = Column(Text)

    aggregated_at = Column(DateTime)    # 已参与 confidence 聚合的时间
    processed_at = Column(DateTime)     # 已处理（纠偏/缺口）的时间
    created_at = Column(DateTime, default=_now, index=True)

    __table_args__ = (
        Index("idx_kg_fb_pending", "kg_id", "feedback_type", "aggregated_at"),
    )


class KgConfidenceSnapshot(Base):
    """活态化趋势采集快照（方案 2：变化曲线）。

    按固定周期（默认随活态调度每日一次）记录整个「活态生态」的瞬时健康度，
    形成时间序列，供成效月报绘制「越用越聪明」趋势线。

    数据来源：
      - 互考矩阵/盲点：8601 GET /kg/api/quiz（模型互考能力，已是真实运行数据）
      - 反馈/活态节点：8602 本地 KgFeedback 表
      - 活态节点平均置信度：对 KgFeedback 中出现的 kg_id 抽样调 8601 取 confidence

    设计要点：
      - 单表一行一快照，报告只需读历史即可渲染，不依赖运行时再连 8601。
      - 各字段 nullable，任一路采集失败不影响整行落库（容错）。
    """
    __tablename__ = "kg_confidence_snapshot"

    id = Column(String(36), primary_key=True, default=_uid)
    snapshot_at = Column(DateTime, default=_now, nullable=False, index=True)

    # —— 模型互考（活态化 A，真实运行数据）——
    quiz_total = Column(Integer, default=0)           # 累计互考题量
    deepseek_acc = Column(Float)                       # DeepSeek 正确率
    qwen_acc = Column(Float)                            # 通义千问 正确率
    glm_acc = Column(Float)                             # GLM-4 正确率
    kimi_acc = Column(Float)                            # Kimi 正确率
    model_trust_mean = Column(Float)                    # 4 模型均值（聚合层 model_trust 杠杆）
    blind_spot_count = Column(Integer, default=0)      # 知识盲点节点数
    # 盲点 Top15 明细（name+count JSON），供月报表格；为空则仅计数
    blind_spots_json = Column(Text)

    # —— 反馈闭环（活态化 P2）——
    living_node_count = Column(Integer, default=0)     # KgFeedback 中出现的不同 kg_id 数
    living_mean_confidence = Column(Float)             # 活态节点置信度抽样均值（无反馈则 null）
    total_feedback = Column(Integer, default=0)        # KgFeedback 总行数
