"""
health-advisor · Agent 能力模块入口

固定专业辨证链：体质辨识 → 辨证 → 方剂 → 调理，基于 8601 四诊合参引擎，
partial 降级 + 免责必带。通过 agent/__init__.py 挂载 router 接入中台。
"""
from qihuang_platform.agent.health_advisor.router import router

__all__ = ["router"]
