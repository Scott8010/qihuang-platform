"""
客户运营管理模块 — 为运营端 customers Tab 提供API

端点：
  GET  /admin/v1/customers            — 客户列表+统计
  GET  /admin/v1/customers/{id}       — 客户详情
  GET  /admin/v1/customers/stats      — 客户统计
  GET  /admin/v1/customers/at-risk    — 流失风险客户
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Tenant, Subscription, CallLog, Bill
from qihuang_platform.gateway.deps import admin_required

router = APIRouter(prefix="/admin/v1/customers", tags=["运营端-客户管理"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/stats", summary="客户统计概览")
async def customer_stats(user=Depends(admin_required), db: Session = Depends(get_db)):
    """返回总客户数、活跃客户、流失风险等统计"""
    total = db.query(Tenant).count()
    # 活跃客户：30天内有调用记录的租户
    cutoff = datetime.utcnow() - timedelta(days=30)
    active_subq = db.query(CallLog.tenant_id).filter(CallLog.timestamp >= cutoff).distinct().subquery()
    active_count = db.query(Tenant).filter(Tenant.id.in_(db.query(active_subq.c.tenant_id))).count()
    # 流失风险：有过订阅但30天内无调用
    risk_count = max(0, total - active_count)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "total": total,
            "active": active_count,
            "at_risk": risk_count,
            "new_this_month": db.query(Tenant).filter(
                Tenant.created_at >= datetime.utcnow().replace(day=1)
            ).count(),
        }
    }


@router.get("", summary="客户列表")
async def customer_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    scenario: str = Query(None, description="场景筛选: HEALTH/MED/EDU"),
    sort_by: str = Query("created_at", description="排序字段"),
    user=Depends(admin_required),
    db: Session = Depends(get_db),
):
    """客户列表，含套餐、调用量、场景等信息"""
    query = db.query(Tenant)
    if scenario:
        query = query.filter(Tenant.scene == scenario)

    # 排序
    if sort_by == "name":
        query = query.order_by(Tenant.display_name)
    elif sort_by == "calls":
        query = query.order_by(Tenant.id)  # fallback
    else:
        query = query.order_by(Tenant.created_at.desc())

    total = query.count()
    tenants = query.offset((page - 1) * page_size).limit(page_size).all()

    cutoff = datetime.utcnow() - timedelta(days=30)
    items = []
    for t in tenants:
        # 获取订阅
        sub = db.query(Subscription).filter(
            Subscription.tenant_id == t.id,
            Subscription.status == "active"
        ).first()
        plan_name = sub.plan_id if sub else "无"
        # 30天调用量
        calls_30d = db.query(CallLog).filter(
            CallLog.tenant_id == t.id,
            CallLog.timestamp >= cutoff
        ).count()
        # 剩余天数（模型字段为 end_date，对外沿用 expires_at 契约名）
        days_left = None
        if sub and sub.end_date:
            days_left = (sub.end_date - datetime.utcnow()).days

        items.append({
            "id": t.id,
            "name": t.display_name or t.id,
            "scene": t.scene or "N/A",
            "plan": plan_name,
            "calls_30d": calls_30d,
            "is_active": calls_30d > 0,
            "subscription_status": sub.status if sub else "无订阅",
            "days_left": days_left,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    }


@router.get("/{tenant_id}", summary="客户详情")
async def customer_detail(
    tenant_id: str,
    user=Depends(admin_required),
    db: Session = Depends(get_db),
):
    """单个客户详细信息"""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        return {"code": 404, "message": "客户不存在", "data": None}

    sub = db.query(Subscription).filter(
        Subscription.tenant_id == tenant_id,
        Subscription.status == "active"
    ).first()

    # 近6个月调用趋势
    calls_trend = []
    for i in range(5, -1, -1):
        month_start = (datetime.utcnow().replace(day=1) - timedelta(days=i * 30))
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) if i > 0 else datetime.utcnow()
        cnt = db.query(CallLog).filter(
            CallLog.tenant_id == tenant_id,
            CallLog.timestamp >= month_start,
            CallLog.timestamp < month_end
        ).count()
        calls_trend.append({"month": month_start.strftime("%Y-%m"), "calls": cnt})

    # 最近账单
    bills = db.query(Bill).filter(
        Bill.tenant_id == tenant_id
    ).order_by(Bill.bill_period.desc()).limit(6).all()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "tenant": {
                "id": t.id,
                "name": t.display_name or t.id,
                "scene": t.scene,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            },
            "subscription": {
                "plan": sub.plan_id if sub else None,
                "status": sub.status if sub else "无订阅",
                "started_at": sub.start_date.isoformat() if sub and sub.start_date else None,
                "expires_at": sub.end_date.isoformat() if sub and sub.end_date else None,
            } if sub else None,
            "calls_trend": calls_trend,
            "recent_bills": [
                {"period": b.bill_period, "amount": b.total_cents or 0, "status": b.status}
                for b in bills
            ],
        }
    }


@router.get("/at-risk/list", summary="流失风险客户列表")
async def at_risk_customers(
    user=Depends(admin_required),
    db: Session = Depends(get_db),
):
    """返回30天内无调用但有订阅的客户"""
    cutoff = datetime.utcnow() - timedelta(days=30)
    active_ids = [r[0] for r in db.query(CallLog.tenant_id).filter(
        CallLog.timestamp >= cutoff
    ).distinct().all()]

    query = db.query(Tenant).filter(~Tenant.id.in_(active_ids)) if active_ids else db.query(Tenant)
    tenants = query.all()

    items = []
    for t in tenants:
        sub = db.query(Subscription).filter(
            Subscription.tenant_id == t.id,
            Subscription.status == "active"
        ).first()
        if sub:
            last_call = db.query(CallLog).filter(
                CallLog.tenant_id == t.id
            ).order_by(CallLog.timestamp.desc()).first()
            items.append({
                "id": t.id,
                "name": t.display_name or t.id,
                "plan": sub.plan_id,
                "last_active": last_call.created_at.isoformat() if last_call else "从未调用",
                "days_inactive": (datetime.utcnow() - last_call.created_at).days if last_call else "N/A",
            })

    return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}
