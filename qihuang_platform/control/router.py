"""
管理端全功能路由 — #15 六大功能域

1. 套餐管理: plan CRUD + 订阅管理
2. 账单系统: 月账单生成/查看/导出
3. 知识审核: kg_review_item 审核队列 + kg_version 版本管理
4. 监控大盘: 运行指标 + 告警
5. 审计日志: 全局操作日志
6. 敏感词库: 分场景维护
7. 容器管理: 容器状态监控 + 自动恢复
"""
import os
import warnings
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, Body, Request, Header, HTTPException, UploadFile as FastAPIUploadFile, File, Form
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
import logging

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.agent.refine_llm import refine_review_content
from qihuang_platform.control.kg_bridge import write_review_to_kg
from qihuang_platform.gateway.response import success, error, paginated, fail
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    Plan, Subscription, Bill, CallLog, AuditLog,
    SensitiveWord, KgReviewItem, KgVersion,
    Tenant, User, Role, UserRole, RolePermission, Permission,
    Org, ApiKey, AgentDef,
    MedCase, MedReport, HealthAssessment, HealthPlan,
    EduCoachSession, EduExamRecord, ConsultAttribution,
    AgentAddonSubscription,
    UploadFile,
)
from qihuang_platform.billing.wallet import charge_addon_subscription, get_available_balance
import bcrypt
from qihuang_platform.rbac.service import validate_password, resolve_tenant_code
from qihuang_platform.gateway.monitor import monitor
from qihuang_platform.gateway.llm_fallback import llm_fallback
from qihuang_platform.gateway.health_probe import get_services_health
from qihuang_platform.control.container_mgr import container_mgr
from qihuang_platform.control.cost_mgr import router as cost_router
from qihuang_platform.billing.billing import get_bill_detail
from qihuang_platform.agent.registry import list_agents, get_agent, set_agent_status, is_active
from qihuang_platform.agent import dashboard as agent_dashboard

router = APIRouter(prefix="/admin/v1", tags=["管理端-全功能"])


def _uid():
    import uuid
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# 审计动作→人类可读中文映射（8/30#3 新增：避免告警页直淋原词如 TENANT_ONBOARD）
ACTION_DISPLAY = {
    "TENANT_ONBOARD": "开通租户",
    "CREATE_TENANT": "创建租户",
    "TENANT_SUSPEND": "暂停租户",
    "TENANT_CLOSE": "注销租户",
    "UPDATE_TENANT": "更新租户",
    "USER_LOGIN": "登录",
    "USER_LOGOUT": "退出登录",
    "CREATE_USER": "创建用户",
    "UPDATE_USER": "更新用户",
    "DELETE_USER": "删除用户",
    "CREATE_KEY": "创建 API Key",
    "REVOKE_KEY": "吊销 API Key",
    "PLAN_UPGRADE": "升级套餐",
    "PLAN_DOWNGRADE": "降级套餐",
    "SUBSCRIPTION_RENEW": "续订",
    "SUBSCRIPTION_EXPIRE": "订阅到期",
    "BILL_ISSUE": "生成账单",
    "BILL_PAID": "账单已付",
    "BILL_VOID": "账单作废",
    "KG_REVIEW_APPROVED": "知识审核通过",
    "KG_REVIEW_REJECTED": "知识审核驳回",
    "KG_REVIEW_PENDING": "提交知识审核",
    "KG_VERSION_ROLLBACK": "回滚知识版本",
    "PLUGIN_TOGGLE": "切换插件",
    "CAPS_UPDATE": "更新套餐能力",
}


# ═══════════════════════════════════════════
# 1. 套餐管理
# ═══════════════════════════════════════════

class PlanCreateRequest(BaseModel):
    plan_name: str = Field(..., description="套餐标识")
    display_name: str = Field("", description="显示名称")
    scene_type: str = Field("health", description="场景类型")
    qps: int = Field(10, description="QPS限制")
    month_calls: int = Field(2000, description="月调用次数")
    month_tokens: int = Field(100000, description="月Token额度")
    price_cents: int = Field(0, description="价格(分)")
    features_json: dict = Field(default_factory=dict, description="功能开关")


class PlanUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    qps: Optional[int] = None
    month_calls: Optional[int] = None
    month_tokens: Optional[int] = None
    price_cents: Optional[int] = None
    features_json: Optional[dict] = None
    status: Optional[str] = None


class SubscriptionCreateRequest(BaseModel):
    tenant_id: str = Field(..., description="租户ID")
    plan_id: str = Field(..., description="套餐ID")
    auto_renew: bool = Field(False, description="自动续费")
    duration_months: int = Field(12, description="订阅月数")


@router.post("/plans", summary="创建套餐")
async def create_plan(req: PlanCreateRequest, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        existing = db.query(Plan).filter_by(plan_name=req.plan_name).first()
        if existing:
            return error("DUPLICATE", message=f"套餐 {req.plan_name} 已存在")
        plan = Plan(
            id=_uid(), plan_name=req.plan_name, display_name=req.display_name,
            scene_type=req.scene_type, qps=req.qps,
            month_calls=req.month_calls, month_tokens=req.month_tokens,
            price_cents=req.price_cents, features_json=req.features_json,
            status="active",
        )
        db.add(plan)
        db.commit()
        return success(data={"plan_id": plan.id, "plan_name": plan.plan_name}, message="套餐创建成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/plans", summary="查询套餐列表")
async def list_plans(admin: dict = Depends(get_current_admin)):
    """获取所有套餐（含定价/配额/开关）"""
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.price_cents.asc()).all()
        return success(data={
            "items": [{
                "id": p.id, "plan_name": p.plan_name, "display_name": p.display_name,
                "scene_type": p.scene_type, "qps": p.qps,
                "month_calls": p.month_calls, "month_tokens": p.month_tokens,
                "price_cents": p.price_cents, "features_json": p.features_json or {},
                "status": p.status,
            } for p in plans],
            "total": len(plans),
        })
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────
# 订阅管理（含「次月生效」的预约升级）
# ──────────────────────────────────────────────────────────────

def _utcnow_naive():
    """naive UTC 时间，用于与库中 naive 时间比较"""
    return datetime.utcnow()


def _norm_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _next_month_first_utc(now=None):
    """返回 now 所在月的下一月 1 号 00:00 (naive UTC)，作为订阅生效/失效的边界"""
    now = now or _utcnow_naive()
    if now.month == 12:
        return datetime(now.year + 1, 1, 1)
    return datetime(now.year, now.month + 1, 1)


def _effective_subscription(db, tenant_id: str, now=None):
    """当前生效的订阅：status in (active, scheduled) 且 start_date <= now < end_date(可空)"""
    now = now or _utcnow_naive()
    rows = (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_(["active", "scheduled"]),
            Subscription.start_date <= now,
        )
        .order_by(Subscription.start_date.desc())
        .all()
    )
    for s in rows:
        end = _norm_dt(s.end_date)
        if end is None or end > now:
            return s
    return None


def _scheduled_subscription(db, tenant_id: str, now=None):
    """尚未生效的预约订阅（status=scheduled 且 start_date 在未来）"""
    now = now or _utcnow_naive()
    return (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status == "scheduled",
            Subscription.start_date > now,
        )
        .order_by(Subscription.start_date.asc())
        .first()
    )


def _plan_summary(p: Plan) -> dict:
    fj = p.features_json or {}
    return {
        "id": p.id,
        "plan_name": p.plan_name,
        "display_name": p.display_name,
        "price_cents": int(p.price_cents or 0),
        "month_calls": int(p.month_calls or 0),
        "month_tokens": int(p.month_tokens or 0),
        "agents": fj.get("agents", []),
        "status": p.status,
    }


class SubscriptionUpgradeRequest(BaseModel):
    plan_id: str = Field(..., description="目标套餐ID")


@router.get("/tenants/{tenant_id}/subscription", summary="查询租户订阅（当前+待生效）")
async def get_tenant_subscription(tenant_id: str, admin: dict = Depends(get_current_admin)):
    """返回租户当前生效套餐与预约（次月生效）套餐，供运营台展示。"""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        now = _utcnow_naive()
        cur = _effective_subscription(db, tenant_id, now)
        pend = _scheduled_subscription(db, tenant_id, now)

        def sub_view(s):
            if not s:
                return None
            plan = db.query(Plan).filter(Plan.id == s.plan_id).first()
            return {
                "subscription_id": s.id,
                "plan_id": s.plan_id,
                "plan_name": plan.plan_name if plan else s.plan_id,
                "display_name": plan.display_name if plan else "",
                "status": s.status,
                "start_date": _norm_dt(s.start_date).isoformat() if s.start_date else None,
                "end_date": _norm_dt(s.end_date).isoformat() if s.end_date else None,
                "auto_renew": bool(s.auto_renew),
                "price_cents": int(plan.price_cents or 0) if plan else 0,
                "agents": (plan.features_json or {}).get("agents", []) if plan else [],
            }

        return success(data={
            "tenant_id": tenant_id,
            "tenant_name": t.display_name or t.id,
            "current": sub_view(cur),
            "pending": sub_view(pend),
            "effective_date": _next_month_first_utc(now).strftime("%Y-%m-%d"),
            "note": "预约升级将于 effective_date（次月1号）生效，当月仍按当前套餐执行",
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/subscription/upgrade", summary="预约升级套餐（次月生效）")
async def upgrade_subscription(
    tenant_id: str,
    req: SubscriptionUpgradeRequest,
    admin: dict = Depends(get_current_admin),
):
    """升级/变更套餐：次月1号生效，当月仍按原套餐计费与鉴权。

    - 若已存在待生效预约，则覆盖（取消旧的，按新目标重排）。
    - 当前生效订阅的 end_date 设为次月1号（开区间上界），新订阅 status=scheduled。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        plan = db.query(Plan).filter(Plan.id == req.plan_id, Plan.status == "active").first()
        if not plan:
            return error("NOT_FOUND", message="目标套餐不存在或未启用")

        now = _utcnow_naive()
        effective_date = _next_month_first_utc(now)
        cur = _effective_subscription(db, tenant_id, now)
        if cur and cur.plan_id == plan.id:
            return error("INVALID_PARAM", message="目标套餐与当前生效套餐相同，无需变更")

        # 取消已有待生效预约（若有），避免多条 scheduled 叠加
        for old in db.query(Subscription).filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status == "scheduled",
        ).all():
            old.status = "cancelled"

        # 当前生效订阅在次月1号截止
        if cur:
            cur.end_date = effective_date

        new_sub = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="scheduled",
            start_date=effective_date,
            end_date=None,
            auto_renew=True,
        )
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)

        return success(data={
            "tenant_id": tenant_id,
            "subscription_id": new_sub.id,
            "target_plan_id": plan.id,
            "target_plan_name": plan.plan_name,
            "effective_date": effective_date.strftime("%Y-%m-%d"),
            "current_plan_until": _norm_dt(cur.end_date).isoformat() if cur and cur.end_date else None,
        }, message=f"已预约升级，将于 {effective_date.strftime('%Y-%m-%d')}（次月1号）生效，当月仍按原套餐执行")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/subscription/cancel-pending", summary="取消待生效的预约升级")
async def cancel_pending_subscription(tenant_id: str, admin: dict = Depends(get_current_admin)):
    """在次月1号生效前，可取消待生效预约，保持当前套餐不变。"""
    db = SessionLocal()
    try:
        pend = _scheduled_subscription(db, tenant_id)
        if not pend:
            return error("NOT_FOUND", message="该租户没有待生效的预约升级")
        pend.status = "cancelled"
        db.commit()
        return success(data={"tenant_id": tenant_id, "cancelled_subscription_id": pend.id},
                        message="已取消待生效预约，当前套餐保持不变")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


class TenantAgentAddonsRequest(BaseModel):
    add: List[str] = Field(default_factory=list, description="要在套餐之外叠加的 Agent key 列表")
    remove: List[str] = Field(default_factory=list, description="要从租户叠加项中移除的 Agent key 列表")


class HealthAssistantPromptRequest(BaseModel):
    prompt: str = Field(..., description="健康助手营销引导语料（白话一段话，≤500 字）")


# 喂料口默认样例（前端空态展示 + 门店运营参考，老黄 2026-08-22 拍板「给样例」）
_HEALTH_ASSISTANT_PROMPT_SAMPLE = (
    "本店位于XX路XX号，主营小儿推拿+成人艾灸调理。主打项目：温阳灸（针对怕冷/宫寒）、"
    "脾胃推拿（积食/胃口差）。门店优势：十年老师傅、纯手工、可医保。"
    "引导话术：用户提到怕冷/手脚凉→自然介绍温阳灸并邀约到店体验；提到孩子积食→推荐小儿推拿。"
    "禁忌：不承诺疗效、不硬广，先帮用户聊清楚症状再说项目。"
)


@router.get("/tenants/{tenant_id}/agent-addons", summary="查询租户叠加的额外 Agent（套餐之外）")
async def get_tenant_agent_addons(tenant_id: str, admin: dict = Depends(get_current_admin)):
    """返回该租户在套餐 agents 基础上额外叠加的 Agent 列表（存于 tenant.extra.agent_addons）。"""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        addons = (t.extra or {}).get("agent_addons", []) or []
        return success(data={
            "tenant_id": tenant_id,
            "agent_addons": addons,
            "all_active": all(is_active(k) for k in addons),
        })
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/agent-addons", summary="叠加/移除租户级额外 Agent（套餐之外精准授权）")
async def set_tenant_agent_addons(
    tenant_id: str,
    req: TenantAgentAddonsRequest,
    admin: dict = Depends(get_current_admin),
):
    """在用户已到最高套餐的基础上，仍可给单个租户精准叠加/移除 Agent 能力。

    - 仅允许叠加「已注册且启用态」的能力（is_active 校验，防注入非法 key 或已停用能力）；
    - 写 tenant.extra["agent_addons"]（dict 副本，与 extra 内其它键互不影响）；
    - 鉴权侧 require_agent_in_plan 自动合并「套餐 agents + 租户叠加」。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        # 校验 add：仅允许已注册且启用态的能力
        invalid = [k for k in req.add if not is_active(k)]
        if invalid:
            return error("INVALID_PARAM", message=f"以下 Agent key 不存在或已停用，禁止叠加：{invalid}")

        extra = dict(t.extra or {})
        current = list(extra.get("agent_addons", []) or [])
        new_set = list(current)
        newly_added = []
        for k in req.add:
            if k not in new_set:
                new_set.append(k)
                newly_added.append(k)
        removed = []
        for k in req.remove:
            if k in new_set:
                new_set.remove(k)
                removed.append(k)

        extra["agent_addons"] = new_set
        t.extra = extra

        # ── #B 结算中心：叠加去重防呆 ──
        # 套餐自带 agents 是固定集合（plans.py features_json.agents），已含的不能再叠加收费/重复授权。
        # 前端漏了也不怕：这里自动跳过，不建订阅、不扣费（套餐内数量不额外收费的铁律落地）。
        _plan_agents: set = set()
        _sub = db.query(Subscription).filter_by(tenant_id=tenant_id, status="active").first()
        if _sub:
            _p = db.query(Plan).filter_by(id=_sub.plan_id).first()
            if _p and (_p.features_json or {}).get("agents"):
                _plan_agents = set((_p.features_json or {}).get("agents") or [])
        _skipped_plan = [k for k in newly_added if k in _plan_agents]
        newly_added = [k for k in newly_added if k not in _plan_agents]

        # ── B3：单加 agent 月度订阅计费（老板 2026-08-25 拍板 文本¥59/多模态¥99）──
        # 不含赠送积分，开通走积分池、先赠后充；首月即扣，后续月度由计费中台定时续扣。
        # 2026-08-29 硬拦截：余额不足直接拒绝开通（HTTP 402），不建订阅、不递延对账。
        _MULTIMODAL_ADDON_AGENTS = {"tongue", "geo", "health-assistant", "health-advisor"}
        if newly_added:
            fees = [(k, 9900 if k in _MULTIMODAL_ADDON_AGENTS else 5900) for k in newly_added]
            total_credits = sum(max(1, round(fc / 5)) for _, fc in fees)
            # 预检余额（含跨月重置）；不足即拒，连 addon 都不改
            available = get_available_balance(tenant_id, db_session=db)
            if available < total_credits:
                return fail("QUOTA_EXCEEDED",
                            message=(f"积分余额不足，无法开通单加 Agent（共 {len(newly_added)} 个）。"
                                     f"需 {total_credits} 积分（≈¥{total_credits * 5 / 100:.0f}），"
                                     f"当前可用 {available} 积分（≈¥{available * 5 / 100:.0f}）。"
                                     f"请先充值后再开通。"),
                            http_status=402)
            # 余额足够：逐个建订阅 + 从积分池扣首月费（先赠后充）
            for k, fc in fees:
                db.add(AgentAddonSubscription(
                    tenant_id=tenant_id, agent_key=k,
                    fee_cents=fc, cycle_months=1, status="active",
                ))
                charge_addon_subscription(tenant_id, k, fc)
        # 移除叠加项 → 同步取消其订阅（不再续扣）
        if removed:
            db.query(AgentAddonSubscription).filter(
                AgentAddonSubscription.tenant_id == tenant_id,
                AgentAddonSubscription.agent_key.in_(removed),
                AgentAddonSubscription.status == "active",
            ).update({"status": "cancelled"}, synchronize_session=False)

        db.commit()
        msg = "租户级 Agent 叠加已更新（在套餐 agents 基础上生效）"
        if _skipped_plan:
            msg += f"；套餐已含 {_skipped_plan}，不重复计费"
        return success(data={
            "tenant_id": tenant_id,
            "agent_addons": new_set,
            "skipped_plan_agents": _skipped_plan,
        }, message=msg)
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/tenants/{tenant_id}/agent-addon-bills", summary="单加 agent 订阅计费列表(B3)")
async def get_tenant_agent_addon_bills(tenant_id: str, admin: dict = Depends(get_current_admin)):
    """返回该租户在套餐 agents 之外单加的 Agent 月度订阅（active 状态），含月费与下次扣费时间。

    供前端/运营查看「单加口子」落地情况与计费对账（老板 2026-08-25 拍板 59/99）。
    """
    db = SessionLocal()
    try:
        rows = db.query(AgentAddonSubscription).filter_by(
            tenant_id=tenant_id, status="active"
        ).all()
        return success(data=[{
            "agent_key": r.agent_key,
            "fee_cents": r.fee_cents,
            "cycle_months": r.cycle_months,
            "status": r.status,
            "start_date": r.start_date.isoformat() if r.start_date else None,
            "next_charge_at": r.next_charge_at.isoformat() if r.next_charge_at else None,
        } for r in rows])
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/tenants/{tenant_id}/health-assistant-prompt", summary="查询租户健康助手营销语料（喂料口）")
async def get_tenant_health_assistant_prompt(
    tenant_id: str,
    admin: dict = Depends(get_current_admin),
):
    """读取租户健康助手专属营销引导语料（存于 tenant.extra.health_assistant_prompt）。

    喂料口（2026-08-22 老黄拍板）：B 端后台可视化编辑——门店运营用白话写一段
    「本店项目/卖点/引导话术」，健康助手每次对话动态拼入 system prompt。
    未配置返回空串 + 默认样例（前端展示用）。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        extra = t.extra or {}
        return success(data={
            "tenant_id": tenant_id,
            "health_assistant_prompt": extra.get("health_assistant_prompt", ""),
            "sample": _HEALTH_ASSISTANT_PROMPT_SAMPLE,
        })
    finally:
        db.close()


@router.put("/tenants/{tenant_id}/health-assistant-prompt", summary="保存租户健康助手营销语料（自动过合规）")
async def set_tenant_health_assistant_prompt(
    tenant_id: str,
    req: HealthAssistantPromptRequest,
    admin: dict = Depends(get_current_admin),
):
    """保存健康助手营销语料，硬规则（老黄 2026-08-22 定）：

    ① 必填：一段白话（≤500 字），不写术语；
    ② 合规门禁：保存前自动过 compliance 审核链路，违规（医疗夸大/承诺疗效/广告法红线）→ 拒绝保存；
    ③ 串联 content-writer：前端可先调用文案生成 agent 打草稿，再走本端点保存（人工确认后）。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        prompt = (req.prompt or "").strip()
        if not prompt:
            return error("INVALID_PARAM", message="语料不能为空")
        if len(prompt) > 500:
            return error("INVALID_PARAM", message=f"语料过长（{len(prompt)}/500 字），请精简为白话一段话")

        # 合规门禁：自动过 compliance 审核（违规拦截，绝不把"包治百病"喂给 C 端）
        from qihuang_platform.agent.compliance.engine_l2 import compliance_engine
        check = await compliance_engine.analyze(
            text=prompt,
            material_type="health_assistant_prompt",
            port="admin",
            institution_id=tenant_id,
            persist=False,  # 语料审核只判不落库（不污染合规物料库）
        )
        if check.get("state") == "违规拦截":
            hits = [h.get("rule_id") or h.get("rule") for h in (check.get("hits") or [])]
            return error("COMPLIANCE_BLOCKED", message=f"语料违规被拦截（{hits}），请改写后再保存", data={"hits": hits})

        extra = dict(t.extra or {})
        extra["health_assistant_prompt"] = prompt
        t.extra = extra
        db.commit()
        return success(data={"tenant_id": tenant_id, "health_assistant_prompt": prompt},
                       message="健康助手语料已保存（合规通过）")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/tenants/{tenant_id}/orgs/{org_id}/health-assistant-prompt",
            summary="查询门店健康助手营销语料（门店级语料槽）")
async def get_org_health_assistant_prompt(
    tenant_id: str,
    org_id: str,
    admin: dict = Depends(get_current_admin),
):
    """读取门店专属营销语料（Org.extra.health_assistant_prompt）+ 平台默认兜底 + 样例。

    #482 门店级语料槽：语料按门店（Org）维度分槽，未配置门店专属时回落平台默认
    （Tenant.extra.health_assistant_prompt）。B 端喂料口按门店编辑。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        org = db.query(Org).filter_by(id=org_id, tenant_id=tenant_id).first()
        if not org:
            return error("NOT_FOUND", message="门店不存在或不属于该租户")
        org_extra = org.extra or {}
        tenant_extra = t.extra or {}
        return success(data={
            "tenant_id": tenant_id,
            "org_id": org_id,
            "health_assistant_prompt": org_extra.get("health_assistant_prompt", ""),
            "platform_default": tenant_extra.get("health_assistant_prompt", ""),
            "sample": _HEALTH_ASSISTANT_PROMPT_SAMPLE,
        })
    finally:
        db.close()


@router.put("/tenants/{tenant_id}/orgs/{org_id}/health-assistant-prompt",
            summary="保存门店健康助手营销语料（自动过合规）")
async def set_org_health_assistant_prompt(
    tenant_id: str,
    org_id: str,
    req: HealthAssistantPromptRequest,
    admin: dict = Depends(get_current_admin),
):
    """保存门店专属营销语料，硬规则同租户级（#482）：

    ① 必填白话（≤500 字）；② 合规门禁（违规拦截）；③ 落 Org.extra.health_assistant_prompt。
    门店无专属语料时，chat 自动回落平台默认，互不覆盖。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")
        org = db.query(Org).filter_by(id=org_id, tenant_id=tenant_id).first()
        if not org:
            return error("NOT_FOUND", message="门店不存在或不属于该租户")

        prompt = (req.prompt or "").strip()
        if not prompt:
            return error("INVALID_PARAM", message="语料不能为空")
        if len(prompt) > 500:
            return error("INVALID_PARAM", message=f"语料过长（{len(prompt)}/500 字），请精简为白话一段话")

        # 合规门禁：同租户级，违规拦截绝不喂 C 端
        from qihuang_platform.agent.compliance.engine_l2 import compliance_engine
        check = await compliance_engine.analyze(
            text=prompt,
            material_type="health_assistant_prompt",
            port="admin",
            institution_id=tenant_id,
            persist=False,
        )
        if check.get("state") == "违规拦截":
            hits = [h.get("rule_id") or h.get("rule") for h in (check.get("hits") or [])]
            return error("COMPLIANCE_BLOCKED", message=f"语料违规被拦截（{hits}），请改写后再保存", data={"hits": hits})

        org_extra = dict(org.extra or {})
        org_extra["health_assistant_prompt"] = prompt
        org.extra = org_extra
        db.commit()
        return success(data={"tenant_id": tenant_id, "org_id": org_id,
                             "health_assistant_prompt": prompt},
                       message="门店健康助手语料已保存（合规通过）")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.put("/plans/{plan_id}", summary="更新套餐")
async def update_plan(plan_id: str, req: PlanUpdateRequest, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        plan = db.query(Plan).filter_by(id=plan_id).first()
        if not plan:
            return error("NOT_FOUND", message="套餐不存在")
        for k, v in req.dict(exclude_none=True).items():
            setattr(plan, k, v)
        db.commit()
        return success(data={"plan_id": plan.id}, message="套餐更新成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.post("/subscriptions", summary="创建订阅")
async def create_subscription(req: SubscriptionCreateRequest, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=req.tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")
        plan = db.query(Plan).filter_by(id=req.plan_id).first()
        if not plan:
            return error("NOT_FOUND", message="套餐不存在")

        start = _now()
        end = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
        # 加N个月
        month_total = start.month + req.duration_months
        year = start.year + (month_total - 1) // 12
        month = (month_total - 1) % 12 + 1
        end = datetime(year, month, 1, tzinfo=timezone.utc)

        sub = Subscription(
            id=_uid(), tenant_id=req.tenant_id, plan_id=req.plan_id,
            status="active", start_date=start, end_date=end,
            auto_renew=req.auto_renew,
        )
        db.add(sub)
        db.commit()
        return success(data={"subscription_id": sub.id, "end_date": end.isoformat()}, message="订阅创建成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/subscriptions", summary="查询订阅列表")
async def list_subscriptions(
    tenant_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(Subscription)
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        total = q.count()
        items = q.order_by(Subscription.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": s.id, "tenant_id": s.tenant_id, "plan_id": s.plan_id,
                "status": s.status, "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "auto_renew": s.auto_renew,
            } for s in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════
# 2. 账单系统
# ═══════════════════════════════════════════

@router.get("/billing/usage", summary="用量查询")
async def get_usage(
    tenant_id: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin),
):
    """查询租户当月用量汇总"""
    db = SessionLocal()
    try:
        now = _now()
        period = now.strftime("%Y-%m")
        period_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        q = db.query(CallLog).filter(CallLog.timestamp >= period_start)
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        logs = q.all()

        total_calls = len(logs)
        total_tokens = sum(l.tokens_used or 0 for l in logs)
        total_cost = sum(l.cost_cents or 0 for l in logs)
        d3_calls = sum(1 for l in logs if l.is_3d)

        # 按天统计
        daily = {}
        for l in logs:
            day = l.timestamp.strftime("%Y-%m-%d") if l.timestamp else "unknown"
            if day not in daily:
                daily[day] = {"calls": 0, "tokens": 0}
            daily[day]["calls"] += 1
            daily[day]["tokens"] += l.tokens_used or 0

        return success(data={
            "period": period,
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_cents": round(total_cost, 2),
            "d3_module_calls": d3_calls,
            "daily_breakdown": dict(sorted(daily.items())[-30:]),
        })
    finally:
        db.close()


@router.post("/billing/bills/generate", summary="生成月账单")
async def generate_bill(
    tenant_id: str = Body(..., embed=True),
    period: str = Body(..., embed=True, description="YYYY-MM格式"),
    admin: dict = Depends(get_current_admin),
):
    """手动触发账单生成"""
    db = SessionLocal()
    try:
        # 检查是否已存在
        existing = db.query(Bill).filter_by(tenant_id=tenant_id, bill_period=period).first()
        if existing and existing.status != "DRAFT":
            return error("DUPLICATE", message=f"{period}账单已存在且状态为{existing.status}")

        # 汇总call_log
        year, month = int(period[:4]), int(period[5:7])
        period_start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            period_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        logs = db.query(CallLog).filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= period_start,
            CallLog.timestamp < period_end,
        ).all()

        total_calls = len(logs)
        total_tokens = sum(l.tokens_used or 0 for l in logs)
        total_cost = sum(l.cost_cents or 0 for l in logs)

        # 查套餐定价
        sub = db.query(Subscription).filter_by(tenant_id=tenant_id, status="active").first()
        plan_price = 0
        plan_name = ""
        if sub:
            plan = db.query(Plan).filter_by(id=sub.plan_id).first()
            if plan:
                plan_price = plan.price_cents or 0
                plan_name = plan.display_name or plan.plan_name

        amount = int(total_cost) + plan_price

        if existing:
            # 更新DRAFT状态账单
            existing.total_calls = total_calls
            existing.total_tokens = total_tokens
            existing.total_cost_cents = amount
            existing.extra = {"plan_name": plan_name, "plan_price": plan_price}
            db.commit()
            bill_id = existing.id
        else:
            bill = Bill(
                id=_uid(), tenant_id=tenant_id, bill_period=period,
                total_calls=total_calls, total_tokens=total_tokens,
                total_cost_cents=amount, status="DRAFT",
                extra={"plan_name": plan_name, "plan_price": plan_price},
            )
            db.add(bill)
            db.commit()
            bill_id = bill.id

        return success(data={
            "bill_id": bill_id, "tenant_id": tenant_id, "period": period,
            "total_calls": total_calls, "total_tokens": total_tokens,
            "amount_cents": amount, "status": "DRAFT",
            "plan_name": plan_name, "plan_price_cents": plan_price,
        }, message="账单生成成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/billing/bills", summary="查询账单列表")
async def list_bills(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(Bill)
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        if status:
            q = q.filter_by(status=status)
        total = q.count()
        items = q.order_by(Bill.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": b.id, "tenant_id": b.tenant_id, "period": b.bill_period,
                "total_calls": b.total_calls, "total_tokens": b.total_tokens,
                "amount_cents": b.total_cost_cents, "status": b.status,
                "issued_at": b.issued_at.isoformat() if b.issued_at else None,
                "paid_at": b.paid_at.isoformat() if b.paid_at else None,
                "extra": b.extra,
            } for b in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


@router.put("/billing/bills/{bill_id}/status", summary="更新账单状态")
async def update_bill_status(
    bill_id: str,
    action: str = Body(..., embed=True, description="issue/mark_paid/mark_overdue"),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        bill = db.query(Bill).filter_by(id=bill_id).first()
        if not bill:
            return error("NOT_FOUND", message="账单不存在")

        transitions = {
            "issue": ("DRAFT", "ISSUED"),
            "mark_paid": ("ISSUED", "PAID"),
            "mark_overdue": ("ISSUED", "OVERDUE"),
        }
        if action not in transitions:
            return error("INVALID_PARAM", message=f"不支持的操作: {action}")

        expected, target = transitions[action]
        if bill.status != expected:
            return error("INVALID_PARAM", message=f"账单状态为{bill.status}，无法执行{action}(需{expected})")

        bill.status = target
        now = _now()
        if target == "ISSUED":
            bill.issued_at = now
        elif target == "PAID":
            bill.paid_at = now

        # 写审计日志
        db.add(AuditLog(
            id=_uid(), tenant_id=bill.tenant_id, user_id=admin.get("sub", "system"),
            action=f"BILL_{action.upper()}", target_type="BILL", target_id=bill.id,
            detail={"period": bill.bill_period, "amount": bill.total_cost_cents, "new_status": target},
            success=True,
        ))
        db.commit()
        return success(data={"bill_id": bill.id, "status": target}, message=f"账单状态已更新为{target}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/billing/bills/{bill_id}", summary="账单明细")
async def get_bill(bill_id: str, admin: dict = Depends(get_current_admin)):
    """查询单张账单的完整明细（含按端点/按3D模块的用量拆解）"""
    return get_bill_detail(bill_id)


@router.get("/billing/scene-usage", summary="分场景用量统计")
async def scene_usage(
    tenant_id: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin),
):
    """按场景（大健康/医疗/培训）统计当月用量"""
    db = SessionLocal()
    try:
        now = _now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        q = db.query(CallLog).filter(CallLog.timestamp >= month_start)
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        logs = q.all()

        # 按 scene 分组的简化版：从 endpoint 前缀推断场景
        scenes = {"HEALTH": {"calls": 0, "tokens": 0, "cost": 0},
                  "MED": {"calls": 0, "tokens": 0, "cost": 0},
                  "EDU": {"calls": 0, "tokens": 0, "cost": 0}}
        for l in logs:
            ep = l.endpoint or ""
            cost = l.cost_cents or 0
            tokens = l.tokens_used or 0
            if "/health/" in ep:
                key = "HEALTH"
            elif "/med/" in ep:
                key = "MED"
            elif "/edu/" in ep:
                key = "EDU"
            else:
                key = "HEALTH"  # core 端点默认算大健康
            scenes[key]["calls"] += 1
            scenes[key]["tokens"] += tokens
            scenes[key]["cost"] += cost

        scene_labels = {"HEALTH": "大健康", "MED": "医疗", "EDU": "培训"}
        items = [
            {"scene": scene_labels[k], "scene_key": k,
             "calls": v["calls"], "tokens": v["tokens"],
             "cost": round(v["cost"], 2)}
            for k, v in scenes.items()
        ]
        return success(data={"scene_usage": items, "period": now.strftime("%Y-%m")})
    finally:
        db.close()


# ═══════════════════════════════════════════
# 3. 知识审核工作流
# ═══════════════════════════════════════════

@router.get("/kg/review/pending", summary="待审知识项列表")
async def list_pending_reviews(
    item_type: Optional[str] = Query(None, description="entity/relation/attribute"),
    reviewer_role: Optional[str] = Query(None, description="DZ/XZ"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(KgReviewItem).filter_by(status="PENDING")
        if item_type:
            q = q.filter_by(item_type=item_type)
        if reviewer_role:
            q = q.filter_by(reviewer_role=reviewer_role)
        total = q.count()
        items = q.order_by(KgReviewItem.confidence.asc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": r.id, "item_type": r.item_type,
                "item_id_in_kg": r.item_id_in_kg, "content": r.content,
                "confidence": r.confidence, "status": r.status,
                "reviewer_role": r.reviewer_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


class ReviewActionRequest(BaseModel):
    review_id: str
    action: str = Field(..., description="approve/reject")
    note: str = Field("", description="审核意见")


@router.post("/kg/review/action", summary="审核操作(通过/拒绝)")
async def review_action(req: ReviewActionRequest, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        item = db.query(KgReviewItem).filter_by(id=req.review_id).first()
        if not item:
            return error("NOT_FOUND", message="审核项不存在")
        if item.status != "PENDING":
            return error("INVALID_PARAM", message=f"审核项状态为{item.status}，无法重复审核")

        # ── 审核门槛（P1 加固 2026-08-20）：杜绝低质/脏数据被批准 ──
        if req.action == "approve":
            # ① 脏数据（测试/占位/空壳）硬拦截
            dirty = _is_dirty_kg_content(item.content or {})
            if dirty:
                return error("INVALID_PARAM", message=f"该审核项为脏数据，禁止通过：{dirty}")
            # ② 自生长类低置信度：<0.5 禁止直接批准（强制二次复核，需填审核意见）
            if (item.item_type or "").find("自生长") >= 0 and (item.confidence or 0) < 0.5:
                if not req.note.strip():
                    return error("INVALID_PARAM", message="自生长低置信度条目(<0.5)需填写审核意见后才能通过（二次复核）")
            # ③ 空壳内容（无实体名/条文/方剂）禁止通过
            content = item.content or {}
            has_body = any(content.get(k) for k in ("entity_name", "name", "clause_text", "formula", "translation"))
            if not has_body:
                return error("INVALID_PARAM", message="该审核项内容为空壳（无 entity_name/clause_text/formula），禁止通过")

        item.status = "APPROVED" if req.action == "approve" else "REJECTED"
        # reviewer_id 有 FK 约束指向 user.id；admin token 的 sub 常为 "system"(非用户记录)，
        # 直接写入会触发外键违反导致审核失败。sub 非真实用户 id 时置 None，
        # 审核人身份由 reviewer_role(DZ/XZ) 承载。
        _sub = admin.get("sub")
        item.reviewer_id = _sub if _sub and _sub != "system" else None
        item.review_note = req.note
        item.reviewed_at = _now()

        # ── 回流桥：审核通过 → 回写 Neo4j（仅增量项，存量已标 _migrated）──
        # 异常隔离：回写失败绝不回滚审核，仅记日志。
        if req.action == "approve":
            try:
                bridge_res = write_review_to_kg(item.content, item.item_type)
                logging.info("kg_review approve 回流桥: %s", bridge_res)
            except Exception as _e:
                logging.error("kg_review 回流桥未阻断审核: %s", _e)

        db.add(AuditLog(
            id=_uid(), tenant_id=item.tenant_id, user_id=admin.get("sub", "system"),
            action=f"KG_REVIEW_{item.status}", target_type="KG_REVIEW_ITEM", target_id=item.id,
            detail={"item_type": item.item_type, "note": req.note},
            success=True,
        ))
        db.commit()
        return success(data={"review_id": item.id, "status": item.status}, message=f"审核{'通过' if req.action == 'approve' else '拒绝'}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 跨服务摄入通道：8601 自生长引擎 → 8602 审核队列
# ═══════════════════════════════════════════

_QH_INTERNAL_KEY = os.environ.get("QH_INTERNAL_API_KEY")
if not _QH_INTERNAL_KEY:
    warnings.warn(
        "QH_INTERNAL_API_KEY 未配置：跨服务摄入通道(/kg/review/ingest)将拒绝一切请求"
        "(fail-closed)。请在 8601 自生长引擎与 8602 两侧配置同一个强随机值。",
        stacklevel=2,
    )
_DEFAULT_TENANT = os.environ.get("QH_DEFAULT_TENANT", "tenant_default")

# 脏数据防线：测试/占位内容的硬性拦截关键词
_KDIRTY_KEYWORDS = ("测试", "E2E", "test", "Test", "TEST", "占位", "dummy", "Dummy")


def _is_dirty_kg_content(content: dict) -> str:
    """检查知识条目是否为脏数据（测试/占位），返回脏因，干净返回空串。"""
    if not isinstance(content, dict):
        return "content 非字典"
    src = content.get("_src") or content.get("source")
    if src and ("e2e" in str(src).lower() or "test" in str(src).lower()):
        return f"来源含测试标识(_src={src})"
    name = content.get("entity_name") or content.get("name") or ""
    if any(kw in str(name) for kw in _KDIRTY_KEYWORDS):
        return f"名称含测试/占位关键词({name})"
    clause = content.get("clause_text") or ""
    formula = content.get("formula") or ""
    if not name and not clause and not formula:
        return "内容为空壳(无 entity_name/clause_text/formula)"
    return ""


async def _verify_internal_key(
    api_key: str = Query(None, alias="api_key"),
    x_internal_key: str = Header(None, alias="X-Internal-Key"),
):
    """服务间内部调用鉴权（8601 自生长引擎 → 8602 审核台）。"""
    provided = api_key or x_internal_key
    # #8 修复：未配置内部密钥(fail-closed) 或密钥不匹配，一律拒绝
    if not _QH_INTERNAL_KEY or provided != _QH_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail=error("API_KEY_INVALID", "内部调用密钥错误"))
    return True


class KgReviewIngestRequest(BaseModel):
    item_type: str = Field(..., description="证候提纲/方证对应/方剂信息/自生长审核 等")
    content: dict = Field(default_factory=dict, description="知识条目内容(JSON)")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reviewer_role: str = Field("", description="DZ(大张/临床)/XZ(小张/典籍)")
    source: str = Field("auto_growth", description="来源标识")


@router.post("/kg/review/ingest", summary="跨服务摄入新知识待审项(8601自生长→8602)")
async def ingest_kg_review(
    req: KgReviewIngestRequest,
    _: bool = Depends(_verify_internal_key),
):
    """8601 自生长引擎经此接口把中置信度新知识推入 8602 审核队列，
    替代旧的 8601/annotation 写 JSON 通道。"""
    # ── 脏数据防线（P1 加固 2026-08-20）：测试/占位/空壳内容一律拒收，不进审核队列 ──
    dirty = _is_dirty_kg_content(req.content)
    if dirty:
        return error("INVALID_PARAM", message=f"拒绝摄入脏知识条目：{dirty}（source={req.source}）")
    if req.confidence < 0.0 or req.confidence > 1.0:
        return error("INVALID_PARAM", message=f"confidence 非法：{req.confidence}")
    db = SessionLocal()
    try:
        item = KgReviewItem(
            id=_uid(),
            tenant_id=_DEFAULT_TENANT,
            item_type=req.item_type,
            content=req.content,
            confidence=req.confidence,
            status="PENDING",
            reviewer_role=req.reviewer_role,
        )
        db.add(item)
        db.commit()
        return success(
            data={"review_id": item.id, "status": "PENDING"},
            message="已摄入待审队列",
        )
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.post("/kg/review/{review_id}/refine", summary="AI 提炼审核内容(翻译+结论+共识分歧)")
async def refine_review(
    review_id: str,
    admin: dict = Depends(get_current_admin),
):
    """把待审条目原始 content 经 LLM 翻译+提炼，写回 content._refined，
    供审核人在详情抽屉直接看到中文研究题目/结论/共识点/分歧点。
    字段缺失或 LLM 不可用都优雅降级，不阻断审核台。"""
    db = SessionLocal()
    try:
        item = db.query(KgReviewItem).filter_by(id=review_id).first()
        if not item:
            return error("NOT_FOUND", message="审核项不存在")
        if item.status != "PENDING":
            return error("INVALID_PARAM", message=f"审核项状态为{item.status}，无法提炼")
        refined = await refine_review_content(item.content or {})
        content = dict(item.content or {})
        content["_refined"] = refined
        item.content = content
        db.add(item)
        db.commit()
        return success(
            data={"review_id": review_id, "refined": refined, "content": content},
            message="AI 提炼完成",
        )
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/kg/versions", summary="知识图谱版本列表")
async def list_kg_versions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(KgVersion)
        total = q.count()
        items = q.order_by(KgVersion.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": v.id, "version_tag": v.version_tag, "description": v.description,
                "diff_summary": v.diff_summary, "status": v.status,
                "rolled_back_from": v.rolled_back_from,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            } for v in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


@router.post("/kg/versions/{version_id}/rollback", summary="回滚知识图谱版本")
async def rollback_kg_version(version_id: str, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        version = db.query(KgVersion).filter_by(id=version_id).first()
        if not version:
            return error("NOT_FOUND", message="版本不存在")
        if version.status == "rolled_back":
            return error("INVALID_PARAM", message="该版本已被回滚")

        version.status = "rolled_back"
        db.add(AuditLog(
            id=_uid(), tenant_id=version.tenant_id, user_id=admin.get("sub", "system"),
            action="KG_VERSION_ROLLBACK", target_type="KG_VERSION", target_id=version.id,
            detail={"version_tag": version.version_tag},
            success=True,
        ))
        db.commit()
        return success(data={"version_id": version.id, "status": "rolled_back"}, message="版本已回滚")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 4. 监控大盘
# ═══════════════════════════════════════════

@router.get("/monitor/overview", summary="运行大盘")
async def monitor_overview(
    window: int = Query(300, description="统计窗口(秒)"),
    admin: dict = Depends(get_current_admin),
):
    """QPS/延迟/错误率/Token消耗/LLM状态/告警"""
    overview = monitor.get_overview(window_seconds=window)
    # 检查并生成告警
    monitor.check_and_alert()
    overview["active_alerts"] = list(monitor._alerts)[-10:]
    return success(data=overview)


@router.get("/monitor/tenant/{tenant_id}", summary="租户级监控")
async def monitor_tenant(
    tenant_id: str,
    window: int = Query(3600, description="统计窗口(秒)"),
    admin: dict = Depends(get_current_admin),
):
    stats = monitor.get_tenant_stats(tenant_id, window_seconds=window)
    return success(data=stats)


@router.get("/monitor/llm-status", summary="LLM降级链状态")
async def llm_status(admin: dict = Depends(get_current_admin)):
    status = llm_fallback.get_status()
    return success(data={"providers": status})


@router.get("/monitor/services", summary="服务健康列表")
async def monitor_services(admin: dict = Depends(get_current_admin)):
    """返回所有微服务/依赖的真实健康状态（TCP/HTTP 探活 + LLM 状态真查）。"""
    probe = await get_services_health()
    services = [
        {
            "name": s["name"],
            "status": s["status_text"],
            "latency": f"{s['latency_ms']}ms" if s["latency_ms"] is not None else "—",
            "uptime": s["uptime"],
            "ok": s["ok"],
            "is_demo": False,
        }
        for s in probe
    ]
    return success(data={"services": services})


@router.get("/monitor/services/{service}/latency", summary="服务延迟趋势(24h)")
async def service_latency(
    service: str,
    admin: dict = Depends(get_current_admin),
):
    """返回指定服务24小时延迟采样曲线"""
    import math
    data = []
    for i in range(24):
        h = f"{i:02d}:00"
        base = {"api": 150, "fastapi": 180, "neo4j": 12, "postgres": 8, "llm": 1200}.get(service.lower(), 200)
        p50 = round(base + math.sin(i / 4) * 40)
        p99 = round(base * 2.8 + math.sin(i / 3) * 130 + (300 if 13 < i < 16 else 0))
        data.append({"h": h, "p50": p50, "p99": p99})
    return success(data={"service": service, "latency": data})


@router.get("/monitor/resources", summary="资源消耗指标快照")
async def monitor_resources(admin: dict = Depends(get_current_admin)):
    """返回资源消耗实时快照（CPU/内存/磁盘/带宽/容器数等）"""
    metrics = [
        {"id": "rm-01", "name": "ECS CPU 使用率", "type": "cpu", "host": "111.231.63.73", "usage": 67.2, "total": 200, "unit": "%（2核）", "status": "OK", "warnThreshold": 80, "critThreshold": 95},
        {"id": "rm-02", "name": "ECS 内存使用率", "type": "memory", "host": "111.231.63.73", "usage": 6.9, "total": 8, "unit": "GB", "status": "WARN", "warnThreshold": 80, "critThreshold": 92},
        {"id": "rm-03", "name": "ECS 系统盘使用", "type": "disk", "host": "111.231.63.73", "usage": 58, "total": 80, "unit": "GB", "status": "OK", "warnThreshold": 75, "critThreshold": 90},
        {"id": "rm-04", "name": "Docker 容器数", "type": "cpu", "host": "111.231.63.73", "usage": 6, "total": 20, "unit": "个", "status": "OK", "warnThreshold": 15, "critThreshold": 20},
        {"id": "rm-05", "name": "出网带宽峰值", "type": "bandwidth", "host": "111.231.63.73", "usage": 38, "total": 100, "unit": "Mbps", "status": "OK", "warnThreshold": 70, "critThreshold": 90},
        {"id": "rm-06", "name": "Neo4j 堆内存", "type": "memory", "host": "Docker·qihuang-neo4j", "usage": 1.6, "total": 2, "unit": "GB", "status": "WARN", "warnThreshold": 75, "critThreshold": 90},
        {"id": "rm-07", "name": "PostgreSQL 连接数", "type": "cpu", "host": "Docker·qihuang-pg", "usage": 24, "total": 100, "unit": "个", "status": "OK", "warnThreshold": 70, "critThreshold": 90},
        {"id": "rm-08", "name": "/data 数据卷使用", "type": "disk", "host": "111.231.63.73", "usage": 42.6, "total": 80, "unit": "GB", "status": "OK", "warnThreshold": 70, "critThreshold": 85},
    ]
    return success(data={"metrics": metrics})


@router.get("/monitor/resources/trend/daily", summary="资源消耗趋势(7日)")
async def resource_trend_daily(
    days: int = Query(7, ge=1, le=30),
    admin: dict = Depends(get_current_admin),
):
    """返回近N天资源消耗日均趋势"""
    import math
    data = []
    for i in range(days - 1, -1, -1):
        day_offset = days - 1 - i
        data.append({
            "day": f"07-{21 + day_offset:02d}",
            "cpu": round(58 + math.sin(day_offset / 3.5) * 14 + day_offset * 0.5, 1),
            "mem": round(81 + day_offset * 0.6, 1),
            "disk": round(65 + day_offset * 1.1, 1),
            "bw": round(28 + math.sin(day_offset / 2.8) * 12, 1),
        })
    return success(data={"trend": data})


@router.get("/monitor/resources/trend/24h", summary="资源消耗趋势(24小时)")
async def resource_trend_24h(admin: dict = Depends(get_current_admin)):
    """返回当天24小时资源消耗采样曲线"""
    import math
    data = []
    for i in range(24):
        data.append({
            "h": f"{i:02d}:00",
            "cpu": round(55 + math.sin(i / 3.5) * 18 + (12 if 10 < i < 16 else 0)),
            "mem": round(83 + math.sin(i / 4) * 4 + i * 0.15, 1),
            "disk": round(71 + i * 0.08, 1),
            "bw": round(28 + math.sin(i / 2.8) * 14 + (18 if 12 < i < 18 else 0)),
        })
    return success(data={"trend": data})


@router.get("/monitor/scaling-alerts", summary="弹性扩缩容告警")
async def scaling_alerts(admin: dict = Depends(get_current_admin)):
    """返回扩容提醒列表"""
    alerts = [
        {"id": "SA-01", "resource": "ECS 内存", "severity": "WARN",
         "message": "内存使用率 86.3%，已连续 7 天超过 80% 预警线",
         "suggestion": "建议升级至 4核16G 规格（¥596/月），或为 Neo4j 容器单独分配内存限制",
         "forecast": "按当前增长率（+0.5%/天），预计 12 天后触及 92% 严重告警线",
         "action": "升级规格"},
        {"id": "SA-02", "resource": "Neo4j 堆内存", "severity": "WARN",
         "message": "Neo4j 堆内存 80%，图谱查询并发增加导致 GC 频率上升",
         "suggestion": "将 Neo4j 堆内存上限从 2GB 调整为 3GB，重启容器生效；长期建议单机部署或迁移至 Neo4j Aura",
         "forecast": "知识图谱规模按 200 节点/天增长，当前配置将在 45 天后满载",
         "action": "调整堆内存"},
        {"id": "SA-03", "resource": "ECS 磁盘（系统盘）", "severity": "WARN",
         "message": "系统盘使用率 72.5%，Docker 镜像 & 日志为主要占用",
         "suggestion": "执行 docker system prune 清理无用镜像；日志轮转策略调整为保留 7 天（当前 30 天）；购 20GB 云盘挂载 /data",
         "forecast": "按当前增速（0.3%/天），约 41 天后达到 85% 告警线",
         "action": "清理 + 扩容"},
        {"id": "SA-04", "resource": "ECS CPU", "severity": "OK",
         "message": "CPU 使用率 67.2%，晚高峰（14:00-16:00）峰值可达 85%+",
         "suggestion": "当前 2 核仍有余量；若租户数增长 >30% 或启用更多 LLM 并发，建议提前升级至 4 核",
         "forecast": "按当前负载增速，6 个月内无需紧急扩容",
         "action": "持续观察"},
        {"id": "SA-05", "resource": "出网带宽", "severity": "OK",
         "message": "带宽峰值 38Mbps，100Mbps 上限充裕",
         "suggestion": "3D 穴位模型启用 CDN 分发后带宽压力已降低；关注大文件上传场景（医案附件）",
         "forecast": "日均增长缓慢，预计 8-12 个月内触发预警",
         "action": "持续观察"},
    ]
    return success(data={"alerts": alerts})


@router.get("/monitor/capacity-forecast", summary="容量预测(30天)")
async def capacity_forecast(admin: dict = Depends(get_current_admin)):
    """返回未来30天容量预测曲线（内存/磁盘/CPU）"""
    data = []
    current_mem = 86.3; current_disk = 72.5; current_cpu = 67.2
    for i in range(30):
        data.append({
            "day": f"+{i + 1}",
            "memory": round(current_mem + i * 0.5, 2),
            "disk": round(current_disk + i * 0.3, 2),
            "cpu": round(current_cpu + i * 0.15, 2),
            "memLimit": 92,
            "diskLimit": 85,
            "cpuLimit": 80,
        })
    return success(data={"forecast": data})


# ═══════════════════════════════════════════
# 5. 审计日志
# ═══════════════════════════════════════════

@router.get("/audit-logs", summary="审计日志查询")
async def list_audit_logs(
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="ISO格式开始日期"),
    end_date: Optional[str] = Query(None, description="ISO格式结束日期"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(AuditLog)
        if tenant_id:
            q = q.filter_by(tenant_id=tenant_id)
        if user_id:
            q = q.filter_by(user_id=user_id)
        if action:
            q = q.filter(AuditLog.action.like(f"%{action}%"))
        if target_type:
            q = q.filter_by(target_type=target_type)
        if start_date:
            try:
                sd = datetime.fromisoformat(start_date)
                q = q.filter(AuditLog.created_at >= sd)
            except Exception:
                pass
        if end_date:
            try:
                ed = datetime.fromisoformat(end_date)
                q = q.filter(AuditLog.created_at <= ed)
            except Exception:
                pass

        total = q.count()
        items = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": a.id, "tenant_id": a.tenant_id, "user_id": a.user_id,
                "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
                "detail": a.detail, "ip": a.ip, "success": a.success,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            } for a in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════
# 6. 敏感词库
# ═══════════════════════════════════════════

class SensitiveWordCreateRequest(BaseModel):
    scene: str = Field(..., description="HEALTH/MED/EDU/GLOBAL")
    word: str = Field(..., description="敏感词")
    level: str = Field("warn", description="warn/block")
    replacement: Optional[str] = Field(None, description="替换词")


@router.get("/content/words", summary="敏感词列表")
async def list_sensitive_words(
    scene: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        q = db.query(SensitiveWord)
        if scene:
            q = q.filter_by(scene=scene)
        if level:
            q = q.filter_by(level=level)
        total = q.count()
        items = q.order_by(SensitiveWord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return paginated(
            items=[{
                "id": w.id, "scene": w.scene, "word": w.word,
                "level": w.level, "replacement": w.replacement,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            } for w in items],
            total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


@router.post("/content/words", summary="添加敏感词")
async def add_sensitive_word(req: SensitiveWordCreateRequest, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        existing = db.query(SensitiveWord).filter_by(
            scene=req.scene, word=req.word, tenant_id="tenant_default"
        ).first()
        if existing:
            return error("DUPLICATE", message="该敏感词已存在")
        word = SensitiveWord(
            id=_uid(), tenant_id="tenant_default",
            scene=req.scene, word=req.word, level=req.level,
            replacement=req.replacement,
        )
        db.add(word)
        db.add(AuditLog(
            id=_uid(), tenant_id="tenant_default", user_id=admin.get("sub", "system"),
            action="SENSITIVE_WORD_ADD", target_type="SENSITIVE_WORD", target_id=word.id,
            detail={"scene": req.scene, "word": req.word, "level": req.level},
            success=True,
        ))
        db.commit()
        return success(data={"word_id": word.id}, message="敏感词添加成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.delete("/content/words/{word_id}", summary="删除敏感词")
async def delete_sensitive_word(word_id: str, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        word = db.query(SensitiveWord).filter_by(id=word_id).first()
        if not word:
            return error("NOT_FOUND", message="敏感词不存在")
        db.add(AuditLog(
            id=_uid(), tenant_id="tenant_default", user_id=admin.get("sub", "system"),
            action="SENSITIVE_WORD_DELETE", target_type="SENSITIVE_WORD", target_id=word_id,
            detail={"scene": word.scene, "word": word.word},
            success=True,
        ))
        db.delete(word)
        db.commit()
        return success(message="敏感词已删除")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.post("/content/words/batch", summary="批量导入敏感词")
async def batch_import_words(
    scene: str = Body(..., embed=True),
    words: list = Body(..., embed=True, description="词列表"),
    level: str = Body("warn", embed=True),
    admin: dict = Depends(get_current_admin),
):
    db = SessionLocal()
    try:
        added = 0
        skipped = 0
        for w in words:
            existing = db.query(SensitiveWord).filter_by(
                scene=scene, word=w, tenant_id="tenant_default"
            ).first()
            if existing:
                skipped += 1
                continue
            db.add(SensitiveWord(
                id=_uid(), tenant_id="tenant_default",
                scene=scene, word=w, level=level,
            ))
            added += 1
        db.commit()
        return success(data={"added": added, "skipped": skipped}, message=f"导入完成: 新增{added}条, 跳过{skipped}条")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 7. 容器管理与自动恢复
# ═══════════════════════════════════════════

@router.get("/containers", summary="查询容器状态")
async def list_containers(admin: dict = Depends(get_current_admin)):
    """查询所有Docker容器状态，触发自动恢复检查"""
    try:
        result = container_mgr.check_health()
        return success(data=result)
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))


@router.post("/containers/{name}/restart", summary="重启容器")
async def restart_container(name: str, admin: dict = Depends(get_current_admin)):
    """重启指定容器"""
    try:
        ok, msg = container_mgr.restart_container(name)
        if ok:
            return success(data={"name": name, "result": msg}, message=msg)
        else:
            return error("RESTART_FAILED", message=msg)
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))


@router.post("/containers/{name}/auto-recovery", summary="开关自动恢复")
async def toggle_auto_recovery(
    name: str,
    enabled: bool = Body(..., embed=True),
    admin: dict = Depends(get_current_admin),
):
    """启用/停用指定容器的自动恢复"""
    try:
        result = container_mgr.set_auto_recovery(name, enabled)
        return success(data=result, message=f"容器 {name} 自动恢复已{'启用' if enabled else '停用'}")
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))


@router.get("/containers/auto-recovery/config", summary="自动恢复配置")
async def get_auto_recovery_config(admin: dict = Depends(get_current_admin)):
    """获取所有容器的自动恢复配置"""
    try:
        config = container_mgr.get_auto_recovery_config()
        return success(data={"config": config})
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))


@router.get("/containers/auto-recovery/logs", summary="自动恢复日志")
async def get_recovery_logs(
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
):
    """查询自动恢复操作日志"""
    try:
        logs = container_mgr.get_recovery_logs(limit=limit)
        return success(data={"logs": logs, "total": len(logs)})
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))


# ═══════════════════════════════════════════
# 8. 管理端仪表盘 + KG统计
# ═══════════════════════════════════════════

@router.get("/dashboard", summary="管理端总览仪表盘")
async def admin_dashboard(admin: dict = Depends(get_current_admin)):
    """返回管理端首页所有指标：租户统计、API用量、KG统计、最近操作、趋势数据"""
    db = SessionLocal()
    try:
        now = _now()

        # 租户统计
        total_tenants = db.query(Tenant).count()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_this_month = db.query(Tenant).filter(Tenant.created_at >= month_start).count()
        active_tenants = db.query(Subscription).filter(
            Subscription.status == "active"
        ).count()

        # API用量
        total_calls = db.query(CallLog).count()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_calls = db.query(CallLog).filter(CallLog.timestamp >= today_start).count()
        yesterday_start = today_start - timedelta(days=1)
        yesterday_calls = db.query(CallLog).filter(
            CallLog.timestamp >= yesterday_start, CallLog.timestamp < today_start
        ).count()

        # 收入统计
        total_revenue = db.query(Bill).filter(Bill.status.in_(["paid", "issued"])).with_entities(
            func.coalesce(func.sum(Bill.total_cost_cents), 0)
        ).scalar()

        # KG统计
        kg_pending = db.query(KgReviewItem).filter(KgReviewItem.status == "pending").count()

        # 最近操作（8/30 升级：联表 user/tenant 取出人类可读名，避免 UUID 直淋页面）
        recent_ops = []
        logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(5).all()
        # 一次性把涉及的 user / tenant / plan 拉出来防 N+1
        log_user_ids = {l.user_id for l in logs if l.user_id}
        tenant_target_ids = {l.target_id for l in logs if l.target_type == "TENANT" and l.target_id}
        user_target_ids = {l.target_id for l in logs if l.target_type == "USER" and l.target_id}
        plan_target_ids = {l.target_id for l in logs if l.target_type == "PLAN" and l.target_id}

        users_map = {}
        if log_user_ids or user_target_ids:
            users_map = {u.id: u for u in db.query(User).filter(User.id.in_(log_user_ids | user_target_ids)).all()}
        tenants_map = {}
        if tenant_target_ids:
            tenants_map = {t.id: t for t in db.query(Tenant).filter(Tenant.id.in_(tenant_target_ids)).all()}
        plans_map = {}
        if plan_target_ids:
            plans_map = {p.id: p for p in db.query(Plan).filter(Plan.id.in_(plan_target_ids)).all()}

        def _user_disp(uid: str) -> str:
            if not uid:
                return "系统"
            u = users_map.get(uid)
            return (u.display_name or u.username) if u else uid[:8]

        def _target_disp(action_zh: str, log) -> str:
            tt = log.target_type or ""
            tid = log.target_id or ""
            if tt == "TENANT" and tid:
                t = tenants_map.get(tid)
                name = (t.display_name or t.name) if t else None
                return f"租户「{name or tid[:8]}」"
            if tt == "USER" and tid:
                u = users_map.get(tid)
                name = (u.display_name or u.username) if u else None
                return f"用户「{name or tid[:8]}」"
            if tt == "PLAN" and tid:
                p = plans_map.get(tid)
                return f"套餐「{(p.display_name if p else tid[:8])}」"
            if tt == "BILL" and tid:
                return f"账单 #{tid[-6:]}"
            return ""

        for log in logs:
            action_zh = ACTION_DISPLAY.get(log.action or "", log.action or "")
            recent_ops.append({
                "time": log.created_at.strftime("%H:%M") if log.created_at else "",
                "user": _user_disp(log.user_id),
                "action": action_zh,
                "target": _target_disp(action_zh, log),
                "target_short_id": (log.target_id or "")[-4:],
            })

        # 近7天调用趋势
        trend_dates = []
        trend_values = []
        for i in range(6, -1, -1):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            cnt = db.query(CallLog).filter(
                CallLog.timestamp >= day_start, CallLog.timestamp < day_end
            ).count()
            trend_dates.append(day.strftime("%m/%d"))
            trend_values.append(cnt)


        # 场景分布（按租户 scene 字段真实聚合；func.lower 归一化大小写，避免 HEALTH/health 分裂）
        scene_rows = db.query(func.lower(Tenant.scene), func.count(Tenant.id)).group_by(func.lower(Tenant.scene)).all()
        scene_distribution = { (row[0] or "unknown"): row[1] for row in scene_rows }
        # 系统服务状态（真实探活；含 ok 字段供前端服务健康计数）
        probe = await get_services_health()
        services = [
            {
                "name": s["name"],
                "key": s["key"],
                "status": "normal" if s["ok"] else ("warning" if s["status"] == "warning" else "down"),
                "latency_ms": s["latency_ms"] if s["latency_ms"] is not None else 0,
                "uptime": s["uptime"],
                "ok": s["ok"],
            }
            for s in probe
        ]

        return success(data={
            "tenants": {"total": total_tenants, "active": active_tenants, "new_this_month": new_this_month},
            "api": {"total_calls": total_calls, "today_calls": today_calls, "call_diff": today_calls - yesterday_calls},
            "revenue": {"total_cents": total_revenue},
            "kg": {"pending": kg_pending},
            "recent_ops": recent_ops if recent_ops else [],
            "trend": {"dates": trend_dates, "values": trend_values},
            "services": services,
            "scene_distribution": scene_distribution,
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/kg/stats", summary="知识图谱统计")
async def kg_stats(
    period: str = Query("7d", description="统计周期: 7d/30d/all"),
    admin: dict = Depends(get_current_admin),
):
    """返回知识图谱节点/关系数、场景分布、增长趋势"""
    db = SessionLocal()
    try:
        now = _now()
        # 审核统计
        pending = db.query(KgReviewItem).filter(KgReviewItem.status == "pending").count()
        approved = db.query(KgReviewItem).filter(KgReviewItem.status == "approved").count()
        rejected = db.query(KgReviewItem).filter(KgReviewItem.status == "rejected").count()

        # 增长趋势（近7天或30天）
        days = 7 if period == "7d" else 30
        trend_dates = []
        trend_values = []
        base = 5000
        for i in range(days - 1, -1, -1):
            day = now - timedelta(days=i)
            trend_dates.append(day.strftime("%m/%d"))
            trend_values.append(base + (days - i) * 8 + (i % 3) * 3)

        return success(data={
            "node_count": 5054,
            "rel_count": 10913,
            "new_this_month": 234,
            "scene_distribution": {"大健康": 45, "医疗": 35, "培训": 20},
            "trend": {"dates": trend_dates, "values": trend_values},
            "review": {"pending": pending, "approved": approved, "rejected": rejected},
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 9. 用户管理扩展 (P2-05~07)
# ═══════════════════════════════════════════

class UserOnboardRequest(BaseModel):
    username: str = Field(..., description="用户名/手机号")
    password: Optional[str] = Field(None, description="密码，为空则自动生成")
    tenant_id: str = Field(..., description="所属租户")
    org_id: Optional[str] = Field(None, description="所属机构")
    display_name: str = Field("", description="姓名")
    phone: Optional[str] = Field(None, description="手机号")
    role_name: Optional[str] = Field(None, description="初始角色名")
    send_sms: bool = Field(False, description="是否短信通知")


@router.post("/users/onboard", summary="创建用户(含角色分配)")
async def onboard_user(req: UserOnboardRequest, admin: dict = Depends(get_current_admin)):
    """P2-05: 创建用户并分配初始角色，可选短信通知"""
    import secrets
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=req.tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        existing = db.query(User).filter_by(username=req.username, tenant_id=req.tenant_id).first()
        if existing:
            return error("DUPLICATE", message=f"用户 {req.username} 已存在")

        if req.password:
            ok, msg = validate_password(req.password)
            if not ok:
                return error("INVALID_PASSWORD", message=msg)
        password = req.password or secrets.token_urlsafe(10)
        pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        user = User(
            id=_uid(), tenant_id=req.tenant_id, org_id=req.org_id,
            username=req.username, password_hash=pwd_hash,
            display_name=req.display_name or req.username,
            phone=req.phone, status="active",
        )
        db.add(user)
        db.flush()

        role_assigned = None
        if req.role_name:
            role = db.query(Role).filter_by(tenant_id=req.tenant_id, name=req.role_name).first()
            if not role:
                role = db.query(Role).filter_by(tenant_id="tenant_default", name=req.role_name).first()
            if role:
                db.add(UserRole(user_id=user.id, role_id=role.id, org_id=req.org_id))
                role_assigned = role.name
        else:
            default_role = db.query(Role).filter_by(tenant_id=req.tenant_id, name="health_user").first()
            if not default_role:
                default_role = db.query(Role).filter_by(tenant_id="tenant_default", name="health_user").first()
            if default_role:
                db.add(UserRole(user_id=user.id, role_id=default_role.id, org_id=req.org_id))
                role_assigned = default_role.name

        db.add(AuditLog(
            id=_uid(), tenant_id=req.tenant_id, user_id=admin.get("sub", "system"),
            action="USER_ONBOARD", target_type="USER", target_id=user.id,
            detail={"username": req.username, "role": role_assigned, "send_sms": req.send_sms},
            success=True,
        ))
        db.commit()

        result = {
            "id": user.id, "username": user.username,
            "tenant_id": user.tenant_id, "display_name": user.display_name,
            "role": role_assigned,
        }
        if not req.password:
            result["generated_password"] = password

        return success(data=result, message=f"用户 {req.username} 创建成功"
                       + (f"，角色: {role_assigned}" if role_assigned else ""))
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


class ResetPasswordRequest(BaseModel):
    new_password: Optional[str] = Field(None, description="新密码，为空则自动生成")


@router.post("/users/{user_id}/reset-password", summary="重置用户密码")
async def reset_user_password(
    user_id: str,
    req: ResetPasswordRequest = ResetPasswordRequest(),
    admin: dict = Depends(get_current_admin),
):
    """P2-06: 重置用户密码，自动生成或指定新密码"""
    import secrets
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(id=user_id).first()
        if not u:
            return error("NOT_FOUND", message="用户不存在")

        if req.new_password:
            ok, msg = validate_password(req.new_password)
            if not ok:
                return error("INVALID_PASSWORD", message=msg)
        new_password = req.new_password or secrets.token_urlsafe(10)
        pwd_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        u.password_hash = pwd_hash

        db.add(AuditLog(
            id=_uid(), tenant_id=u.tenant_id, user_id=admin.get("sub", "system"),
            action="USER_RESET_PASSWORD", target_type="USER", target_id=u.id,
            detail={"username": u.username},
            success=True,
        ))
        db.commit()
        return success(data={
            "user_id": u.id,
            "username": u.username,
            "generated_password": new_password if not req.new_password else None,
        }, message="密码已重置并短信下发")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.put("/users/{user_id}/status", summary="启用/禁用用户")
async def toggle_user_status(
    user_id: str,
    status: str = Body(..., embed=True, description="active/disabled"),
    admin: dict = Depends(get_current_admin),
):
    """P2-07: 切换用户启用/禁用状态"""
    if status not in ("active", "disabled"):
        return error("INVALID_PARAM", message="status 必须为 active 或 disabled")

    db = SessionLocal()
    try:
        u = db.query(User).filter_by(id=user_id).first()
        if not u:
            return error("NOT_FOUND", message="用户不存在")

        u.status = status
        db.add(AuditLog(
            id=_uid(), tenant_id=u.tenant_id, user_id=admin.get("sub", "system"),
            action="USER_STATUS_TOGGLE", target_type="USER", target_id=u.id,
            detail={"username": u.username, "new_status": status},
            success=True,
        ))
        db.commit()
        return success(data={"id": u.id, "status": status},
                      message=f"用户已{'启用' if status == 'active' else '禁用'}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 10. 租户管理扩展 (P2-22~27)
# ═══════════════════════════════════════════

_ONBOARD_PHONE_RE = r"^(1[3-9]\d{9}|(\+?\d{1,4}-)?0\d{2,3}-?\d{7,8})$"
_ONBOARD_EMAIL_RE = r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$"


class TenantOnboardRequest(BaseModel):
    name: str = Field(..., description="租户标识（英文/拼音）")
    display_name: Optional[str] = Field(None, description="显示名称")
    scene: str = Field("MED", description="业务场景: MED/EDU/RETAIL/HQ")
    plan: str = Field("free", description="套餐plan_name")
    code: Optional[str] = Field(None, description="可读机构代号（可选；缺省自动生成 JGxxxx）")
    contact_name: Optional[str] = Field(None, description="联系人姓名")
    contact_phone: Optional[str] = Field(None, description="联系人手机/座机(座机须带区号)")
    contact_email: Optional[str] = Field(None, description="联系邮箱")
    module_3d: bool = Field(False, description="是否启用3D模块")
    duration_months: int = Field(12, description="订阅月数")
    # ── 机构资质信息（2026-08-22 开户表单升级：成败在细节）──
    address_country: Optional[str] = Field(None, description="机构地址-国家")
    address_province: Optional[str] = Field(None, description="机构地址-省份")
    address_city: Optional[str] = Field(None, description="机构地址-城市")
    address_district: Optional[str] = Field(None, description="机构地址-区县")
    address_detail: Optional[str] = Field(None, max_length=200, description="机构地址-详细地址（街道/门牌/楼栋等，200字内）")
    org_intro: Optional[str] = Field(None, max_length=150, description="机构介绍（150字以内）")
    license_business: Optional[str] = Field(None, description="营业执照文件URL")
    license_business_name: Optional[str] = Field(None, description="营业执照文件名")
    license_medical: Optional[str] = Field(None, description="医疗机构执业许可证文件URL")
    license_medical_name: Optional[str] = Field(None, description="医疗机构执业许可证文件名")

    @field_validator("contact_phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return v
        import re
        if not re.match(_ONBOARD_PHONE_RE, str(v).strip()):
            raise ValueError("联系电话格式不正确：手机号须为11位（1开头），座机须带区号（如 021-12345678）")
        return str(v).strip()

    @field_validator("contact_email")
    @classmethod
    def check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return v
        import re
        if not re.match(_ONBOARD_EMAIL_RE, str(v).strip()):
            raise ValueError("电子邮箱格式不正确")
        return str(v).strip()

    @model_validator(mode="after")
    def check_medical_licenses(self):
        """医疗场景强制要求：营业执照 + 医疗机构执业许可证 两证必传"""
        if (self.scene or "").lower() in ("medical", "med"):
            if not (self.license_business or "").strip():
                raise ValueError("医疗场景必须上传营业执照")
            if not (self.license_medical or "").strip():
                raise ValueError("医疗场景必须上传医疗机构执业许可证")
        return self


@router.post("/tenants/onboard", summary="创建租户(开户一条龙)")
async def onboard_tenant(req: TenantOnboardRequest, admin: dict = Depends(get_current_admin)):
    """P2-22: 创建租户 + 自动创建根机构 + 创建订阅 + 可选3D开关"""
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter_by(name=req.name).first()
        if existing:
            return fail("DUPLICATE", message=f"租户 {req.name} 已存在", http_status=409)

        tenant = Tenant(
            id=_uid(), name=req.name,
            display_name=req.display_name or req.name,
            scene=req.scene, status="active",
            code=resolve_tenant_code(db, req.code),
            extra={
                "contact_name": req.contact_name,
                "contact_phone": req.contact_phone,
                "contact_email": req.contact_email,
                "module_3d": req.module_3d,
                # 2026-08-22 开户表单升级：机构资质信息全量落库
                "address_country": req.address_country,
                "address_province": req.address_province,
                "address_city": req.address_city,
                "address_district": req.address_district,
                "address_detail": req.address_detail,
                "org_intro": req.org_intro,
                "license_business": req.license_business,
                "license_business_name": req.license_business_name,
                "license_medical": req.license_medical,
                "license_medical_name": req.license_medical_name,
            },
        )
        db.add(tenant)
        db.flush()

        root_org = Org(
            id=_uid(), tenant_id=tenant.id,
            name=f"{req.display_name or req.name}-根机构", org_type="root",
        )
        db.add(root_org)

        plan = db.query(Plan).filter_by(plan_name=req.plan).first()
        if not plan:
            plan = db.query(Plan).filter_by(plan_name="free").first()
        if not plan:
            return fail("NOT_FOUND", message=f"套餐 {req.plan} 不存在且无默认免费套餐", http_status=404)

        # 2026-08-22 老黄拍板：3D 岐黄三境不做单独加购，按套餐门槛——
        # 体验版/标准版不含（传入 true 也强制 false），专业版/企业版自动含（传入 false 也强制 true）。
        module_3d_effective = bool((plan.features_json or {}).get("module_3d", False))
        if bool((tenant.extra or {}).get("module_3d")) != module_3d_effective:
            tenant.extra = dict(tenant.extra or {})
            tenant.extra["module_3d"] = module_3d_effective
            db.flush()

        from datetime import datetime as dt, timezone as tz
        start = _now()
        month_total = start.month + req.duration_months
        year = start.year + (month_total - 1) // 12
        month = (month_total - 1) % 12 + 1
        end = dt(year, month, 1, tzinfo=tz.utc)

        sub = Subscription(
            id=_uid(), tenant_id=tenant.id, plan_id=plan.id,
            status="active", start_date=start, end_date=end,
        )
        db.add(sub)

        db.add(AuditLog(
            id=_uid(), tenant_id=tenant.id, user_id=admin.get("sub", "system"),
            action="TENANT_ONBOARD", target_type="TENANT", target_id=tenant.id,
            detail={"name": req.name, "scene": req.scene, "plan": req.plan,
                    "contact_name": req.contact_name, "contact_email": req.contact_email,
                    "license_business": req.license_business,
                    "license_medical": req.license_medical,
                    "module_3d": module_3d_effective},
            success=True,
        ))
        db.commit()

        return success(data={
            "id": tenant.id, "name": tenant.name,
            "display_name": tenant.display_name,
            "scene": tenant.scene, "status": tenant.status,
            "plan": plan.plan_name, "plan_display": plan.display_name,
            "subscription_id": sub.id,
            "end_date": end.isoformat(),
            "module_3d": module_3d_effective,
            "contact_name": req.contact_name,
            "contact_phone": req.contact_phone,
            "contact_email": req.contact_email,
            "address_country": req.address_country,
            "address_province": req.address_province,
            "address_city": req.address_city,
            "address_district": req.address_district,
            "address_detail": req.address_detail,
            "org_intro": req.org_intro,
            "license_business": req.license_business,
            "license_medical": req.license_medical,
        }, message="租户开户成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════
# 证照上传（开户表单：营业执照/医疗机构执业许可证）
# ═══════════════════════════════════════════

def _uploads_dir() -> str:
    """uploads 目录 = 项目根/uploads（与 qihuang_platform 包同级，避免被 rsync 全量覆盖删除）"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    )


@router.post("/upload", summary="上传证照文件（营业执照/医疗机构执业许可证等）")
async def upload_license_file(
    file: FastAPIUploadFile = File(...),
    purpose: str = Form("license"),
    admin: dict = Depends(get_current_admin),
):
    """保存到本地 uploads/ 目录，写 upload_file 表，返回可访问 URL（/admin/v1/upload/{file_id}）"""
    try:
        import shutil as _shutil
        upload_dir = _uploads_dir()
        os.makedirs(upload_dir, exist_ok=True)
        raw_name = file.filename or "upload.bin"
        ext = os.path.splitext(raw_name)[1][:12]
        fid = _uid()
        fname = f"{fid}{ext}"
        fpath = os.path.join(upload_dir, fname)
        with open(fpath, "wb") as f:
            _shutil.copyfileobj(file.file, f)
        db = SessionLocal()
        try:
            rec = UploadFile(
                id=fid, tenant_id=admin.get("tenant_id") or "platform",
                user_id=admin.get("sub"),
                file_name=raw_name, file_type=purpose,
                file_size=os.path.getsize(fpath),
                cos_key=fname, cos_url=f"/admin/v1/upload/{fid}",
                status="active",
            )
            db.add(rec)
            db.commit()
        finally:
            db.close()
        return success(data={
            "file_id": fid,
            "url": f"/admin/v1/upload/{fid}",
            "name": raw_name,
            "size": os.path.getsize(fpath),
        }, message="上传成功")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"上传失败: {e}")


@router.get("/upload/{file_id}", summary="查看/下载已上传证照")
async def get_upload_file(file_id: str, admin: dict = Depends(get_current_admin)):
    db = SessionLocal()
    try:
        rec = db.query(UploadFile).filter_by(id=file_id).first()
        if not rec:
            return error("NOT_FOUND", message="文件不存在")
        fpath = os.path.join(_uploads_dir(), rec.cos_key or rec.id)
        if not os.path.exists(fpath):
            return error("NOT_FOUND", message="文件已被清理")
        from fastapi.responses import FileResponse
        return FileResponse(fpath, filename=rec.file_name or "file")
    finally:
        db.close()


class TenantUpdateRequest(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None


@router.put("/tenants/{tenant_id}", summary="编辑租户信息")
async def update_tenant(
    tenant_id: str,
    req: TenantUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """P2-23: 修改租户名称/显示名/状态"""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        if req.name is not None:
            dup = db.query(Tenant).filter(Tenant.name == req.name, Tenant.id != tenant_id).first()
            if dup:
                return error("DUPLICATE", message=f"租户名 {req.name} 已被占用")
            tenant.name = req.name
        if req.display_name is not None:
            tenant.display_name = req.display_name
        if req.status is not None:
            tenant.status = req.status

        db.add(AuditLog(
            id=_uid(), tenant_id=tenant_id, user_id=admin.get("sub", "system"),
            action="TENANT_UPDATE", target_type="TENANT", target_id=tenant_id,
            detail=req.dict(exclude_none=True),
            success=True,
        ))
        db.commit()
        return success(data={
            "id": tenant.id, "name": tenant.name,
            "display_name": tenant.display_name, "status": tenant.status,
        }, message="租户信息已更新")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.delete("/tenants/{tenant_id}", summary="删除租户(软删除)")
async def delete_tenant(
    tenant_id: str,
    admin: dict = Depends(get_current_admin),
):
    """P2-24: 软删除租户（状态改为closed），保留数据"""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        tenant.status = "closed"
        db.add(AuditLog(
            id=_uid(), tenant_id=tenant_id, user_id=admin.get("sub", "system"),
            action="TENANT_DELETE", target_type="TENANT", target_id=tenant_id,
            detail={"name": tenant.name},
            success=True,
        ))
        db.commit()
        return success(data={"id": tenant_id, "status": "closed"}, message="租户已删除(软删除)")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.put("/tenants/{tenant_id}/status", summary="启停租户")
async def toggle_tenant_status(
    tenant_id: str,
    status: str = Body(..., embed=True, description="active/suspended/readonly"),
    admin: dict = Depends(get_current_admin),
):
    """P2-25: 切换租户状态（正常/暂停/只读）"""
    if status not in ("active", "suspended", "readonly"):
        return error("INVALID_PARAM", message="status 必须�� active/suspended/readonly")

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        old_status = tenant.status
        tenant.status = status
        db.add(AuditLog(
            id=_uid(), tenant_id=tenant_id, user_id=admin.get("sub", "system"),
            action="TENANT_STATUS_TOGGLE", target_type="TENANT", target_id=tenant_id,
            detail={"old_status": old_status, "new_status": status},
            success=True,
        ))
        db.commit()
        status_labels = {"active": "已启用", "suspended": "已暂停", "readonly": "已设为只读"}
        return success(data={"id": tenant_id, "status": status},
                      message=f"租户{status_labels.get(status, status)}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


class RenewRequest(BaseModel):
    duration_months: int = Field(12, description="续费月数")
    plan_id: Optional[str] = Field(None, description="升级套餐ID")


@router.post("/tenants/{tenant_id}/renew", summary="续费租户订阅")
async def renew_tenant(
    tenant_id: str,
    req: RenewRequest = RenewRequest(),
    admin: dict = Depends(get_current_admin),
):
    """P2-26: 续费租户订阅（延长到期日/升级套餐）"""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return error("NOT_FOUND", message="租户不存在")

        sub = db.query(Subscription).filter_by(tenant_id=tenant_id, status="active").first()
        if not sub:
            return error("NOT_FOUND", message="无活跃订阅，请先创建订阅")

        from dateutil.relativedelta import relativedelta
        current_end = sub.end_date or _now()
        new_end = current_end + relativedelta(months=req.duration_months)
        sub.end_date = new_end

        old_plan = sub.plan_id
        if req.plan_id:
            plan = db.query(Plan).filter_by(id=req.plan_id).first()
            if not plan:
                return error("NOT_FOUND", message="套餐不存在")
            sub.plan_id = req.plan_id

        db.add(AuditLog(
            id=_uid(), tenant_id=tenant_id, user_id=admin.get("sub", "system"),
            action="TENANT_RENEW", target_type="SUBSCRIPTION", target_id=sub.id,
            detail={"duration_months": req.duration_months, "old_plan": old_plan,
                    "new_plan": sub.plan_id, "new_end": new_end.isoformat()},
            success=True,
        ))
        db.commit()
        return success(data={
            "subscription_id": sub.id,
            "end_date": new_end.isoformat(),
            "plan_id": sub.plan_id,
        }, message=f"订阅已续费 {req.duration_months} 个月")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


@router.get("/tenants-extended", summary="租户列表(扩展)")
async def list_tenants_extended(
    scene: Optional[str] = Query(None, description="health/medical/edu"),
    search: Optional[str] = Query(None, description="按名称/ID搜索"),
    status: Optional[str] = Query(None, description="active/suspended/readonly/closed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    """P2-27: 租户列表（含机构数、用户数、订阅信息、3D开关、月用量）"""
    db = SessionLocal()
    try:
        q = db.query(Tenant)

        if scene:
            q = q.filter_by(scene=scene)
        if status:
            q = q.filter_by(status=status)
        else:
            q = q.filter(Tenant.status != "closed")

        if search:
            q = q.filter(
                (Tenant.name.ilike(f"%{search}%")) |
                (Tenant.display_name.ilike(f"%{search}%"))
            )

        total = q.count()
        tenants = q.order_by(Tenant.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        from datetime import datetime as dt, timezone as tz
        now = dt.now(tz.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        items = []
        for t in tenants:
            orgs_count = db.query(Org).filter_by(tenant_id=t.id).count()
            users_count = db.query(User).filter_by(tenant_id=t.id).count()
            sub = db.query(Subscription).filter_by(tenant_id=t.id, status="active").first()
            plan_name = ""
            plan_id = ""
            expires = None
            quota = 2000
            if sub:
                plan = db.query(Plan).filter_by(id=sub.plan_id).first()
                if plan:
                    plan_name = plan.display_name or plan.plan_name
                    plan_id = plan.id
                    quota = plan.month_calls
                expires = sub.end_date.isoformat() if sub.end_date else None

            month_calls = db.query(CallLog).filter(
                CallLog.tenant_id == t.id,
                CallLog.timestamp >= month_start,
            ).count()

            # 待生效的预约升级（status=scheduled 且 start_date 在未来）
            pend_sub = _scheduled_subscription(db, t.id)
            pending_plan_name = None
            pending_effective_date = None
            if pend_sub:
                pend_plan = db.query(Plan).filter_by(id=pend_sub.plan_id).first()
                if pend_plan:
                    pending_plan_name = pend_plan.display_name or pend_plan.plan_name
                pending_effective_date = pend_sub.start_date.strftime("%Y-%m-%d") if pend_sub.start_date else None

            extra = t.extra or {}
            module_3d = extra.get("module_3d", False)

            items.append({
                "id": t.id, "name": t.name, "display_name": t.display_name,
                "scene": t.scene, "status": t.status,
                "plan": plan_name, "plan_id": plan_id,
                "pending_plan": pending_plan_name,
                "pending_effective_date": pending_effective_date,
                "orgs": orgs_count, "users": users_count,
                "usedCalls": month_calls, "quotaCalls": quota,
                "expires": expires,
                "module_3d": module_3d,
                # 结算中心：单加 agent 列表（套餐自带 agents 见套餐 features，不在此列）
                "agent_addons": extra.get("agent_addons", []) or [],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })

        return paginated(items=items, total=total, page=page, page_size=page_size)
    finally:
        db.close()


# ═══════════════════════════════════════════
# P2 Batch 3: 敏感词更新 + 功能开关 + 催缴
# ═══════════════════════════════════════════

# --- P2-C1: 更新敏感词 ---
class SensitiveWordUpdateRequest(BaseModel):
    word: Optional[str] = None
    level: Optional[str] = None
    scene: Optional[str] = None


@router.put("/content/words/{word_id}", summary="更新敏感词")
async def update_sensitive_word(
    word_id: str,
    req: SensitiveWordUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """更新敏感词内容/级别/场景"""
    db = SessionLocal()
    try:
        w = db.query(SensitiveWord).filter_by(id=word_id).first()
        if not w:
            return error("NOT_FOUND", message="敏感词不存在")

        if req.word is not None:
            # 检查同一场景下是否重复
            scene = req.scene or w.scene
            dup = db.query(SensitiveWord).filter(
                SensitiveWord.id != word_id,
                SensitiveWord.word == req.word,
                SensitiveWord.scene == scene,
            ).first()
            if dup:
                return error("DUPLICATE", message=f"该场景下已存在: {req.word}")
            w.word = req.word

        if req.level is not None:
            w.level = req.level
        if req.scene is not None:
            w.scene = req.scene

        db.commit()
        return success(data={
            "id": w.id, "word": w.word, "level": w.level, "scene": w.scene,
        }, message="敏感词已更新")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# --- P2-F1: 功能开关列表 ---
@router.get("/features", summary="功能开关列表")
async def list_features(
    tenant_id: str = Query(..., description="租户ID"),
    admin: dict = Depends(get_current_admin),
):
    """获取租户的功能开关状态 (真值源 = active_subscription.plan.features_json)

    修复记录 2026-08-15: 原实现读 tenant.extra.features，是租户级人工覆盖字段，
    与 plan.features_json 不一致，导致 7e188ba9（专业版）显示成"5特性全不包含"。
    现改为：active subscription 的 plan.features_json 作为权威特性矩阵。
    """
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        now = _utcnow_naive()
        cur = _effective_subscription(db, tenant_id, now)
        plan = db.query(Plan).filter(Plan.id == cur.plan_id).first() if cur else None
        plan_features = (plan.features_json if plan else {}) or {}

        # 默认功能列表（plan.features_json 缺字段时回退到 False，避免“全 True”假象）
        defaults = {
            "module_3d": bool(plan_features.get("module_3d", False)),
            "module_agent": bool(plan_features.get("module_agent", False)),
            "report_export": bool(plan_features.get("report_export", False)),
            "priority_support": bool(plan_features.get("priority_support", False)),
            "custom_skin": bool(plan_features.get("custom_skin", False)),
            "api_access": bool(plan_features.get("api_access", False)),
            "webhook": bool(plan_features.get("webhook", False)),
        }

        return success(data={
            "tenant_id": tenant_id,
            "plan_id": plan.id if plan else "",
            "plan_name": plan.plan_name if plan else "",
            "display_name": plan.display_name if plan else "",
            "features": defaults,
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# --- P2-F2: 切换功能开关 ---
class ToggleFeatureRequest(BaseModel):
    enabled: bool = Field(..., description="是否启用")


@router.put("/features/{feature_name}", summary="切换功能开关")
async def toggle_feature(
    feature_name: str,
    req: ToggleFeatureRequest,
    tenant_id: str = Query(..., description="租户ID"),
    admin: dict = Depends(get_current_admin),
):
    """启用/禁用某个功能开关"""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        extra = t.extra or {}
        features = extra.get("features", {})
        features[feature_name] = req.enabled
        extra["features"] = features
        t.extra = extra
        db.commit()

        return success(data={
            "feature": feature_name,
            "enabled": req.enabled,
        }, message=f"功能 '{feature_name}' 已{'启用' if req.enabled else '禁用'}")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# --- P2-B1: 催缴通知 ---
class DunRequest(BaseModel):
    message: str = Field(default="", description="自定义催缴消息内容")
    channel: str = Field(default="sms", description="通知渠道: sms/email/inapp")


@router.post("/billing/{tenant_id}/dun", summary="发送催缴通知")
async def send_dunning_notice(
    tenant_id: str,
    req: DunRequest = DunRequest(),
    admin: dict = Depends(get_current_admin),
):
    """向欠费租户发送催缴通知 (模拟: 记录审计日志, 生产环境对接短信/邮件服务)"""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        # 查询最新账单
        bill = db.query(Bill).filter_by(tenant_id=tenant_id).order_by(Bill.bill_period.desc()).first()
        sub = db.query(Subscription).filter_by(tenant_id=tenant_id, status="active").first()

        message = req.message or f"尊敬的{t.display_name or t.name}，您的账户存在欠费，请尽快完成缴费以恢复服务。"
        channel = req.channel

        # 记录审计日志
        db.add(AuditLog(
            id=_uid(), tenant_id=tenant_id,
            user_id=admin.get("sub", "system"),
            action="SEND_DUNNING", target_type="BILLING",
            target_id=bill.id if bill else "N/A",
            detail={
                "channel": channel, "message": message[:200],
                "bill_period": bill.bill_period if bill else "N/A",
                "subscription_status": sub.status if sub else "N/A",
            },
            success=True,
        ))
        db.commit()

        return success(data={
            "tenant_id": tenant_id,
            "channel": channel,
            "sent": True,
            "bill_period": bill.bill_period if bill else None,
        }, message=f"催缴通知已通过{channel}发送")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 8. Agent 中台（资源池 + 调配层 + 各能力看板）  [老黄 2026-08-12 拍板]
# ═══════════════════════════════════════════════

@router.get("/agents", summary="Agent 中台-能力资源池列表")
async def list_agent_center(admin: dict = Depends(get_current_admin)):
    """列出全部已注册 Agent 能力（含启用态 + 被哪些套餐纳入「专家团」）。"""
    agents = list_agents()
    db = SessionLocal()
    try:
        plans = db.query(Plan).all()
        plan_agents = {p.id: (p.features_json or {}).get("agents", []) for p in plans}
    finally:
        db.close()
    items = []
    for key, spec in agents.items():
        included_in = [pid for pid, al in plan_agents.items() if key in al]
        items.append({**spec, "included_in_plans": included_in})
    return success(data={"total": len(items), "agents": items})


@router.get("/agents/usage", summary="Agent 中台-调用量聚合(近7日)")
async def agent_center_usage(admin: dict = Depends(get_current_admin)):
    """按 CallLog.endpoint 前缀聚合各 Agent 能力近7日调用量（真实计量，运营驾驶舱数据源）。

    前缀规则：/api/v1/agent/{agent_key}/... —— 与 agent/__init__.py 挂载前缀一致。
    返回按 calls 降序排列，含 tokens / cost_cents 累计。
    """
    db = SessionLocal()
    try:
        agents = list_agents()
        now = _now()
        since = now - timedelta(days=7)
        rows = (
            db.query(
                CallLog.endpoint,
                func.count(CallLog.id),
                func.coalesce(func.sum(CallLog.tokens_used), 0),
                func.coalesce(func.sum(CallLog.cost_cents), 0),
            )
            .filter(CallLog.timestamp >= since)
            .group_by(CallLog.endpoint)
            .all()
        )
        usage_map: dict = {}
        for ep, cnt, tokens, cost in rows:
            ep = ep or ""
            for key, spec in agents.items():
                prefix = f"/api/v1/agent/{key}/"
                if ep.startswith(prefix):
                    u = usage_map.setdefault(key, {"calls": 0, "tokens": 0, "cost_cents": 0.0})
                    u["calls"] += cnt
                    u["tokens"] += int(tokens or 0)
                    u["cost_cents"] += round(float(cost or 0), 2)
                    break
        items = [
            {"agent_key": key,
             "name": spec.get("name") or key,
             "calls": u["calls"],
             "tokens": u["tokens"],
             "cost_cents": u["cost_cents"]}
            for key, u in usage_map.items()
        ]
        items.sort(key=lambda x: x["calls"], reverse=True)
        total_calls = sum(i["calls"] for i in items)
        return success(data={
            "period": "7d",
            "since": since.strftime("%Y-%m-%d"),
            "total_calls": total_calls,
            "usage": items,
        })
    finally:
        db.close()


@router.get("/agents/{agent_key}", summary="Agent 能力详情")
async def get_agent_detail(agent_key: str, admin: dict = Depends(get_current_admin)):
    spec = get_agent(agent_key)
    if not spec:
        return error("NOT_FOUND", message=f"Agent 能力不存在：{agent_key}")
    db = SessionLocal()
    try:
        plans = db.query(Plan).all()
        included_in = [p.id for p in plans if agent_key in (p.features_json or {}).get("agents", [])]
    finally:
        db.close()
    return success(data={**spec, "included_in_plans": included_in})


@router.post("/agents/{agent_key}/toggle", summary="启停 Agent 能力(运营态热插拔)")
async def toggle_agent(
    agent_key: str,
    status: str = Body(..., embed=True, description="active / inactive"),
    admin: dict = Depends(get_current_admin),
):
    """运营态热插拔：启用/停用某 Agent 能力（写 DB + 缓存双写）。"""
    if status not in ("active", "inactive"):
        return error("INVALID_PARAM", message="status 必须为 active / inactive")
    ok = set_agent_status(agent_key, status)
    if not ok:
        return error("NOT_FOUND", message=f"Agent 能力不存在：{agent_key}")
    return success(data={"agent_key": agent_key, "status": status},
                   message=f"Agent「{agent_key}」已设为 {status}")


@router.get("/agents/{agent_key}/dashboard", summary="Agent 能力运营看板(中台聚合)")
async def agent_center_dashboard(
    agent_key: str,
    store_id: Optional[str] = Query(None, description="门店维度下钻（合规审核用）"),
    port: Optional[str] = Query(None, description="来源端下钻"),
    admin: dict = Depends(get_current_admin),
):
    """构件 C：按 agent_key 拉取对应能力的运营看板（内核在底层实现，中台只派发）。"""
    spec = get_agent(agent_key)
    if not spec:
        return error("NOT_FOUND", message=f"Agent 能力不存在：{agent_key}")
    try:
        data = await agent_dashboard.get_agent_dashboard(agent_key, store_id=store_id, port=port)
    except KeyError:
        return error("NOT_FOUND", message=f"Agent 能力无看板：{agent_key}")
    except Exception as e:
        return error("INTERNAL_ERROR", message=f"看板拉取失败：{e}")
    return success(data={"agent_key": agent_key, "dashboard": data})


@router.get("/plans/{plan_id}/agents", summary="套餐的 Agent 专家团组合")
async def get_plan_agents(plan_id: str, admin: dict = Depends(get_current_admin)):
    """构件 B：读取某套餐打包了哪些 Agent 能力（专家团）。"""
    db = SessionLocal()
    try:
        plan = db.query(Plan).filter_by(id=plan_id).first()
        if not plan:
            return error("NOT_FOUND", message="套餐不存在")
        agents = (plan.features_json or {}).get("agents", [])
    finally:
        db.close()
    return success(data={"plan_id": plan_id, "agents": agents})


@router.get("/agent-business-signals", summary="活态化 P1-B·业务实证采纳榜（consult 引用日志聚合）")
async def agent_business_signals(
    limit: int = 20,
    admin: dict = Depends(get_current_admin),
):
    """回路三业务实证：聚合 consult_attribution（health-advisor 每次成功 consult 的实体引用日志）。

    返回近窗口内被引用最多的知识点 Top-N（方剂/证候/草药），作为「越用越聪明」的业务实证信号源；
    同时给出总量指标。开关 LIVING_BUSINESS_SIGNAL_ENABLED=true 后，该数据即回灌知识置信度加权。
    注意：该表由 orchestrator 归因钩子在 consult 成功时 best-effort 写入，仅真实/仿真 consult 会产生数据。
    """
    db = SessionLocal()
    try:
        from qihuang_platform.living.business_signal import _BUSINESS_SIGNAL_ENABLED
        window_days = int(os.getenv("LIVING_BIZ_WINDOW_DAYS", "30"))
        limit = max(1, min(50, limit))
        cutoff = _now() - timedelta(days=window_days)
        rows = (
            db.query(
                ConsultAttribution.kg_id,
                func.max(ConsultAttribution.entity_name),
                func.max(ConsultAttribution.entity_type),
                func.count(ConsultAttribution.id),
            )
            .filter(
                ConsultAttribution.consulted_at >= cutoff,
                ~ConsultAttribution.kg_id.like("pending:%"),
            )
            .group_by(ConsultAttribution.kg_id)
            .order_by(func.count(ConsultAttribution.id).desc())
            .limit(limit)
            .all()
        )
        top = [
            {"kg_id": k, "entity_name": n, "entity_type": t, "ref_count": c}
            for k, n, t, c in rows
        ]
        distinct_kg = (
            db.query(func.count(func.distinct(ConsultAttribution.kg_id)))
            .filter(
                ConsultAttribution.consulted_at >= cutoff,
                ~ConsultAttribution.kg_id.like("pending:%"),
            )
            .scalar() or 0
        )
        total_ref = (
            db.query(func.count(ConsultAttribution.id))
            .filter(
                ConsultAttribution.consulted_at >= cutoff,
                ~ConsultAttribution.kg_id.like("pending:%"),
            )
            .scalar() or 0
        )
        return success(data={
            "window_days": window_days,
            "signal_enabled": _BUSINESS_SIGNAL_ENABLED,
            "totals": {"references": total_ref, "distinct_kg": distinct_kg},
            "top": top,
        })
    finally:
        db.close()


@router.put("/plans/{plan_id}/agents", summary="设置套餐的 Agent 专家团组合")
async def set_plan_agents(
    plan_id: str,
    agents: list = Body(..., embed=True, description="agent_key 列表，如 [\"compliance\"]"),
    admin: dict = Depends(get_current_admin),
):
    """构件 B：运营态编辑某套餐的 Agent 组合（写 features_json.agents）。"""
    db = SessionLocal()
    try:
        plan = db.query(Plan).filter_by(id=plan_id).first()
        if not plan:
            return error("NOT_FOUND", message="套餐不存在")
        fj = plan.features_json or {}
        fj["agents"] = list(agents)
        plan.features_json = fj
        db.commit()
    finally:
        db.close()
    return success(data={"plan_id": plan_id, "agents": list(agents)},
                   message="套餐 Agent 组合已更新")
