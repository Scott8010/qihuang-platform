"""
Agent 中台 — 各 Agent 看板聚合派发（构件 C）。

控制端「Agent 中台」面板按 agent_key 拉取对应能力的运营看板。
能力内核在底层实现，中台只做派发，永不在控制面重算业务逻辑。
"""
from typing import Any, Dict, Optional


async def get_agent_dashboard(agent_key: str, **kwargs) -> Dict[str, Any]:
    """按 agent_key 派发到对应能力的看板函数。未知 key 抛 KeyError。"""
    if agent_key == "compliance":
        from qihuang_platform.agent.compliance.engine_l2 import compliance_engine
        institution_id = kwargs.get("store_id") or kwargs.get("institution_id")
        port = kwargs.get("port")
        return await compliance_engine.dashboard(institution_id=institution_id, port=port)
    raise KeyError(f"未知 Agent 能力看板：{agent_key}")
