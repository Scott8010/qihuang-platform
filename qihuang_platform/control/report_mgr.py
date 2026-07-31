"""
报表管理模块 — 为运营端 reports Tab 提供API

端点：
  POST /admin/v1/reports/generate     — 生成报表
  GET  /admin/v1/reports              — 历史报表列表
  GET  /admin/v1/reports/{id}/download — 下载报表
  DELETE /admin/v1/reports/{id}       — 删除报表
"""
import csv
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Tenant, Bill, CallLog, Subscription, AuditLog
from qihuang_platform.gateway.deps import admin_required

router = APIRouter(prefix="/admin/v1/reports", tags=["运营端-报表管理"])

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 内存报表元数据（简化版，正式环境应走DB）
_reports_store = []


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/generate", summary="生成报表")
async def generate_report(
    report_type: str = Query(..., description="报表类型: usage/billing/customer/audit/kg"),
    time_range: str = Query("this_month", description="时间范围"),
    fmt: str = Query("csv", description="导出格式: csv/json"),
    user=Depends(admin_required),
    db: Session = Depends(get_db),
):
    """生成并保存报表文件，返回元数据"""
    now = datetime.utcnow()
    report_id = f"RPT-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    filename = f"{report_id}.{fmt}"
    filepath = REPORTS_DIR / filename

    # 确定时间范围
    if time_range == "this_month":
        start = now.replace(day=1)
        end = now
    elif time_range == "last_month":
        first = now.replace(day=1)
        start = first - timedelta(days=1)
        start = start.replace(day=1)
        end = first - timedelta(days=1)
    elif time_range == "last_7_days":
        start = now - timedelta(days=7)
        end = now
    elif time_range == "last_30_days":
        start = now - timedelta(days=30)
        end = now
    else:
        start = now - timedelta(days=30)
        end = now

    rows = []
    headers = []

    if report_type == "usage":
        headers = ["日期", "租户ID", "调用次数", "Token消耗"]
        logs = db.query(CallLog).filter(
            CallLog.timestamp >= start, CallLog.timestamp <= end
        ).all()
        for log in logs:
            rows.append([
                log.created_at.strftime("%Y-%m-%d") if log.created_at else "",
                log.tenant_id or "",
                str(log.call_count or 0),
                str(log.tokens_used or 0),
            ])

    elif report_type == "billing":
        headers = ["账单ID", "租户ID", "账期", "金额(分)", "状态", "创建时间"]
        bills = db.query(Bill).filter(
            Bill.created_at >= start, Bill.created_at <= end
        ).all()
        for b in bills:
            rows.append([
                b.id or "", b.tenant_id or "", b.bill_period or "",
                str(b.total_cents or 0), b.status or "",
                b.created_at.isoformat() if b.created_at else "",
            ])

    elif report_type == "customer":
        headers = ["租户ID", "名称", "场景", "套餐", "30天调用", "订阅状态", "创建时间"]
        tenants = db.query(Tenant).all()
        cutoff = now - timedelta(days=30)
        for t in tenants:
            sub = db.query(Subscription).filter(
                Subscription.tenant_id == t.id, Subscription.status == "active"
            ).first()
            calls = db.query(CallLog).filter(
                CallLog.tenant_id == t.id, CallLog.timestamp >= cutoff
            ).count()
            rows.append([
                t.id, t.display_name or t.id, t.scene or "",
                sub.plan_id if sub else "无",
                str(calls), sub.status if sub else "无订阅",
                t.created_at.isoformat() if t.created_at else "",
            ])

    elif report_type == "audit":
        headers = ["ID", "租户", "用户", "操作", "目标", "结果", "IP", "时间"]
        logs = db.query(AuditLog).filter(
            AuditLog.created_at >= start, AuditLog.created_at <= end
        ).order_by(AuditLog.created_at.desc()).limit(500).all()
        for log in logs:
            rows.append([
                str(log.id), log.tenant_id or "", log.user_id or "",
                log.action or "", log.target_type or "", log.result or "",
                log.ip_address or "", log.created_at.isoformat() if log.created_at else "",
            ])

    elif report_type == "kg":
        headers = ["指标", "数值"]
        # KG stats
        node_count = db.execute(db.bind.execute("SELECT COUNT(*) FROM kg_nodes")).scalar() if hasattr(db.bind, 'execute') else 5054
        rel_count = db.execute(db.bind.execute("SELECT COUNT(*) FROM kg_relations")).scalar() if hasattr(db.bind, 'execute') else 10913
        rows = [
            ["图谱节点数", str(node_count)],
            ["图谱关系数", str(rel_count)],
            ["生成时间", now.isoformat()],
        ]

    # 写入文件
    if fmt == "csv":
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
    else:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"headers": headers, "rows": rows}, f, ensure_ascii=False, indent=2)

    # 记录元数据
    meta = {
        "id": report_id,
        "type": report_type,
        "time_range": time_range,
        "format": fmt,
        "filename": filename,
        "size": os.path.getsize(filepath),
        "generated_at": now.isoformat(),
        "download_url": f"/admin/v1/reports/{report_id}/download",
    }
    _reports_store.insert(0, meta)
    if len(_reports_store) > 100:
        _reports_store.pop()

    return {"code": 0, "message": "报表生成成功", "data": meta}


@router.get("", summary="历史报表列表")
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(admin_required),
):
    """返回已生成的报表列表"""
    total = len(_reports_store)
    start = (page - 1) * page_size
    items = _reports_store[start:start + page_size]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }
    }


@router.get("/{report_id}/download", summary="下载报表")
async def download_report(
    report_id: str,
    user=Depends(admin_required),
):
    """下载指定报表文件"""
    for r in _reports_store:
        if r["id"] == report_id:
            filepath = REPORTS_DIR / r["filename"]
            if filepath.exists():
                content_type = "text/csv" if r["format"] == "csv" else "application/json"
                return StreamingResponse(
                    io.BytesIO(filepath.read_bytes()),
                    media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="{r["filename"]}"'}
                )
            return {"code": 404, "message": "报表文件不存在", "data": None}
    return {"code": 404, "message": "报表未找到", "data": None}


@router.delete("/{report_id}", summary="删除报表")
async def delete_report(
    report_id: str,
    user=Depends(admin_required),
):
    """删除指定报表"""
    global _reports_store
    for i, r in enumerate(_reports_store):
        if r["id"] == report_id:
            filepath = REPORTS_DIR / r["filename"]
            if filepath.exists():
                filepath.unlink()
            _reports_store.pop(i)
            return {"code": 0, "message": "报表已删除", "data": None}
    return {"code": 404, "message": "报表未找到", "data": None}
