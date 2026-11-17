"""舌象健康特征分析 Agent 路由（MindSen 路 A）。

端点（需鉴权 + 租户套餐授权，tenant_id 由鉴权层注入 request.state）：
  POST /api/v1/agent/tongue/analyze  舌面照片 → 15 类标签 + TongueAnalysis 结构化 JSON

鉴权：API Key 签名 / JWT 双鉴权（get_current_principal，与 health-advisor A2 同款通道）
      + require_agent_in_plan("tongue") 套餐/叠加授权。
数据：stateless 返回，不落库（计量由网关 CallLog 自动聚合）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.tongue import engine
from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.billing.wallet import charge_agent

router = APIRouter()


class TongueRequest(BaseModel):
    image: str = Field(..., description="舌象图片引用：data URI / http(s) URL / 本地路径")
    face_image: str | None = Field(None, description="面色图片引用（可选，两图齐全时综合分析）")
    profile: dict | None = Field(None, description="客户基础信息（可选，供证候提示保守融合）")


@router.post("/tongue/analyze", summary="舌象健康特征分析")
async def tongue_analyze(
    req: TongueRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _agent=Depends(require_agent_in_plan("tongue")),
):
    """舌面照片 → 舌色/舌形/苔色/苔质/瘀斑瘀点等 15 类标签 + TongueAnalysis 字段。

    输出对齐 tongue_face_analysis.md §3.5（含 petechiae/texture/deviation/corrosion/peeling）。
    fail-closed：视觉模型未配置或调用失败时返回 mode=image_pending/image_error，绝不返回假数据。
    """
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    data, tokens = engine.analyze_tongue(
        req.image,
        face_image=req.face_image,
        profile=req.profile,
    )
    # 多模态：真实视觉 token（含图片 token）来自 vision_chat_json usage；未配置视觉则 tokens=0（未真调 LLM）
    charge_agent(tenant_id, "tongue", uses_llm=True, token_used=tokens, is_multimodal=True, endpoint="/api/v1/agent/tongue/analyze")

    # 上游视觉故障时不再"code=0 假成功"（租户 P0 建议②）。
    # 兼容策略：保留 data.mode=image_error/image_pending 供现有租户兜底判定，
    # 额外加 degraded 标识 + 顶层非 0 code 供新客户端一眼识别平台侧故障。
    mode = data.get("mode")
    if mode in ("image_error", "image_pending") and data.get("provided"):
        data["degraded"] = True
        # image_error=上游调用失败(5003 LLM_DOWN)；image_pending=未配置模型(5002)
        return error("LLM_DOWN" if mode == "image_error" else "SERVICE_UNAVAILABLE",
                     message=f"舌象视觉分析不可用（{mode}），平台侧故障或配置缺失", data=data)
    return success(data=data)
