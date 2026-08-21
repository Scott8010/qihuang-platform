"""舌象健康特征分析 Agent 路由（MindSen 路 A）。

端点（需 JWT + 租户套餐授权，tenant_id 由网关注入 request.state）：
  POST /api/v1/agent/tongue/analyze  舌面照片 → 15 类标签 + TongueAnalysis 结构化 JSON

鉴权：require_agent_in_plan("tongue") —— 租户订阅套餐 agents 或 tenant.extra.agent_addons
      含 "tongue" 才放行（与 fortune/compliance/health-advisor 同款门禁）。
数据：stateless 返回，不落库（计量由网关 CallLog 自动聚合）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.tongue import engine
from qihuang_platform.gateway.deps import get_current_user
from qihuang_platform.gateway.response import success

router = APIRouter()


class TongueRequest(BaseModel):
    image: str = Field(..., description="舌象图片引用：data URI / http(s) URL / 本地路径")
    face_image: str | None = Field(None, description="面色图片引用（可选，两图齐全时综合分析）")
    profile: dict | None = Field(None, description="客户基础信息（可选，供证候提示保守融合）")


@router.post("/tongue/analyze", summary="舌象健康特征分析")
async def tongue_analyze(
    req: TongueRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("tongue")),
):
    """舌面照片 → 舌色/舌形/苔色/苔质/瘀斑瘀点等 15 类标签 + TongueAnalysis 字段。

    输出对齐 tongue_face_analysis.md §3.5（含 petechiae/texture/deviation/corrosion/peeling）。
    fail-closed：视觉模型未配置或调用失败时返回 mode=image_pending/image_error，绝不返回假数据。
    """
    data = engine.analyze_tongue(
        req.image,
        face_image=req.face_image,
        profile=req.profile,
    )
    return success(data=data)
