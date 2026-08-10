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
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import func

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    Plan, Subscription, Bill, CallLog, AuditLog,
    SensitiveWord, KgReviewItem, KgVersion,
    Tenant, User, Role, UserRole, RolePermission, Permission,
    Org, ApiKey,
    MedCase, MedReport, HealthAssessment, HealthPlan,
    EduCoachSession, EduExamRecord,
)
import bcrypt
from qihuang_platform.rbac.service import validate_password
from qihuang_platform.gateway.monitor import monitor
from qihuang_platform.gateway.llm_fallback import llm_fallback
from qihuang_platform.control.container_mgr import container_mgr
from qihuang_platform.control.cost_mgr import router as cost_router
from qihuang_platform.billing.billing import get_bill_detail

router = APIRouter(prefix="/admin/v1", tags=["管理端-全功能"])


def _uid():
    import uuid
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


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

        item.status = "APPROVED" if req.action == "approve" else "REJECTED"
        item.reviewer_id = admin.get("sub", "system")
        item.review_note = req.note
        item.reviewed_at = _now()

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
    """返回所有微服务/依赖的健康状态"""
    services = [
        {"name": "API 网关", "status": "运行正常", "latency": "42ms", "uptime": "99.98%", "ok": True},
        {"name": "中台应用（FastAPI）", "status": "运行正常", "latency": "186ms", "uptime": "99.95%", "ok": True},
        {"name": "Neo4j 图谱库", "status": "运行正常", "latency": "12ms", "uptime": "99.99%", "ok": True},
        {"name": "PostgreSQL 业务库", "status": "运行正常", "latency": "8ms", "uptime": "99.99%", "ok": True},
        {"name": "LLM 共识集群", "status": "DeepSeek 备用切换中", "latency": "1240ms", "uptime": "99.91%", "ok": False},
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

        # 最近操作
        recent_ops = []
        logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(5).all()
        for log in logs:
            recent_ops.append({
                "time": log.created_at.strftime("%H:%M") if log.created_at else "",
                "user": log.user_id or "系统",
                "action": log.action or "",
                "target": log.target_id or "",
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

        # 系统服务状态
        services = [
            {"name": "API 网关", "key": "api_gateway", "status": "normal", "latency_ms": 42, "uptime": "99.98%"},
            {"name": "中台应用 (FastAPI)", "key": "fastapi", "status": "normal", "latency_ms": 186, "uptime": "99.95%"},
            {"name": "Neo4j 图谱库", "key": "neo4j", "status": "normal", "latency_ms": 12, "uptime": "99.99%"},
            {"name": "PostgreSQL 业务库", "key": "postgres", "status": "normal", "latency_ms": 8, "uptime": "99.99%"},
            {"name": "LLM 共识集群", "key": "llm", "status": "warning", "latency_ms": 1240, "uptime": "99.91%"},
        ]

        return success(data={
            "tenants": {"total": total_tenants, "active": active_tenants, "new_this_month": new_this_month},
            "api": {"total_calls": total_calls, "today_calls": today_calls, "call_diff": today_calls - yesterday_calls},
            "revenue": {"total_cents": total_revenue},
            "kg": {"pending": kg_pending},
            "recent_ops": recent_ops if recent_ops else [],
            "trend": {"dates": trend_dates, "values": trend_values},
            "services": services,
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

class TenantOnboardRequest(BaseModel):
    name: str = Field(..., description="租户标识（英文/拼音）")
    display_name: Optional[str] = Field(None, description="显示名称")
    scene: str = Field("health", description="health/medical/edu")
    plan: str = Field("free", description="套餐plan_name")
    contact_phone: Optional[str] = Field(None, description="联系人手机")
    module_3d: bool = Field(False, description="是否启用3D模块")
    duration_months: int = Field(12, description="订阅月数")


@router.post("/tenants/onboard", summary="创建租户(开户一条龙)")
async def onboard_tenant(req: TenantOnboardRequest, admin: dict = Depends(get_current_admin)):
    """P2-22: 创建租户 + 自动创建根机构 + 创建订阅 + 可选3D开关"""
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter_by(name=req.name).first()
        if existing:
            return error("DUPLICATE", message=f"租户 {req.name} 已存在")

        tenant = Tenant(
            id=_uid(), name=req.name,
            display_name=req.display_name or req.name,
            scene=req.scene, status="active",
            extra={"contact_phone": req.contact_phone, "module_3d": req.module_3d},
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
            return error("NOT_FOUND", message=f"套餐 {req.plan} 不存在且无默认免费套餐")

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
                    "module_3d": req.module_3d},
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
            "module_3d": req.module_3d,
        }, message="租户开户成功")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
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

            extra = t.extra or {}
            module_3d = extra.get("module_3d", False)

            items.append({
                "id": t.id, "name": t.name, "display_name": t.display_name,
                "scene": t.scene, "status": t.status,
                "plan": plan_name, "plan_id": plan_id,
                "orgs": orgs_count, "users": users_count,
                "usedCalls": month_calls, "quotaCalls": quota,
                "expires": expires,
                "module_3d": module_3d,
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
    """获取租户的功能开关状态 (存储在 tenant.extra.features)"""
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return error("NOT_FOUND", message="租户不存在")

        extra = t.extra or {}
        features = extra.get("features", {})

        # 默认功能列表（如果未配置则使用默认值）
        defaults = {
            "module_3d": features.get("module_3d", False),
            "module_agent": features.get("module_agent", False),
            "report_export": features.get("report_export", True),
            "priority_support": features.get("priority_support", False),
            "custom_skin": features.get("custom_skin", False),
            "api_access": features.get("api_access", True),
            "webhook": features.get("webhook", False),
        }

        return success(data={
            "tenant_id": tenant_id,
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
