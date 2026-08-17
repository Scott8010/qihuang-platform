"""
Agent 中台（智能控制面）— 与 HB 业务平台平级，横切「底座能力 / 运营控制 / 业务展现」三层。

定位（老黄 2026-08-11 拍板）：
    - Agent 中台不是 8602 菜单项，而是长在「岐黄智脑赋能平台（AI PaaS）」底座上的第二面；
    - 以「可嵌入业务流的能力模块」形态存在（如内容送审工作台），回写钉在业务实体上，
      客观、可追溯、能反哺活态化 —— 不是对话窗口型 Agent。

第一个能力：内容合规审核（compliance），由 hb-compliance-guard 纯引擎驱动。
新增能力只需在 registry 注册 + 在下方 include_router 即可。
"""
from fastapi import APIRouter

from qihuang_platform.agent.compliance.router import router as compliance_router
from qihuang_platform.agent.fortune.router import router as fortune_router
from qihuang_platform.agent.geo.router import router as geo_router
from qihuang_platform.agent.health_advisor.router import router as health_advisor_router

agent_router = APIRouter()
agent_router.include_router(
    compliance_router, prefix="/api/v1/agent", tags=["Agent-中台"]
)
agent_router.include_router(
    fortune_router, prefix="/api/v1/agent", tags=["Agent-中台"]
)
agent_router.include_router(
    geo_router, prefix="/api/v1/agent", tags=["Agent-中台"]
)
agent_router.include_router(
    health_advisor_router, prefix="/api/v1/agent", tags=["Agent-中台"]
)

__all__ = ["agent_router"]
