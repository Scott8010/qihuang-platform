"""
health-assistant · Agent 能力模块入口

C 端健康服务钩子（2026-08-22 老黄拍板从 health-advisor 拆出独立）：
自由问答（ChatGPT 式）+ 多模态自动切换 + 会话内记忆 + 租户级营销引导语料口子
（Tenant.extra.health_assistant_prompt）+ 双层配额（机构级 + 终端 C 端用户级）。

与 health-advisor 分工：health-advisor 走固定辨证链（打磨中，暂不对外）；
health-assistant 面向 C 端获客与导购，是套餐内第一钩子。
"""
from qihuang_platform.agent.health_assistant.router import router

__all__ = ["router"]
