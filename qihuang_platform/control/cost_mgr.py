"""
成本中心模块 — 运营端成本管理6个端点
对应前端 CostCenter.tsx 的数据接口

端点:
  GET /admin/v1/cost/overview          — 成本概览KPI（本月/上月/预算/日成本）
  GET /admin/v1/cost/trend             — 12个月成本趋势（面积堆叠图）
  GET /admin/v1/cost/breakdown         — 成本构成环形图
  GET /admin/v1/cost/daily             — 近7日日成本柱状图
  GET /admin/v1/cost/services/expiring — 云服务到期提醒
  GET /admin/v1/cost/resources         — 云资源详细清单
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.gateway.response import success, error

router = APIRouter(prefix="/admin/v1/cost", tags=["管理端-成本中心"])

# ═══════════════════════════════════════════
# Mock 数据（与前端 kimi_extract/app/src/lib/mock.ts 一致）
# ═══════════════════════════════════════════

COST_BREAKDOWN = [
    {"category": "LLM Token", "amount": 5240, "color": "#B03A2E", "icon": "cpu", "detail": "DeepSeek ¥3,120 + GLM-4 ¥980 + Kimi ¥720 + 通义 ¥420"},
    {"category": "云服务器", "amount": 298, "color": "#2E5A4C", "icon": "server", "detail": "ECS 2核8G × 1 台（上海）"},
    {"category": "云数据库", "amount": 0, "color": "#8FA9A0", "icon": "db", "detail": "T0-1 待部署，预计 ¥198/月（PostgreSQL + Redis）"},
    {"category": "CDN + 带宽", "amount": 465, "color": "#C8A45D", "icon": "wifi", "detail": "3D 资产分发 41.2GB + 静态资源加速"},
    {"category": "域名", "amount": 2.5, "color": "#4A5B54", "icon": "globe", "detail": "yshealth.com.cn 年费 ¥30 按月分摊"},
    {"category": "HTTPS 证书", "amount": 0, "color": "#22312B", "icon": "shield", "detail": "Let's Encrypt 免费自动续期"},
]

COST_TREND = [
    {"month": "2025-08", "LLM": 2100, "Server": 298, "CDN": 120, "DB": 0},
    {"month": "2025-09", "LLM": 2340, "Server": 298, "CDN": 145, "DB": 0},
    {"month": "2025-10", "LLM": 2580, "Server": 298, "CDN": 168, "DB": 0},
    {"month": "2025-11", "LLM": 3120, "Server": 298, "CDN": 201, "DB": 0},
    {"month": "2025-12", "LLM": 2980, "Server": 298, "CDN": 189, "DB": 0},
    {"month": "2026-01", "LLM": 3450, "Server": 298, "CDN": 235, "DB": 0},
    {"month": "2026-02", "LLM": 3620, "Server": 298, "CDN": 278, "DB": 0},
    {"month": "2026-03", "LLM": 4100, "Server": 298, "CDN": 312, "DB": 0},
    {"month": "2026-04", "LLM": 3980, "Server": 298, "CDN": 345, "DB": 0},
    {"month": "2026-05", "LLM": 4560, "Server": 298, "CDN": 398, "DB": 0},
    {"month": "2026-06", "LLM": 4890, "Server": 298, "CDN": 432, "DB": 0},
    {"month": "2026-07", "LLM": 5240, "Server": 298, "CDN": 465, "DB": 0},
]

TOTAL_COST_THIS_MONTH = sum(c["amount"] for c in COST_BREAKDOWN)
# 上月：取趋势倒数第二个月的所有项之和
_last_month = COST_TREND[-2]
LAST_MONTH_COST = _last_month["LLM"] + _last_month["Server"] + _last_month["CDN"] + _last_month["DB"]
MONTHLY_BUDGET = 8000

SERVICE_EXPIRATIONS = [
    {"id": "S-01", "name": "ECS 云服务器", "type": "服务器", "provider": "阿里云", "expires": "2027-02-15", "daysLeft": 203, "cost": 298, "period": "月", "status": "OK"},
    {"id": "S-02", "name": "yshealth.com.cn", "type": "域名", "provider": "阿里云��万网", "expires": "2027-08-20", "daysLeft": 389, "cost": 30, "period": "年", "status": "OK"},
    {"id": "S-03", "name": "PostgreSQL 云数据库", "type": "数据库", "provider": "阿里云", "expires": "—", "daysLeft": 0, "cost": 198, "period": "月", "status": "TBD"},
    {"id": "S-04", "name": "Redis 缓存实例", "type": "缓存", "provider": "阿里云", "expires": "—", "daysLeft": 0, "cost": 68, "period": "月", "status": "TBD"},
    {"id": "S-05", "name": "COS 对象存储", "type": "存储", "provider": "腾讯云", "expires": "—", "daysLeft": 0, "cost": 45, "period": "月", "status": "TBD"},
    {"id": "S-06", "name": "ICP 备案", "type": "资质", "provider": "工信部", "expires": "2027-06-01", "daysLeft": 309, "cost": 0, "period": "永久", "status": "OK"},
]

RESOURCE_ITEMS = [
    {"name": "ECS ecs.t6-c1m2.large", "spec": "2vCPU / 8GB / 80GB SSD", "provider": "阿里云", "monthlyCost": 298, "status": "RUNNING", "region": "上海"},
    {"name": "NAT 网关 + 弹性 IP", "spec": "100Mbps 按量", "provider": "阿里云", "monthlyCost": 45, "status": "RUNNING", "region": "上海"},
    {"name": "CDN 全站加速", "spec": "按流量计费", "provider": "阿里云", "monthlyCost": 465, "status": "RUNNING", "region": "全国"},
    {"name": "DNS 云解析", "spec": "企业标准版", "provider": "阿里云·云解析", "monthlyCost": 8, "status": "RUNNING", "region": "—"},
    {"name": "PostgreSQL 14", "spec": "2核4G / 100GB / 一主一备", "provider": "阿里云", "monthlyCost": 198, "status": "PLANNED", "region": "上海"},
    {"name": "Redis 7.0", "spec": "2GB 标准版", "provider": "阿里云", "monthlyCost": 68, "status": "PLANNED", "region": "上海"},
    {"name": "COS 标准存储", "spec": "100GB + 按量读请求", "provider": "腾讯云", "monthlyCost": 45, "status": "PLANNED", "region": "上海"},
    {"name": "DeepSeek API", "spec": "按 Token 计费", "provider": "DeepSeek", "monthlyCost": 3120, "status": "RUNNING", "region": "—"},
    {"name": "GLM-4 API", "spec": "按 Token 计费", "provider": "智谱AI", "monthlyCost": 980, "status": "RUNNING", "region": "—"},
    {"name": "Kimi API", "spec": "按 Token 计费", "provider": "月之暗面", "monthlyCost": 720, "status": "RUNNING", "region": "—"},
    {"name": "通义千问 API", "spec": "按 Token 计费", "provider": "阿里云·百炼", "monthlyCost": 420, "status": "RUNNING", "region": "—"},
]

DAILY_COST = [
    {"day": "07-21", "LLM": 168.4, "infra": 25.5, "total": 193.9},
    {"day": "07-22", "LLM": 172.1, "infra": 25.5, "total": 197.6},
    {"day": "07-23", "LLM": 185.3, "infra": 25.5, "total": 210.8},
    {"day": "07-24", "LLM": 178.9, "infra": 25.5, "total": 204.4},
    {"day": "07-25", "LLM": 192.6, "infra": 25.5, "total": 218.1},
    {"day": "07-26", "LLM": 169.0, "infra": 25.5, "total": 194.5},
    {"day": "07-27", "LLM": 183.5, "infra": 25.5, "total": 209.0},
]


# ═══════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════

@router.get("/overview", summary="成本概览KPI")
async def cost_overview(admin: dict = Depends(get_current_admin)):
    """返回本月成本、上月成本、预算、日成本等KPI数据"""
    return success(data={
        "total_cost_this_month": TOTAL_COST_THIS_MONTH,
        "last_month_cost": LAST_MONTH_COST,
        "monthly_budget": MONTHLY_BUDGET,
        "cost_change_percent": round(
            (TOTAL_COST_THIS_MONTH - LAST_MONTH_COST) / LAST_MONTH_COST * 100, 1
        ) if LAST_MONTH_COST > 0 else 0,
        "budget_percent": round(TOTAL_COST_THIS_MONTH / MONTHLY_BUDGET * 100, 1),
    })


@router.get("/trend", summary="12个月成本趋势")
async def cost_trend(admin: dict = Depends(get_current_admin)):
    """返回12个月成本趋势数据（LLM/Server/CDN/DB分项）"""
    return success(data={"trend": COST_TREND})


@router.get("/breakdown", summary="成本构成")
async def cost_breakdown(admin: dict = Depends(get_current_admin)):
    """返回当月成本构成（环形图数据）"""
    return success(data={"breakdown": COST_BREAKDOWN, "total": TOTAL_COST_THIS_MONTH})


@router.get("/daily", summary="近7日日成本")
async def cost_daily(
    days: int = Query(7, ge=1, le=30, description="查询天数"),
    admin: dict = Depends(get_current_admin),
):
    """返回最近N天的日成本明细"""
    return success(data={"daily": DAILY_COST[-days:]})


@router.get("/services/expiring", summary="云服务到期提醒")
async def services_expiring(admin: dict = Depends(get_current_admin)):
    """返回云服务到期提醒列表"""
    return success(data={"services": SERVICE_EXPIRATIONS})


@router.get("/resources", summary="云资源清单")
async def cost_resources(admin: dict = Depends(get_current_admin)):
    """返回云资源详细清单"""
    return success(data={"resources": RESOURCE_ITEMS})
