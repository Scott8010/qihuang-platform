"""
Agent 中台 — 调用鉴权依赖。

require_agent_in_plan(agent_key)：调用端按「租户→订阅套餐→features_json.agents」
校验当前租户是否被授权使用该 Agent 能力（一等可分配资源，与套餐/密钥同级）。
未订阅 / 套餐未包含该能力 → 403 AGENT_FORBIDDEN。

实现为工厂：require_agent_in_plan(key) 返回缓存的稳定内函数，便于测试用
app.dependency_overrides[require_agent_in_plan(key)] 精准覆盖。
"""
from typing import Dict
from fastapi import Depends, Request
from fastapi.exceptions import HTTPException

from qihuang_platform.gateway.deps import get_current_user, get_current_principal
from qihuang_platform.gateway.response import error
from qihuang_platform.agent.registry import is_active

_DEP_CACHE: Dict[str, object] = {}


def _emit_perm_event(tenant_id, agent_key, result, reason, addons=None):
    """旁路记录 agent 调用权限判定（P0 append-only 事件日志；绝不阻断业务）。"""
    try:
        from qihuang_platform.event_log import emit_event
        payload = {"action": "agent_invoke", "result": result, "reason": reason}
        if addons is not None:
            payload["addons"] = addons
        emit_event(
            tenant_id=tenant_id, agent_key=agent_key,
            event_type="PERMISSION", payload=payload,
        )
    except Exception:
        pass


def resolve_tenant_agent_access(tenant_id: str) -> dict:
    """统一解析某租户当前可用的 Agent 范围——门控（require_agent_in_plan）与
    机构端展示（GET /admin/v1/my/agents）共用同一真值源，杜绝「页面显示能用、实际调不通」。

    判定链与 require_agent_in_plan 完全一致：
      active 订阅 → 场景套餐编排（SCENE_PLAN_AGENTS，按 tenant.scene，缺省 MED）→
      租户单加叠加（Tenant.extra.agent_addons，仅计启用态）→ 去重保序。

    返回：has_subscription / scene / plan_name / plan_display_name /
          plan_agents / addons / agents（最终可用 key 列表）
    """
    from qihuang_platform.db.config import SessionLocal
    from qihuang_platform.db.models import Subscription, Plan, Tenant
    from qihuang_platform.billing.plans import get_effective_agents

    db = SessionLocal()
    try:
        sub = db.query(Subscription).filter_by(tenant_id=tenant_id, status="active").first()
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        plan = db.query(Plan).filter_by(id=sub.plan_id).first() if sub else None
        scene = getattr(tenant, "scene", None)
        plan_agents = get_effective_agents(plan, scene) if plan else []
        addons = [k for k in ((tenant.extra or {}).get("agent_addons", []) if tenant else []) if is_active(k)]
        merged = list(plan_agents)
        for k in addons:
            if k not in merged:
                merged.append(k)
        return {
            "has_subscription": bool(sub),
            "scene": scene or "MED",
            "plan_name": getattr(plan, "plan_name", None),
            "plan_display_name": getattr(plan, "display_name", None),
            "plan_agents": plan_agents,
            "addons": addons,
            "agents": merged,
        }
    finally:
        db.close()


def require_agent_in_plan(agent_key: str):
    """返回校验「当前租户套餐是否包含 agent_key」的依赖内函数（稳定可覆盖）。"""
    if agent_key in _DEP_CACHE:
        return _DEP_CACHE[agent_key]

    async def _dep(request: Request, user: dict = Depends(get_current_principal)):
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            _emit_perm_event(tenant_id, agent_key, "denied", "no_tenant_context")
            raise HTTPException(
                status_code=403,
                detail=error("AGENT_FORBIDDEN", "无法解析租户上下文，拒绝调用 Agent 能力"),
            )

        # 能力须处于启用态（控制端可热插拔）
        if not is_active(agent_key):
            _emit_perm_event(tenant_id, agent_key, "denied", "agent_inactive")
            raise HTTPException(
                status_code=403,
                detail=error("AGENT_FORBIDDEN", f"Agent 能力「{agent_key}」已停用"),
            )

        # 解析套餐权限：与机构端展示接口共用同一真值源（统一租户 Agent 范围解析）
        try:
            access = resolve_tenant_agent_access(tenant_id)
        except Exception as e:
            raise HTTPException(
                status_code=403,
                detail=error("AGENT_FORBIDDEN", f"套餐鉴权不可用：{e}"),
            )
        addons = access["addons"]
        if not access["has_subscription"]:
            _emit_perm_event(tenant_id, agent_key, "denied", "no_active_subscription")
            raise HTTPException(
                status_code=403,
                detail=error("AGENT_FORBIDDEN", "租户无有效订阅，无法使用 Agent 能力"),
            )
        if agent_key not in access["agents"]:
            _emit_perm_event(tenant_id, agent_key, "denied", "not_in_plan", addons=addons)
            raise HTTPException(
                status_code=403,
                detail=error(
                    "AGENT_FORBIDDEN",
                    f"当前套餐未包含 Agent 能力「{agent_key}」"
                    + ("（含租户叠加项）" if addons else ""),
                ),
            )
        _emit_perm_event(tenant_id, agent_key, "allowed", "plan_includes_agent", addons=addons)
        return user

    _DEP_CACHE[agent_key] = _dep
    return _dep
