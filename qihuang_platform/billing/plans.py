"""
套餐管理 — features_json 门控 + module_3d 增值模块开关

子任务3: 套餐开关框架
- plan.features_json 中设 module_3d 标识
- 网关鉴权时按租户套餐门控 3D 模块访问
"""
from typing import Optional, Dict


DEFAULT_PLANS = [
    {
        "plan_name": "trial",
        "display_name": "体验版",
        "scene_type": "health",
        "qps": 3,
        "month_calls": 500,
        "month_tokens": 50000,
        "price_cents": 0,
        "features_json": {
            "module_3d": False,
            "module_agent": False,
            "report_export": False,
            "priority_support": False,
            "custom_skin": False,
        },
        "description": "免费试用30天，含基础辨证+体质辨识",
    },
    {
        "plan_name": "standard",
        "display_name": "标准版",
        "scene_type": "health",
        "qps": 10,
        "month_calls": 2000,
        "month_tokens": 100000,
        "price_cents": 9900,
        "features_json": {
            "module_3d": False,
            "module_agent": False,
            "report_export": True,
            "priority_support": False,
            "custom_skin": False,
        },
        "description": "标准健康服务，含辨证推理+方剂分析+体质辨识+养生方案",
    },
    {
        "plan_name": "professional",
        "display_name": "专业版",
        "scene_type": "health",
        "qps": 30,
        "month_calls": 10000,
        "month_tokens": 500000,
        "price_cents": 29900,
        "features_json": {
            "module_3d": True,
            "module_agent": True,
            "report_export": True,
            "priority_support": True,
            "custom_skin": False,
            "agents": ["compliance"],
        },
        "description": "专业健康服务，含3D经络穴位可视化+优先支持+内容合规审核Agent",
    },
    {
        "plan_name": "enterprise",
        "display_name": "企业版",
        "scene_type": "health",
        "qps": 100,
        "month_calls": 50000,
        "month_tokens": 2000000,
        "price_cents": 99900,
        "features_json": {
            "module_3d": True,
            "module_agent": True,
            "report_export": True,
            "priority_support": True,
            "custom_skin": True,
            "agents": ["compliance"],
        },
        "description": "企业级全功能，含3D穴位+名医智能体+品牌定制+专属支持+内容合规审核Agent",
    },
]


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


def get_3d_addon_price():
    return {
        "module": "module_3d",
        "name": "岐黄三境3D经络穴位",
        "pricing": {"monthly_cny": 99.00, "yearly_cny": 990.00},
        "metering_dimensions": [
            "3d_component_loads",
            "3d_model_downloads",
            "3d_data_calls",
            "3d_cdn_traffic_gb",
        ],
        "billing_note": "3D模块作为增值加购项，账单独立列示",
    }


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
            # 幂等合并：已存在套餐补 agents 字段（不覆盖运营端已定制的组合）
            fj = existing.features_json or {}
            if "agents" not in fj and default_agents:
                fj["agents"] = list(default_agents)
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
