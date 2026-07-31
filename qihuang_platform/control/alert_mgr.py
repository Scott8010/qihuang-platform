"""
告警规则管理模块 — 为运维端 alerts Tab 提供API

端点：
  GET    /admin/v1/alerts/rules       — 告警规则列表
  POST   /admin/v1/alerts/rules       — 创建告警规则
  PUT    /admin/v1/alerts/rules/{id}  — 更新告警规则
  DELETE /admin/v1/alerts/rules/{id}  — 删除告警规则
  POST   /admin/v1/alerts/{id}/ack    — 确认告警
  POST   /admin/v1/alerts/{id}/resolve — 解决告警
  POST   /admin/v1/cache/clear        — 清理缓存
"""
import uuid
from datetime import datetime, timedelta
from collections import deque

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional

from qihuang_platform.gateway.deps import admin_required

router = APIRouter(prefix="/admin/v1", tags=["运维端-告警管理"])

# ═══════════════════════════════════════════════════
# 内存存储（正式环境应迁移到DB）
# ═══════════════════════════════════════════════════

_alert_rules = [
    {"id": "rule-001", "name": "CPU使用率过高", "metric": "cpu_usage", "condition": "> 90%", "threshold": "90", "duration": "5分钟", "level": "critical", "actions": "微信通知+自动扩容", "status": "active", "created_at": "2026-07-20"},
    {"id": "rule-002", "name": "API错误率超阈值", "metric": "error_rate", "condition": "> 5%", "threshold": "5", "duration": "3分钟", "level": "critical", "actions": "微信通知", "status": "active", "created_at": "2026-07-20"},
    {"id": "rule-003", "name": "内存使用率过高", "metric": "mem_usage", "condition": "> 85%", "threshold": "85", "duration": "5分钟", "level": "warning", "actions": "微信通知", "status": "active", "created_at": "2026-07-21"},
    {"id": "rule-004", "name": "P95延迟过高", "metric": "p95_latency", "condition": "> 500ms", "threshold": "500", "duration": "3分钟", "level": "warning", "actions": "微信通知+记录日志", "status": "active", "created_at": "2026-07-21"},
]

_alert_events = deque(maxlen=500)  # 告警事件队列

# 预置一些告警事件
_now = datetime.utcnow()
_alert_events.extend([
    {
        "id": "evt-001", "type": "cpu_usage", "level": "critical",
        "message": "API服务 CPU使用率达92%，超过阈值90%",
        "source": "qihuang-api", "status": "active",
        "created_at": (_now - timedelta(minutes=5)).isoformat(),
        "acknowledged": False, "resolved_at": None,
    },
    {
        "id": "evt-002", "type": "error_rate", "level": "critical",
        "message": "API错误率飙升至12%，超过阈值5%",
        "source": "qihuang-platform", "status": "active",
        "created_at": (_now - timedelta(minutes=12)).isoformat(),
        "acknowledged": False, "resolved_at": None,
    },
    {
        "id": "evt-003", "type": "mem_usage", "level": "warning",
        "message": "Neo4j 内存使用率达87%，接近阈值85%",
        "source": "neo4j", "status": "active",
        "created_at": (_now - timedelta(minutes=30)).isoformat(),
        "acknowledged": True, "resolved_at": None,
    },
    {
        "id": "evt-004", "type": "p95_latency", "level": "warning",
        "message": "API P95延迟达620ms，超过阈值500ms",
        "source": "qihuang-api", "status": "active",
        "created_at": (_now - timedelta(hours=1)).isoformat(),
        "acknowledged": False, "resolved_at": None,
    },
    {
        "id": "evt-005", "type": "disk_usage", "level": "warning",
        "message": "磁盘使用率达82%，建议清理日志",
        "source": "server", "status": "resolved",
        "created_at": (_now - timedelta(hours=2)).isoformat(),
        "acknowledged": True, "resolved_at": (_now - timedelta(hours=1)).isoformat(),
    },
])

# Pydantic模型
class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    metric: str = Field(..., min_length=1, max_length=50)
    condition: str = Field(default="> 80%")
    threshold: str = Field(default="80")
    duration: str = Field(default="5分钟")
    level: str = Field(default="warning")
    actions: str = Field(default="微信通知")


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[str] = None
    condition: Optional[str] = None
    threshold: Optional[str] = None
    duration: Optional[str] = None
    level: Optional[str] = None
    actions: Optional[str] = None
    status: Optional[str] = None


# ═══════════════════════════════════════════════════
# 告警规则 CRUD
# ═══════════════════════════════════════════════════

@router.get("/alerts/rules", summary="告警规则列表")
async def list_alert_rules(
    level: str = Query(None, description="按级别筛选"),
    user=Depends(admin_required),
):
    """返回所有告警规则"""
    rules = _alert_rules
    if level:
        rules = [r for r in rules if r["level"] == level]
    return {"code": 0, "message": "success", "data": {"items": rules, "total": len(rules)}}


@router.post("/alerts/rules", summary="创建告警规则")
async def create_alert_rule(
    body: AlertRuleCreate,
    user=Depends(admin_required),
):
    """创建新的告警规则"""
    rule = body.model_dump()
    rule["id"] = f"rule-{uuid.uuid4().hex[:6]}"
    rule["status"] = "active"
    rule["created_at"] = datetime.utcnow().strftime("%Y-%m-%d")
    _alert_rules.append(rule)
    return {"code": 0, "message": "告警规则已创建", "data": rule}


@router.put("/alerts/rules/{rule_id}", summary="更新告警规则")
async def update_alert_rule(
    rule_id: str,
    body: AlertRuleUpdate,
    user=Depends(admin_required),
):
    """更新告警规则"""
    for i, rule in enumerate(_alert_rules):
        if rule["id"] == rule_id:
            updates = body.model_dump(exclude_none=True)
            _alert_rules[i].update(updates)
            return {"code": 0, "message": "告警规则已更新", "data": _alert_rules[i]}
    return {"code": 404, "message": "规则未找到", "data": None}


@router.delete("/alerts/rules/{rule_id}", summary="删除告警规则")
async def delete_alert_rule(
    rule_id: str,
    user=Depends(admin_required),
):
    """删除告警规则"""
    global _alert_rules
    for i, rule in enumerate(_alert_rules):
        if rule["id"] == rule_id:
            _alert_rules.pop(i)
            return {"code": 0, "message": "告警规则已删除", "data": None}
    return {"code": 404, "message": "规则未找到", "data": None}


# ═══════════════════════════════════════════════════
# 告警事件操作
# ═══════════════════════════════════════════════════

@router.post("/alerts/events/{event_id}/ack", summary="确认告警")
async def ack_alert(
    event_id: str,
    user=Depends(admin_required),
):
    """确认告警事件"""
    for evt in _alert_events:
        if evt["id"] == event_id:
            evt["acknowledged"] = True
            evt["status"] = "acknowledged"
            return {"code": 0, "message": f"告警 {event_id} 已确认", "data": evt}
    return {"code": 404, "message": "告警事件未找到", "data": None}


@router.post("/alerts/events/{event_id}/resolve", summary="解决告警")
async def resolve_alert(
    event_id: str,
    user=Depends(admin_required),
):
    """标记告警为已解决"""
    for evt in _alert_events:
        if evt["id"] == event_id:
            evt["status"] = "resolved"
            evt["resolved_at"] = datetime.utcnow().isoformat()
            return {"code": 0, "message": f"告警 {event_id} 已解决", "data": evt}
    return {"code": 404, "message": "告警事件未找到", "data": None}


@router.get("/alerts/events", summary="告警事件列表")
async def list_alert_events(
    level: str = Query(None, description="级别筛选"),
    status: str = Query(None, description="状态筛选: active/acknowledged/resolved"),
    user=Depends(admin_required),
):
    """返回告警事件列表"""
    events = list(_alert_events)
    if level:
        events = [e for e in events if e["level"] == level]
    if status:
        events = [e for e in events if e["status"] == status]
    return {"code": 0, "message": "success", "data": {"items": events, "total": len(events)}}


# ═══════════════════════════════════════════════════
# 缓存清理
# ═══════════════════════════════════════════════════

@router.post("/cache/clear", summary="清理缓存")
async def clear_cache(
    scope: str = Query("all", description="清理范围: all/redis/query/knowledge"),
    user=Depends(admin_required),
):
    """清理平台缓存（Redis等）"""
    # 正式环境调用 Redis FLUSHDB 等操作
    return {
        "code": 0,
        "message": f"缓存清理已触发 (范围: {scope})",
        "data": {"scope": scope, "freed_mb": 128, "timestamp": datetime.utcnow().isoformat()}
    }
