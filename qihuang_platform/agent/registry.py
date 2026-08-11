"""
Agent 能力注册表 — 控制面的「能力清单」。

每个能力是一个融入业务流的模块（business_embedded），由某个底层引擎驱动，
通过 8602 的 tenant_id 注入与嵌套多租户隔离机制接入运营平台。
新增能力：register_agent(key, spec) 并在 agent/__init__.py 挂载其 router。
"""
from typing import Any, Dict, Optional

AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "compliance": {
        "name": "内容合规审核",
        "kind": "business_embedded",          # 融入业务流的能力模块，非对话窗口型
        "engine": "hb-compliance-guard",       # 纯规则引擎（32 条 A~F 类规则，四态判定）
        "router_prefix": "/api/v1/agent/compliance",
        "capabilities": ["scan", "feedback", "dashboard"],
        "status": "active",
        "desc": "门店经营文案送审：广告法/医疗夸大/禁忌缺失等规则四态判定，"
                "回写钉业务实体（material_key→MAT-XXXX 幂等），客观真实可反哺。",
    },
}


def register_agent(key: str, spec: Dict[str, Any]) -> None:
    """注册一个新 Agent 能力。"""
    AGENT_REGISTRY[key] = spec


def get_agent(key: str) -> Optional[Dict[str, Any]]:
    return AGENT_REGISTRY.get(key)


def list_agents() -> Dict[str, Dict[str, Any]]:
    return AGENT_REGISTRY
