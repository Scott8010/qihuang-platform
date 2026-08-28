"""
风水堪舆 Agent（business_embedded，与 fortune 平级，看空间）

端点（双鉴权：API Key 签名优先，否则回退 JWT，tenant_id 由网关注入 request.state）：
  POST /api/v1/agent/geo         风水堪舆：坐向(罗盘/24山)+GPS+户型 → 宅卦/八宅吉凶方/九宫/峦头
  GET  /api/v1/agent/geo/dashboard 运营看板（按 user 聚合）

隔离红线：数据落独立 geo.jsonl（不混 fortune 库、不入 Neo4j）；受 require_agent_in_plan("geo") 门控。
能力内核 geo_fengshui 规则引擎来自 fortune/engine.py（复用，不改），本包仅做路由与落盘。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.db.config import get_db
from qihuang_platform.agent.fortune.schema import GeoRequest
from qihuang_platform.agent.fortune import engine
from qihuang_platform.agent.fortune.store import FortuneStore, make_material_id
from qihuang_platform.agent.fortune.audit import AuditStore
from qihuang_platform.billing.wallet import charge_agent

router = APIRouter()

_HERE = os.path.dirname(__file__)
_seed = os.path.join(_HERE, "seed")
os.makedirs(_seed, exist_ok=True)
_store = FortuneStore(os.path.join(_seed, "geo.jsonl"))
_audit = AuditStore(os.path.join(_seed, "audit.jsonl"))


def geo_analysis(req: GeoRequest, request: Request, operator: str) -> dict:
    """核心风水分析（供 /geo 与 fortune/router 的 /fortune/geo 向后兼容委托共用）。

    数据统一落独立 geo.jsonl（隔离红线），返回成功响应 dict 或 error dict。
    """
    try:
        data = engine.geo_fengshui(req.orientation, gps=req.gps, floor_plan=req.floor_plan)
    except (ValueError, KeyError, TypeError) as e:
        return error(code_key="BAD_ORIENTATION", message=str(e))
    data["user_id"] = req.user_id
    material_key = f"geo:{req.user_id or 'anon'}"
    material_id = make_material_id(material_key, prefix="GEO")
    _store.upsert(material_id, data)
    _audit.append("geo", operator=operator, user_id=req.user_id)
    return success(data={"material_id": material_id, **data})


@router.post("/geo")
async def geo_create(
    req: GeoRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _agent=Depends(require_agent_in_plan("geo")),
):
    """风水堪舆（看空间）：坐向(罗盘/24山) + GPS → 宅卦/八宅吉凶方/九宫/峦头。"""
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    result = geo_analysis(req, request, operator=getattr(request.state, "user_id", "unknown"))
    if isinstance(result, dict) and result.get("code") == 0:
        charge_agent(tenant_id, "geo", uses_llm=False)  # B2: 规则类固定 2 积分
    return result


@router.get("/geo/dashboard")
async def geo_dashboard(
    user_id: str = None,
    request: Request = None,
    user: dict = Depends(get_current_principal),
    _agent=Depends(require_agent_in_plan("geo")),
):
    """运营看板：按 user 聚合调用量与类型分布。"""
    return success(data=_store.dashboard(user_id=user_id))
