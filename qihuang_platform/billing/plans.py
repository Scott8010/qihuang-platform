"""
套餐管理 — 按场景分档的 Agent 编排 + 双层配额（机构级 + 终端用户级）

老黄 2026-08-22 敲定（从勾选调研表导出 JSON 落地）：
- 4 档套餐：体验版(免费/限次) / 标准版 ¥299 / 专业版 ¥599(+3D) / 企业版 ¥999(+3D)
- 每档 Agent 数阶梯：体验1 / 标准2 / 专业3 / 企业4
- 4 业务场景 MED(医馆)/EDU(教育)/RETAIL(门店)/HQ(总部)，各场景同档 Agent 不同
- HQ 仅企业版可订阅（无其他版本）
- 中医健康顾问(health-advisor)打磨中·暂不对外（不在任何套餐）
- 风水堪舆(geo)额外加配（不在套餐内）
- 健康助手(health-assistant)为 C 端主钩子：体验版每 C 端用户限 10 次/月（双层配额第一层）
- module_3d 按套餐门槛（专业/企业自动含，无加购）；module_agent 已废弃删除
"""
from typing import Optional, Dict, List


# 4 档套餐基础配置
DEFAULT_PLANS = [
    {
        "plan_name": "trial",
        "display_name": "体验版",
        "qps": 3,
        "month_calls": 500,
        "month_tokens": 50000,
        "price_cents": 0,
        "features_json": {
            "module_3d": False,
            "report_export": False,
            "priority_support": False,
            "custom_skin": False,
            "trial_days": 30,
            # 双层配额·第一层：体验版健康助手，每个 C 端用户每月免费次数
            "health_assistant_per_user_monthly": 10,
            # 兼容兜底：取 MED 场景同档编排（门控优先走 SCENE_PLAN_AGENTS）
            "agents": ["health-assistant"],
        },
        "description": "免费体验30天，健康助手每C端用户限10次/月，尝鲜大健康C端服务",
    },
    {
        "plan_name": "standard",
        "display_name": "标准版",
        "qps": 10,
        "month_calls": 2000,
        "month_tokens": 100000,
        "price_cents": 29900,
        "features_json": {
            "module_3d": False,
            "report_export": True,
            "priority_support": False,
            "custom_skin": False,
            # 兼容兜底：MED 场景标准版编排
            "agents": ["compliance", "health-assistant"],
        },
        "description": "标准版 ¥299/月 — 2个Agent（零成本合规+健康助手），中小企业入门",
    },
    {
        "plan_name": "professional",
        "display_name": "专业版",
        "qps": 30,
        "month_calls": 10000,
        "month_tokens": 500000,
        "price_cents": 59900,
        "features_json": {
            "module_3d": True,
            "report_export": True,
            "priority_support": True,
            "custom_skin": False,
            # 兼容兜底：MED 场景专业版编排
            "agents": ["compliance", "health-assistant", "tongue"],
        },
        "description": "专业版 ¥599/月 — 3个Agent+3D经络可视化（合规+健康助手+产token能力）",
    },
    {
        "plan_name": "enterprise",
        "display_name": "企业版",
        "qps": 100,
        "month_calls": 50000,
        "month_tokens": 2000000,
        "price_cents": 99900,
        "features_json": {
            "module_3d": True,
            "report_export": True,
            "priority_support": True,
            "custom_skin": True,
            # 兼容兜底：MED 场景企业版编排
            "agents": ["compliance", "health-assistant", "insight", "tongue"],
        },
        "description": "企业版 ¥999/月 — 4个Agent+3D+品牌定制+专属支持，全功能旗舰",
    },
]


# 按场景的 Agent 编排（老黄 2026-08-22 敲定·从勾选调研表导出）
# 结构: scene -> plan_name -> [agent keys]
SCENE_PLAN_AGENTS: Dict[str, Dict[str, List[str]]] = {
    "MED": {
        "trial": ["health-assistant"],
        "standard": ["compliance", "health-assistant"],
        "professional": ["compliance", "health-assistant", "tongue"],
        "enterprise": ["compliance", "health-assistant", "insight", "tongue"],
    },
    "EDU": {
        "trial": ["health-assistant"],
        "standard": ["coach", "health-assistant"],
        "professional": ["coach", "content-writer", "health-assistant"],
        "enterprise": ["coach", "content-writer", "health-assistant", "insight"],
    },
    "RETAIL": {
        "trial": ["health-assistant"],
        "standard": ["fortune", "health-assistant"],
        "professional": ["compliance", "fortune", "health-assistant"],
        "enterprise": ["compliance", "content-writer", "fortune", "health-assistant"],
    },
    "HQ": {
        "trial": [],
        "standard": [],
        "professional": [],
        "enterprise": ["compliance", "content-writer", "insight", "store-coach"],
    },
}

# 各场景可订阅的套餐档位（HQ 仅企业版）
SCENE_ALLOWED_PLANS: Dict[str, List[str]] = {
    "MED": ["trial", "standard", "professional", "enterprise"],
    "EDU": ["trial", "standard", "professional", "enterprise"],
    "RETAIL": ["trial", "standard", "professional", "enterprise"],
    "HQ": ["enterprise"],
}

VALID_SCENES = ["MED", "EDU", "RETAIL", "HQ"]


def normalize_scene(scene: Optional[str]) -> str:
    s = (scene or "MED").upper()
    return s if s in VALID_SCENES else "MED"


def get_effective_agents(plan, scene: Optional[str]) -> List[str]:
    """取某套餐在某业务场景下的有效 Agent 列表（不含租户 addon——addon 在门控层叠加）。

    plan: Plan ORM 对象或 dict（兼容）。
    返回该场景该档的 Agent key 列表。
    """
    scene = normalize_scene(scene)
    plan_name = plan.plan_name if hasattr(plan, "plan_name") else (plan.get("plan_name") if isinstance(plan, dict) else None)
    if not plan_name:
        return []
    return list(SCENE_PLAN_AGENTS.get(scene, {}).get(plan_name, []))


def scene_supports_plan(scene: Optional[str], plan_name: str) -> bool:
    """该场景是否允许订阅某套餐档位（HQ 仅企业版）。"""
    return plan_name in SCENE_ALLOWED_PLANS.get(normalize_scene(scene), [])


def get_plan_features(plan):
    if plan is None:
        return {}
    if hasattr(plan, "features_json"):
        return plan.features_json or {}
    if isinstance(plan, dict):
        return plan.get("features_json", {})
    return {}


def is_module_enabled(plan, module_name="module_3d"):
    features = get_plan_features(plan)
    return bool(features.get(module_name, False))


def seed_plans(session):
    from qihuang_platform.db.models import Plan
    created = {}
    for pdata in list(DEFAULT_PLANS):
        pdata_copy = dict(pdata)
        plan_name = pdata_copy.pop("plan_name")
        display_name = pdata_copy.pop("display_name")
        description = pdata_copy.pop("description")
        default_agents = (pdata.get("features_json") or {}).get("agents", [])
        existing = session.query(Plan).filter_by(plan_name=plan_name).first()
        if existing:
            # 幂等合并：已存在套餐补 agents 字段；若已有 agents，则与内置默认做并集，
            # 保证新增内置能力能纳入已播种的套餐（不覆盖运营端已定制的额外组合）。
            # 必须用 dict() 副本，否则原地改 existing.features_json 同对象引用，
            # SQLAlchemy 检测不到 JSON 变更 → 不 UPDATE → agents 永远写不进已存在套餐。
            fj = dict(existing.features_json or {})
            if "agents" not in fj:
                if default_agents:
                    fj["agents"] = list(default_agents)
                    existing.features_json = fj
                    session.flush()
            else:
                merged = list(dict.fromkeys(list(fj.get("agents", [])) + list(default_agents)))
                if merged != fj.get("agents"):
                    fj["agents"] = merged
                    existing.features_json = fj
                    session.flush()
            created[plan_name] = existing
            continue
        plan = Plan(plan_name=plan_name, display_name=display_name, **pdata_copy)
        session.add(plan)
        session.flush()
        created[plan_name] = plan
    session.commit()
    return created
