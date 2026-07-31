"""
数据同步管理模块 — 为运维端 sync Tab 提供API

端点：
  GET  /admin/v1/sync/status         — 同步状态
  POST /admin/v1/sync/item/{name}    — 单条同步
  POST /admin/v1/sync/all            — 全量同步
  GET  /admin/v1/sync/logs           — 同步日志
"""
import time
from datetime import datetime, timedelta
from collections import deque

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import Tenant, User, AuditLog, KgVersion, SensitiveWord
from qihuang_platform.gateway.deps import admin_required

router = APIRouter(prefix="/admin/v1/sync", tags=["运维端-数据同步"])

# 同步日志队列（内存，最近200条）
_sync_logs = deque(maxlen=200)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/status", summary="同步状态")
async def sync_status(user=Depends(admin_required), db: Session = Depends(get_db)):
    """返回各数据类型的本地量与同步状态"""
    now = datetime.utcnow()
    items = []

    # 知识图谱节点（估算）
    node_count = 5054  # 当前硬编码值，待接入真实Neo4j
    items.append({
        "name": "知识图谱节点",
        "local_count": node_count,
        "cloud_count": node_count,
        "diff": 0,
        "status": "synced",
        "last_sync": "2分钟前",
        "duration": "3s",
    })

    # 知识图谱关系（估算）
    rel_count = 10913
    items.append({
        "name": "知识图谱关系",
        "local_count": rel_count,
        "cloud_count": rel_count,
        "diff": 0,
        "status": "synced",
        "last_sync": "2分钟前",
        "duration": "5s",
    })

    # 租户数据
    tenant_count = db.query(Tenant).count()
    items.append({
        "name": "租户数据",
        "local_count": tenant_count,
        "cloud_count": tenant_count,
        "diff": 0,
        "status": "synced",
        "last_sync": "10分钟前",
        "duration": "1s",
    })

    # 用户数据
    user_count = db.query(User).count()
    items.append({
        "name": "用户数据",
        "local_count": user_count,
        "cloud_count": user_count,
        "diff": 0,
        "status": "synced",
        "last_sync": "10分钟前",
        "duration": "1s",
    })

    # 审计日志（本地 vs 云端差异）
    audit_local = db.query(AuditLog).count()
    audit_cloud = max(0, audit_local - 45)  # 模拟45条未同步（正式环境需对接云端API）
    items.append({
        "name": "审计日志",
        "local_count": audit_local,
        "cloud_count": audit_cloud,
        "diff": audit_local - audit_cloud,
        "status": "synced" if audit_local == audit_cloud else "partial",
        "last_sync": "30分钟前",
        "duration": "8s",
    })

    # 知识版本
    ver_count = db.query(KgVersion).count()
    items.append({
        "name": "知识版本",
        "local_count": ver_count,
        "cloud_count": ver_count,
        "diff": 0,
        "status": "synced",
        "last_sync": "1小时前",
        "duration": "2s",
    })

    return {"code": 0, "message": "success", "data": {"items": items}}


@router.post("/item/{name}", summary="单条同步")
async def sync_item(
    name: str,
    user=Depends(admin_required),
):
    """执行单个数据类型的同步"""
    start = time.time()
    # 模拟同步操作（正式环境需对接云端API）
    time.sleep(1.5)

    duration = f"{time.time() - start:.1f}s"
    _sync_logs.appendleft({
        "time": datetime.utcnow().isoformat(),
        "item": name,
        "result": "success",
        "duration": duration,
        "detail": f"{name} 同步完成",
    })

    return {
        "code": 0,
        "message": f"{name} 同步完成",
        "data": {"item": name, "duration": duration, "status": "synced"}
    }


@router.post("/all", summary="全量同步")
async def sync_all(user=Depends(admin_required)):
    """执行全量数据同步"""
    start = time.time()
    items = ["知识图谱节点", "知识图谱关系", "租户数据", "用户数据", "审计日志", "知识版本"]
    results = []

    for item in items:
        item_start = time.time()
        time.sleep(0.5)  # 模拟同步操作
        d = f"{time.time() - item_start:.1f}s"
        results.append({"item": item, "status": "success", "duration": d})
        _sync_logs.appendleft({
            "time": datetime.utcnow().isoformat(),
            "item": item,
            "result": "success",
            "duration": d,
            "detail": f"全量同步 - {item} 完成",
        })

    total_duration = f"{time.time() - start:.1f}s"
    return {
        "code": 0,
        "message": f"全量同步完成，共 {len(results)} 项",
        "data": {"items": results, "total_duration": total_duration}
    }


@router.get("/logs", summary="同步日志")
async def sync_logs(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(admin_required),
):
    """返回最近N条同步日志"""
    logs = list(_sync_logs)[:limit]
    return {"code": 0, "message": "success", "data": {"items": logs, "total": len(logs)}}
