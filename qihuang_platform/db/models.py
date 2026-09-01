"""
岐黄智脑商业化平台 - 数据库ORM模型（24张表，4域）
1. 账号权限域: tenant, org, user, role, permission, user_role, role_permission (7表)
2. 计费计量域: plan, subscription, api_key, call_log, bill, audit_log (6表)
3. 业务数据域: med_case, med_report, health_profile, health_assessment, health_plan,
                health_event, edu_coach_session, edu_exam_record, upload_file (9表)
4. 内容管控域: sensitive_word, kg_review_item, kg_version (3表) [计24表]
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from qihuang_platform.db.config import Base


def _uid():
    return str(uuid.uuid4())

def _now():
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════
# 1. 账号权限域 (7表)
# ═══════════════════════════════════════════════════════════

class Tenant(Base):
    """租户表"""
    __tablename__ = "tenant"
    id = Column(String(36), primary_key=True, default=_uid)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200))
    scene = Column(String(50), default="MED")  # MED/EDU/RETAIL/HQ（业务场景，默认 MED）
    status = Column(String(20), default="active")  # active/suspended/closed
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    # 2026-08-29 #596 机构ID可读化：可读机构代号（如 JG0007 / 金不换拼音 jbh），与 uuid 主键解耦
    code = Column(String(32), unique=True, nullable=True, index=True)


class Org(Base):
    """机构表"""
    __tablename__ = "org"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    parent_id = Column(String(36), ForeignKey("org.id"), nullable=True)
    org_type = Column(String(50), default="branch")  # root/branch/dept
    status = Column(String(20), default="active")
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)


class User(Base):
    """用户表"""
    __tablename__ = "user"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    org_id = Column(String(36), ForeignKey("org.id"))
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255))  # bcrypt
    display_name = Column(String(200))
    phone = Column(String(20), index=True)
    wechat_openid = Column(String(100), index=True)
    email = Column(String(200))
    status = Column(String(20), default="active")
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    roles = relationship("Role", secondary="user_role", back_populates="users")


class Role(Base):
    """角色表"""
    __tablename__ = "role"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    org_id = Column(String(36), ForeignKey("org.id"), nullable=True, index=True)  # 机构级角色标记（为空=平台级角色）
    name = Column(String(100), nullable=False)
    display_name = Column(String(200))
    description = Column(Text)
    is_system = Column(Boolean, default=False)  # 系统预置角色不可删
    created_at = Column(DateTime, default=_now)

    users = relationship("User", secondary="user_role", back_populates="roles")
    permissions = relationship("Permission", secondary="role_permission")


class Permission(Base):
    """权限表"""
    __tablename__ = "permission"
    id = Column(String(36), primary_key=True, default=_uid)
    code = Column(String(100), unique=True, nullable=False)  # menu:core:diagnose
    name = Column(String(200))
    perm_type = Column(String(20), default="api")  # menu/api/data
    resource = Column(String(200))  # 资源路径
    scene = Column(String(50), default="all")  # all/health/medical/edu
    created_at = Column(DateTime, default=_now)


class UserRole(Base):
    """用户-角色关联表"""
    __tablename__ = "user_role"
    user_id = Column(String(36), ForeignKey("user.id"), primary_key=True)
    role_id = Column(String(36), ForeignKey("role.id"), primary_key=True)
    org_id = Column(String(36), ForeignKey("org.id"))  # 机构级角色
    created_at = Column(DateTime, default=_now)


class RolePermission(Base):
    """角色-权限关联表"""
    __tablename__ = "role_permission"
    role_id = Column(String(36), ForeignKey("role.id"), primary_key=True)
    perm_id = Column(String(36), ForeignKey("permission.id"), primary_key=True)
    data_scope = Column(String(20), default="SELF")  # SELF/ORG/TENANT
    created_at = Column(DateTime, default=_now)


# ═══════════════════════════════════════════════════════════
# 2. 计费计量域 (6表)
# ═══════════════════════════════════════════════════════════

class Plan(Base):
    """套餐表"""
    __tablename__ = "plan"
    id = Column(String(36), primary_key=True, default=_uid)
    plan_name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), default="")
    scene_type = Column(String(50), default="health")
    qps = Column(Integer, default=10)
    month_calls = Column(Integer, default=2000)
    month_tokens = Column(Integer, default=100000)
    price_cents = Column(Integer, default=0)  # 分
    features_json = Column(JSON, default=dict)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=_now)


class Subscription(Base):
    """订阅表"""
    __tablename__ = "subscription"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    plan_id = Column(String(36), ForeignKey("plan.id"), nullable=False)
    status = Column(String(20), default="active")  # active/expired/cancelled
    start_date = Column(DateTime, default=_now)
    end_date = Column(DateTime)
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class ApiKey(Base):
    """API Key表"""
    __tablename__ = "api_key"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    app_key = Column(String(100), unique=True, nullable=False)
    app_secret = Column(String(255), nullable=False)  # 加密存储
    plan_id = Column(String(36), ForeignKey("plan.id"))
    status = Column(String(20), default="active")
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)
    last_used_at = Column(DateTime)


class CallLog(Base):
    """调用日志表"""
    __tablename__ = "call_log"
    id = Column(String(36), primary_key=True, default=_uid)
    trace_id = Column(String(50), index=True)
    endpoint = Column(String(200), index=True)
    method = Column(String(10))
    tenant_id = Column(String(36), ForeignKey("tenant.id"), index=True)
    user_id = Column(String(36), index=True)
    app_key = Column(String(100), index=True)
    org_id = Column(String(36))
    status_code = Column(Integer)
    latency_ms = Column(Float)
    tokens_used = Column(Integer, default=0)
    cost_cents = Column(Float, default=0.0)
    ip = Column(String(50))
    user_agent = Column(Text)
    is_3d = Column(Boolean, default=False)  # 3D模块独立计量
    cdn_traffic_bytes = Column(Integer, default=0)
    timestamp = Column(DateTime, default=_now, index=True)


class Bill(Base):
    """账单表"""
    __tablename__ = "bill"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    bill_period = Column(String(7), nullable=False)  # YYYY-MM
    total_calls = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost_cents = Column(Integer, default=0)
    status = Column(String(20), default="DRAFT")  # DRAFT/ISSUED/PAID/OVERDUE
    issued_at = Column(DateTime)
    paid_at = Column(DateTime)
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "bill_period", name="uq_tenant_period"),
    )


class Order(Base):
    """订单表（结算中心 #B 方案：所有收费动作先落订单再处理）

    订单类型 order_type:
      - recharge  充值包购买（积分 +N，PAID）
      - addon     agent 单加订阅（积分 -N，PAID）
      - usage     用量月度快照单（积分 -N，PAID，结算时生成）
      - plan      套餐变更/升级（预留）
    状态 status: PENDING → PAID（成功）/ CANCELLED（失败/取消）
    billed: 是否已并入月度结算单（阶段⑤结算聚合消费）
    """
    __tablename__ = "orders"
    id = Column(String(36), primary_key=True, default=_uid)
    order_no = Column(String(64), nullable=False, index=True)  # 订单号 ORD+时间戳+随机
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    order_type = Column(String(20), nullable=False, index=True)
    item_key = Column(String(50), default="")  # 包key / agent_key / usage:monthly
    item_label = Column(String(100), default="")  # 展示名
    amount_cents = Column(Integer, default=0)  # 应付金额（分）
    credits = Column(Integer, default=0)  # 积分变动：充值=+N，加购/用量=-N
    status = Column(String(20), default="PENDING")  # PENDING/PAID/CANCELLED
    billed = Column(Boolean, default=False)  # 是否已并入结算单
    period_month = Column(String(7), index=True)  # 归属月份 YYYY-MM（结算聚合）
    paid_at = Column(DateTime)
    extra = Column(JSON)
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("order_no", name="uq_orders_order_no"),
    )


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_log"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), index=True)
    user_id = Column(String(36), index=True)
    action = Column(String(100))  # LOGIN/LOGOUT/CREATE_USER/GRANT_PERM/...
    target_type = Column(String(50))  # USER/ROLE/TENANT/...
    target_id = Column(String(36))
    detail = Column(JSON)
    ip = Column(String(50))
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)


# ═══════════════════════════════════════════════════════════
# 3. 业务数据域 (9表)
# ═══════════════════════════════════════════════════════════

class MedCase(Base):
    """医案表"""
    __tablename__ = "med_case"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    doctor_id = Column(String(36), ForeignKey("user.id"))
    patient_alias = Column(String(50))  # 患者代号，不存真实姓名
    diagnoses = Column(JSON)  # 诊断信息
    prescriptions = Column(JSON)  # 处方
    notes = Column(Text)
    idempotency_key = Column(String(100), index=True)  # 24h去重
    created_at = Column(DateTime, default=_now)


class MedReport(Base):
    """医疗报告表"""
    __tablename__ = "med_report"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    case_id = Column(String(36), ForeignKey("med_case.id"))
    report_type = Column(String(50))  # diagnosed/prescription_review/synthesis
    content = Column(JSON)
    disclaimer = Column(Text)  # 免责声明
    pdf_path = Column(String(500))
    signature_url = Column(String(500))
    override_reason = Column(Text)  # 医师覆盖安全审查警示的理由
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=_now)


class HealthProfile(Base):
    """健康档案表"""
    __tablename__ = "health_profile"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    name_alias = Column(String(50))
    gender = Column(String(10))
    birth_year = Column(Integer)
    height_cm = Column(Float)
    weight_kg = Column(Float)
    device_json = Column(JSON)  # 预留舌面图像数据
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class HealthAssessment(Base):
    """体质辨识评估表"""
    __tablename__ = "health_assessment"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    profile_id = Column(String(36), ForeignKey("health_profile.id"))
    user_id = Column(String(36), ForeignKey("user.id"), index=True)
    constitution_type = Column(String(100))  # 平和质/气虚质/...
    scores = Column(JSON)  # 各体质评分
    raw_answers = Column(JSON)  # 原始问卷答案
    ai_analysis = Column(Text)
    created_at = Column(DateTime, default=_now)


class HealthPlan(Base):
    """调理方案表"""
    __tablename__ = "health_plan"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    profile_id = Column(String(36), ForeignKey("health_profile.id"))
    user_id = Column(String(36), ForeignKey("user.id"), index=True)
    assessment_id = Column(String(36), ForeignKey("health_assessment.id"))
    diet_plan = Column(JSON)  # 饮食建议
    lifestyle_plan = Column(JSON)  # 生活方式建议
    acupoint_plan = Column(JSON)  # 穴位保健
    product_recommendations = Column(JSON)  # 商品推荐
    disclaimer = Column(Text)
    created_at = Column(DateTime, default=_now)


class HealthEvent(Base):
    """健康事件表"""
    __tablename__ = "health_event"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user.id"), index=True)
    event_type = Column(String(50))  # assessment/plan_generated/symptom_log/...
    event_data = Column(JSON)
    created_at = Column(DateTime, default=_now)


class EduCoachSession(Base):
    """AI陪练会话表"""
    __tablename__ = "edu_coach_session"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user.id"), index=True)
    topic = Column(String(200))
    messages = Column(JSON)  # 对话历史
    evaluation = Column(String(20))  # PERFECT/GOOD/PARTIAL/WRONG
    score = Column(Float)
    feedback = Column(Text)
    reviewed = Column(Boolean, default=False)
    reviewer_id = Column(String(36))
    created_at = Column(DateTime, default=_now)


class StoreCoachSession(Base):
    """门店话术对练会话表（store-coach 能力，独立于 edu_coach_session 不混表）

    场景：门店店员话术训练——AI 扮演顾客角色，店员练习接待/推荐/异议处理/促成话术，
    按话术四维评分（完整性/专业性/亲和力/合规性），输出过 compliance 审核。
    tenant_id 非空（行级隔离），user_id 可空（API Key 调用时无 user 上下文）。
    """
    __tablename__ = "store_coach_session"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), index=True)  # 不强制 FK：API Key 调用无 user 上下文
    scene = Column(String(30), default="reception")  # reception/recommend/objection/close
    topic = Column(String(200))
    script_id = Column(String(36), index=True)     # 话术模板（DbTemplate kind=script）
    product_id = Column(String(36), index=True)    # 产品模板（DbTemplate kind=product）
    project_id = Column(String(36), index=True)    # 项目模板（DbTemplate kind=project）
    customer_profile = Column(String(200))         # 顾客画像（默认内置，可租户传入）
    material_text = Column(Text)                   # 课件文本内容（V2 店务培训：课件的文本切片，引擎据此出题）
    material_ref = Column(String(100), index=True) # 课件引用ID（HB Course/Lesson 或 DbTemplate 关联）
    passing_score = Column(Float, default=60.0)    # 合格线（总分 ≥ 此值=合格 qualified）
    messages = Column(JSON)                        # 对话历史
    evaluation = Column(JSON)                      # 四维话术评分 {"completeness":..,"professional":..,"affinity":..,"compliance":..}
    score = Column(Float)                          # 加权总分 0-100
    feedback = Column(Text)                        # 改进建议
    compliance_ok = Column(Boolean, default=True)  # 输出是否过 compliance 审核
    compliance_hits = Column(JSON)                 # 违规命中明细（标红依据）
    created_at = Column(DateTime, default=_now)


class EduExamRecord(Base):
    """测评记录表"""
    __tablename__ = "edu_exam_record"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user.id"), index=True)
    exam_config = Column(JSON)
    answers = Column(JSON)
    score = Column(Float)
    max_score = Column(Float)
    idempotency_key = Column(String(100), index=True)
    created_at = Column(DateTime, default=_now)


class UploadFile(Base):
    """上传文件表"""
    __tablename__ = "upload_file"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user.id"))
    file_name = Column(String(500))
    file_type = Column(String(50))  # image/pdf/doc/...
    file_size = Column(Integer)
    cos_key = Column(String(500))
    cos_url = Column(String(1000))
    signature_url = Column(String(1000))  # 临时签名URL
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=_now)


# ═══════════════════════════════════════════════════════════
# 4. 内容管控域 (3表)
# ═══════════════════════════════════════════════════════════

class SensitiveWord(Base):
    """敏感词表"""
    __tablename__ = "sensitive_word"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    scene = Column(String(50), nullable=False)  # HEALTH/MED/EDU/GLOBAL
    word = Column(String(200), nullable=False)
    level = Column(String(20), default="warn")  # warn/block
    replacement = Column(String(200))
    created_at = Column(DateTime, default=_now)


class KgReviewItem(Base):
    """知识图谱审核项表"""
    __tablename__ = "kg_review_item"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    item_type = Column(String(50))  # entity/relation/attribute
    item_id_in_kg = Column(String(100))  # Neo4j中的ID
    content = Column(JSON)
    confidence = Column(Float)  # 0.0-1.0
    status = Column(String(20), default="PENDING")  # PENDING/APPROVED/REJECTED
    reviewer_id = Column(String(36), ForeignKey("user.id"))
    reviewer_role = Column(String(50))  # DZ(大张/临床)/XZ(小张/典籍)
    review_note = Column(Text)
    created_at = Column(DateTime, default=_now)
    reviewed_at = Column(DateTime)


class KgVersion(Base):
    """知识图谱版本表"""
    __tablename__ = "kg_version"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    version_tag = Column(String(50), nullable=False)
    description = Column(Text)
    diff_summary = Column(JSON)  # 版本差异摘要
    snapshot_backup = Column(Text)  # 备份路径
    status = Column(String(20), default="active")  # active/rolled_back
    rolled_back_from = Column(String(36))
    created_by = Column(String(36), ForeignKey("user.id"))
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        Index("idx_kg_version_tenant_tag", "tenant_id", "version_tag"),
    )


# ═══════════════════════════════════════════════════════════
# 初始化预置角色与权限
# ═══════════════════════════════════════════════════════════

class AgentDef(Base):
    """Agent 能力定义表 — Agent 中台的资源池（注册表落库）。

    与套餐/密钥/计量同级，是一等可分配资源：
    - 部署期注册（register_agent），运营态热插拔（启停/编辑，控制端可读写）；
    - 套餐通过 features_json.agents 组合若干 agent_key 形成「专家团」。
    """
    __tablename__ = "agent_def"
    id = Column(String(36), primary_key=True, default=_uid)
    agent_key = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(50), default="business_embedded")  # business_embedded / conversational
    engine = Column(String(100))          # 驱动引擎标识，如 hb-compliance-guard
    category = Column(String(50), default="general")  # 分组（中台面板用）
    router_prefix = Column(String(200))   # 挂载路径前缀
    capabilities = Column(JSON, default=list)  # 能力点列表，如 ["scan","feedback","dashboard"]
    status = Column(String(20), default="active")  # active / inactive
    desc = Column(Text)
    features_json = Column(JSON, default=dict)  # 扩展元数据
    uses_llm = Column(Boolean, default=True)    # 是否调用大模型（False=纯规则引擎，按固定积分/次计价，#474）
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class Wallet(Base):
    """计费中台积分钱包（#474）— 通用余额池（tenant 单桶，不绑 agent）。

    两层清零：
      - base_credits：基本包赠送积分（套餐档位），按自然月清零（period_month 锚）
      - addon_credits：叠加包充值积分，永久有效
    调用扣费顺序：先 base_credits，不足再扣 addon_credits。
    """
    __tablename__ = "wallet"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), unique=True, nullable=False, index=True)
    base_credits = Column(Integer, default=0)
    addon_credits = Column(Integer, default=0)
    period_month = Column(String(7), default=lambda: datetime.now(timezone.utc).strftime("%Y-%m"))
    total_bought = Column(Integer, default=0)   # 累计充值（展示用）
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AgentAddonSubscription(Base):
    """单加 agent 月度订阅计费（B3 落地点）— 在套餐 agents 之外精准叠加的能力，按 ¥59/¥99 月度计费。

    - fee_cents：月费（分）文本 5900 / 多模态 9900（老板 2026-08-25 拍板）。
    - 开通即在 set_tenant_agent_addons 落一条 active 记录 + 首月从积分池扣费（先赠后充）；
      后续月度由计费中台定时任务续扣（本期先落地记录 + 首月扣费，递归续扣为后续项）。
    """
    __tablename__ = "agent_addon_subscription"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    agent_key = Column(String(100), nullable=False)
    fee_cents = Column(Integer, default=0)
    cycle_months = Column(Integer, default=1)
    status = Column(String(20), default="active")  # active / cancelled
    start_date = Column(DateTime, default=_now)
    next_charge_at = Column(DateTime, default=_now)
    created_at = Column(DateTime, default=_now)


# ═══════════════════════════════════════════════════
# 5. 活态化业务实证（回路三）& 多租户能力中心（二期）域
# ═══════════════════════════════════════════════════

class ConsultAttribution(Base):
    """活态化 B · 回路三（业务实证加权）归因表

    consult 成功路径（非 partial = 弱采纳）时，把返回的实体（方剂/证候）名称
    经 kg_client.resolve 解析成 kg_id 落库，作为「业务实证使用信号」的数据源。
    fetch_business_usage 据此聚合某 kg_id 在窗口内的被引用次数 → 实证权重。
    该表即「8602 consult 引用日志」：零侵入、best-effort、不阻断主响应。
    """
    __tablename__ = "consult_attribution"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=True, index=True)
    store_id = Column(String(36), index=True)
    kg_id = Column(String(100), nullable=False, index=True)
    entity_name = Column(String(100))                 # 解析前的原名称（方剂/证候名）
    entity_type = Column(String(20), default="formula")  # formula / herb / syndrome
    adopted = Column(Boolean, default=True)            # 非 partial 视为弱采纳
    consulted_at = Column(DateTime, default=_now, index=True)
    trace_id = Column(String(32))
    session_id = Column(String(32))


class StoreQuestionnaire(Base):
    """门店问卷 — 门店采集用的结构化问卷模板（如体质/症状采集表）。"""
    __tablename__ = "store_questionnaire"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=False, index=True)
    org_id = Column(String(36), ForeignKey("org.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    schema_json = Column(JSON, default=dict)   # 问卷题目结构（字段名/类型/选项）
    status = Column(String(20), default="active")  # active / draft / archived
    created_by = Column(String(36))
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class DbTemplate(Base):
    """能力中心模板 — 平台/机构维护的知识/数据模板（全模型，可自建编辑/克隆/同步提交）。"""
    __tablename__ = "db_template"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(50), default="herb")  # herb/formula/syndrome/... 模板类型
    content_json = Column(JSON, default=dict)  # 模板内容（字段结构 + 默认值）
    current_version = Column(String(50), default="v1")
    parent_template_id = Column(String(36), nullable=True, index=True)  # 克隆血缘：源模板 id（平台↔机构）
    created_by = Column(String(36))
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    __table_args__ = (
        Index("idx_db_template_tenant_kind", "tenant_id", "kind"),
    )


class TemplateOwnership(Base):
    """模板归属 — 平台↔机构 的模板归属与可见性关系。"""
    __tablename__ = "template_ownership"
    id = Column(String(36), primary_key=True, default=_uid)
    template_id = Column(String(36), ForeignKey("db_template.id"), nullable=False, index=True)
    owner_tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=True, index=True)
    owner_org_id = Column(String(36), ForeignKey("org.id"), nullable=True, index=True)
    visibility = Column(String(20), default="private")  # platform / public / private
    source = Column(String(20), default="platform")     # platform / clone / self
    created_at = Column(DateTime, default=_now)
    __table_args__ = (
        Index("idx_tpl_owner_org", "owner_org_id", "template_id"),
    )


class TemplateReviewSubmission(Base):
    """模板审核提交 — 机构自建模板提交平台审核（强下架依据）。状态复用 PENDING/APPROVED/REJECTED。"""
    __tablename__ = "template_review_submission"
    id = Column(String(36), primary_key=True, default=_uid)
    template_id = Column(String(36), ForeignKey("db_template.id"), nullable=False, index=True)
    submitter_tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=True, index=True)
    submitter_org_id = Column(String(36), ForeignKey("org.id"), nullable=True, index=True)
    status = Column(String(20), default="PENDING")  # PENDING / APPROVED / REJECTED
    reviewer_id = Column(String(36))
    review_note = Column(Text)
    submitted_at = Column(DateTime, default=_now)
    reviewed_at = Column(DateTime)


class TemplateVersion(Base):
    """模板版本 — 每次编辑/提交生成版本快照，支撑平台↔机构模板归属全模型。"""
    __tablename__ = "template_version"
    id = Column(String(36), primary_key=True, default=_uid)
    template_id = Column(String(36), ForeignKey("db_template.id"), nullable=False, index=True)
    version_tag = Column(String(50), nullable=False)
    snapshot_json = Column(JSON, default=dict)
    created_by = Column(String(36))
    created_at = Column(DateTime, default=_now)
    __table_args__ = (
        Index("idx_tplver_tpl_tag", "template_id", "version_tag"),
    )


class CrossTenantSyncLog(Base):
    """跨租户同步审计日志 — 平台→机构下发 / 机构→平台贡献，每次同步留痕（支撑 Stage C 运营）。"""
    __tablename__ = "cross_tenant_sync_log"
    id = Column(String(36), primary_key=True, default=_uid)
    action = Column(String(20), nullable=False)          # push（平台→机构）/ contribute（机构→平台）
    source_template_id = Column(String(36), nullable=False, index=True)
    target_template_id = Column(String(36), index=True)  # 同步生成的新模板 id
    from_tenant_id = Column(String(36), index=True)
    from_org_id = Column(String(36), index=True)
    to_tenant_id = Column(String(36), index=True)
    to_org_id = Column(String(36), index=True)
    created_by = Column(String(36))
    created_at = Column(DateTime, default=_now)


class PluginDisableRequest(Base):
    """关插件申请 — 决策①=B：机构长可申请关插件，平台审核（强治理红线）。"""
    __tablename__ = "plugin_disable_request"
    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), ForeignKey("tenant.id"), nullable=True, index=True)
    org_id = Column(String(36), ForeignKey("org.id"), nullable=True, index=True)
    plugin_key = Column(String(50), nullable=False)      # health-advisor / store-coach / ...
    reason = Column(Text)
    submitter_id = Column(String(36))                    # 申请人（机构长/机构管理员）
    status = Column(String(20), default="PENDING")       # PENDING / APPROVED / REJECTED
    reviewer_id = Column(String(36))
    review_note = Column(Text)
    submitted_at = Column(DateTime, default=_now)
    reviewed_at = Column(DateTime)


PRESET_ROLES = [
    {"name": "super_admin", "display_name": "超级管理员", "description": "平台全局管理"},
    {"name": "tenant_admin", "display_name": "租户管理员", "description": "租户级管理"},
    {"name": "org_admin", "display_name": "机构管理员", "description": "机构级管理"},
    {"name": "doctor", "display_name": "医师", "description": "医疗场景医师"},
    {"name": "teacher", "display_name": "教师", "description": "培训场景教师"},
    {"name": "student", "display_name": "学员", "description": "培训场景学员"},
    {"name": "health_user", "display_name": "健康用户", "description": "大健康C端用户"},
    {"name": "edu_researcher", "display_name": "教研专家", "description": "大张/小张审核角色"},
    {"name": "api_consumer", "display_name": "API调用方", "description": "开放平台调用方"},
]

PRESET_PERMISSIONS = [
    # Admin权限
    {"code": "admin:tenant:manage", "name": "租户管理", "perm_type": "api", "scene": "all"},
    {"code": "admin:org:manage", "name": "机构管理", "perm_type": "api", "scene": "all"},
    {"code": "admin:user:manage", "name": "用户管理", "perm_type": "api", "scene": "all"},
    {"code": "admin:billing:view", "name": "账单查看", "perm_type": "api", "scene": "all"},
    {"code": "admin:monitor:view", "name": "监控查看", "perm_type": "api", "scene": "all"},
    {"code": "admin:audit:view", "name": "审计查看", "perm_type": "api", "scene": "all"},
    # Core权限
    {"code": "core:diagnose", "name": "辨证推理", "perm_type": "api", "scene": "medical"},
    {"code": "core:prescription:review", "name": "处方审查", "perm_type": "api", "scene": "medical"},
    {"code": "core:graph:query", "name": "图谱查询", "perm_type": "api", "scene": "all"},
    {"code": "core:agent:chat", "name": "智能对话", "perm_type": "api", "scene": "all"},
    {"code": "core:literature:search", "name": "文献检索", "perm_type": "api", "scene": "all"},
    # Health权限
    {"code": "health:constitution:assess", "name": "体质辨识", "perm_type": "api", "scene": "health"},
    {"code": "health:plan:generate", "name": "方案生成", "perm_type": "api", "scene": "health"},
    # Edu权限
    {"code": "edu:coach:session", "name": "AI陪练", "perm_type": "api", "scene": "edu"},
    {"code": "edu:exam:manage", "name": "测评管理", "perm_type": "api", "scene": "edu"},
    {"code": "edu:progress:view", "name": "学情查看", "perm_type": "api", "scene": "edu"},
    # 增值模块
    {"code": "module:3d", "name": "岐黄三境3D", "perm_type": "api", "scene": "all"},
]


def seed_preset_data(session):
    """初始化预置角色和权限"""
    from qihuang_platform.db.models import Role, Permission, RolePermission, Tenant, Org
    from sqlalchemy import inspect as _sa_inspect, text as _sa_text
    # 2026-08-29 #596 迁移：生产库 tenant 为既有表，create_all 不会自动加列，
    # 启动时检测并 ALTER 补 code 列（PostgreSQL/SQLite 通用）。
    try:
        _cols = [c["name"] for c in _sa_inspect(session.bind).get_columns("tenant")]
        if "code" not in _cols:
            session.execute(_sa_text("ALTER TABLE tenant ADD COLUMN code VARCHAR(32)"))
            session.flush()
    except Exception as _e:  # 极端情况下不影响其余种子
        print(f"[migrate] tenant.code 列迁移跳过: {_e}")

    # 创建默认租户
    if not session.query(Tenant).filter_by(name="default").first():
        t = Tenant(id="tenant_default", name="default", display_name="默认租户", scene="MED", code="DEFAULT")
        session.add(t)
        session.flush()

    # 创建默认机构（与默认租户配对）。gateway 在用户 org_id 缺失时回退为
    # "org_default"，若不 seed，template_ownership / store_questionnaire 等 org_id
    # 外键在 PostgreSQL（严格 FK 约束）下插入会失败；SQLite 则因不强制 FK 而掩盖。
    if not session.query(Org).filter_by(id="org_default").first():
        org = Org(id="org_default", tenant_id="tenant_default",
                  name="default org", org_type="root", status="active")
        session.add(org)
        session.flush()

    # 2026-08-29 #596 机构ID可读化：存量租户 code 为空时补可读代号（JG0001 递增，跳过已占用）
    _occupied = {c for (c,) in session.query(Tenant.code).filter(Tenant.code.isnot(None)).all()}
    _seq = 1
    for _t in session.query(Tenant).filter_by(code=None).order_by(Tenant.created_at).all():
        while f"JG{_seq:04d}" in _occupied:
            _seq += 1
        _t.code = f"JG{_seq:04d}"
        _occupied.add(_t.code)
        _seq += 1
    session.flush()

    # 创建预置权限
    perm_map = {}
    for pdata in PRESET_PERMISSIONS:
        existing = session.query(Permission).filter_by(code=pdata["code"]).first()
        if not existing:
            p = Permission(id=_uid(), **pdata)
            session.add(p)
            session.flush()
            perm_map[p.code] = p
        else:
            perm_map[existing.code] = existing

    # 创建预置角色
    for rdata in PRESET_ROLES:
        existing = session.query(Role).filter_by(name=rdata["name"], tenant_id="tenant_default").first()
        if existing:
            continue
        role = Role(
            id=_uid(), tenant_id="tenant_default",
            name=rdata["name"], display_name=rdata["display_name"],
            description=rdata["description"], is_system=True,
        )
        session.add(role)
        session.flush()

        # 超级管理员拥有所有权限
        if rdata["name"] == "super_admin":
            for p in perm_map.values():
                session.add(RolePermission(
                    role_id=role.id, perm_id=p.id, data_scope="TENANT"
                ))
        # 租户管理员
        elif rdata["name"] == "tenant_admin":
            admin_codes = [c for c in perm_map if c.startswith("admin:")]
            for c in admin_codes:
                session.add(RolePermission(
                    role_id=role.id, perm_id=perm_map[c].id, data_scope="TENANT"
                ))
        # 健康用户
        elif rdata["name"] == "health_user":
            health_codes = ["core:graph:query", "core:agent:chat", "core:literature:search",
                           "health:constitution:assess", "health:plan:generate", "module:3d"]
            for c in health_codes:
                if c in perm_map:
                    session.add(RolePermission(
                        role_id=role.id, perm_id=perm_map[c].id, data_scope="SELF"
                    ))
        # 医师
        elif rdata["name"] == "doctor":
            med_codes = ["core:diagnose", "core:prescription:review", "core:graph:query",
                        "core:agent:chat", "core:literature:search"]
            for c in med_codes:
                if c in perm_map:
                    session.add(RolePermission(
                        role_id=role.id, perm_id=perm_map[c].id, data_scope="ORG"
                    ))
        # 学员
        elif rdata["name"] == "student":
            edu_codes = ["core:graph:query", "core:agent:chat", "edu:coach:session"]
            for c in edu_codes:
                if c in perm_map:
                    session.add(RolePermission(
                        role_id=role.id, perm_id=perm_map[c].id, data_scope="SELF"
                    ))
        # API调用方
        elif rdata["name"] == "api_consumer":
            open_codes = ["core:graph:query", "core:literature:search"]
            for c in open_codes:
                if c in perm_map:
                    session.add(RolePermission(
                        role_id=role.id, perm_id=perm_map[c].id, data_scope="TENANT"
                    ))

    session.commit()
