"""
health-advisor · 路由（Agent 中台接入点）

端点：POST /api/v1/agent/health-advisor/consult
鉴权：JWT（get_current_user 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan）
响应：success(ConsultResponse) / error(code_key)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from qihuang_platform.gateway.deps import get_current_user, get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.health_advisor.metering import check_quota
from qihuang_platform.agent.health_advisor.reports import get_report
from qihuang_platform.agent.health_advisor.schema import ConsultRequest, ConsultResponse
from qihuang_platform.agent.health_advisor.orchestrator import HealthAdvisor

router = APIRouter()
_advisor = HealthAdvisor()


@router.post(
    "/health-advisor/consult",
    summary="中医健康顾问咨询（固定专业辨证链 + partial 降级）",
)
async def consult(
    req: ConsultRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("health-advisor")),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月健康顾问调用配额已用完，请升级套餐或次月恢复。")
    try:
        resp = await _advisor.consult(req, tenant_id)
        return success(resp.model_dump())
    except Exception as e:  # noqa: BLE001
        return error("INTERNAL_ERROR", str(e))


@router.get(
    "/health-advisor/report/{report_id}",
    summary="获取健康顾问辨证报告（full 模式生成）",
)
async def get_report_endpoint(report_id: str):
    rep = get_report(report_id)
    if not rep:
        return error("NOT_FOUND", "报告不存在或已过期")
    return success(rep)
