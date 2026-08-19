"""
store_coach · 平台级培训模板种数据（幂等）

为门店话术训练提供内容底座：平台内置话术/产品/项目模板样例（DbTemplate，kind=script/product/project），
租户可克隆/自建/提交审核（走能力中心二期模板全模型，零新造）。
所有样例内容均经合规约束（不夸大疗效/不承诺治愈/无绝对化用语）。

种子数据可被租户克隆后按自家产品/话术替换（source=self/clone），平台内置样例只作起点。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("store_coach.seed")

# 种子模板唯一 key（避免重复种入）
_SEED_KEYS = {
    "script": [
        "seed_script_reception",
        "seed_script_recommend",
        "seed_script_objection",
        "seed_script_close",
    ],
    "product": [
        "seed_product_tea",
        "seed_product_soup",
    ],
    "project": [
        "seed_project_cupping",
    ],
}

_SEED_TEMPLATES: List[dict] = [
    # ── 话术模板（kind=script）──
    {
        "seed_key": "seed_script_reception",
        "kind": "script",
        "name": "进店接待标准话术",
        "content_json": {
            "scene": "reception",
            "steps": [
                {"step": 1, "name": "迎宾破冰", "script": "阿姨您好，欢迎光临！看您气色不错，是想了解哪方面的调理呢？"},
                {"step": 2, "name": "需求倾听", "script": "您平时睡眠、胃口都还好吗？我先帮您了解一下基本情况。"},
                {"step": 3, "name": "引导体验", "script": "我们这边有免费的体质测评，可以帮您看看适合的调理方向。"},
                {"step": 4, "name": "留资跟进", "script": "方便留个联系方式吗？后续有节气养生小知识可以分享给您。"},
            ],
            "tips": ["先倾听后推荐", "不打断顾客", "用生活化语言解释中医概念"],
        },
    },
    {
        "seed_key": "seed_script_recommend",
        "kind": "script",
        "name": "产品推荐话术（中医养生品）",
        "content_json": {
            "scene": "recommend",
            "steps": [
                {"step": 1, "name": "关联需求", "script": "根据您的情况，这款茶饮比较适合日常调理，温和不刺激。"},
                {"step": 2, "name": "成分说明", "script": "里面主要是菊花、枸杞这类常见食材，很多注重养生的朋友都在喝。"},
                {"step": 3, "name": "使用建议", "script": "建议每天泡一杯，坚持一段时间看看身体感受。"},
                {"step": 4, "name": "风险提示", "script": "如果您正在服药或有特殊情况，建议先咨询医生再用。"},
            ],
            "tips": ["如实说明成分", "不夸大功效", "给出使用期限建议"],
        },
    },
    {
        "seed_key": "seed_script_objection",
        "kind": "script",
        "name": "异议处理话术（嫌贵/怀疑效果）",
        "content_json": {
            "scene": "objection",
            "steps": [
                {"step": 1, "name": "先认同", "script": "您说的有道理，价格确实是大家都会考虑的因素。"},
                {"step": 2, "name": "拆解价值", "script": "不过您可以算一下，每天一杯的成本其实很划算，比外卖一杯饮料还便宜。"},
                {"step": 3, "name": "给依据", "script": "我们很多老顾客都是调理一段时间后主动回购的。"},
                {"step": 4, "name": "不逼单", "script": "您可以先少买一点试试，觉得合适再继续，不强求。"},
            ],
            "tips": ["不贬低顾客", "不承诺效果", "给出试错空间降低心理门槛"],
        },
    },
    {
        "seed_key": "seed_script_close",
        "kind": "script",
        "name": "促成下单话术",
        "content_json": {
            "scene": "close",
            "steps": [
                {"step": 1, "name": "确认需求", "script": "这个方案和您的需求比较匹配，您觉得可以吗？"},
                {"step": 2, "name": "降低门槛", "script": "今天新客有体验价，可以先拿一周的量试试。"},
                {"step": 3, "name": "售后安心", "script": "购买后有任何疑问随时可以来店里找我，也可以微信联系。"},
                {"step": 4, "name": "礼貌收尾", "script": "感谢您的信任，调理是个循序渐进的过程，慢慢来。"},
            ],
            "tips": ["不制造焦虑", "给足售后安全感", "成交后不松懈服务"],
        },
    },
    # ── 产品模板（kind=product）──
    {
        "seed_key": "seed_product_tea",
        "kind": "product",
        "name": "菊花枸杞茶（示例养生茶饮）",
        "content_json": {
            "type": "tea",
            "ingredients": ["菊花", "枸杞", "决明子"],
            "positioning": "清肝明目，适合长期用眼、易上火的日常调理",
            "usage": "每日 1 包，85°C 热水冲泡 3-5 分钟",
            "suitable": "适合大部分成年人群日常保健",
            "cautions": ["孕妇、经期女性慎用", "正在服药者先咨询医生", "如有不适停用并就医"],
            "sales_points": ["道地药材", "独立小包装", "无添加糖"],
        },
    },
    {
        "seed_key": "seed_product_soup",
        "kind": "product",
        "name": "四神汤料包（示例调理汤品）",
        "content_json": {
            "type": "soup",
            "ingredients": ["茯苓", "莲子", "芡实", "山药"],
            "positioning": "健脾养胃，适合脾胃虚弱、食欲不振的日常食养",
            "usage": "与排骨/瘦肉炖汤 1-1.5 小时，每周 2-3 次",
            "suitable": "适合脾胃虚弱人群日常食养",
            "cautions": ["湿热重者遵医嘱", "婴幼儿及特殊人群慎用", "如有不适停用并就医"],
            "sales_points": ["药食同源", "无硫熏", "炖煮方便"],
        },
    },
    # ── 项目模板（kind=project）──
    {
        "seed_key": "seed_project_cupping",
        "kind": "project",
        "name": "拔罐调理项目（示例门店项目）",
        "content_json": {
            "type": "service",
            "duration_min": 30,
            "flow": [
                {"step": 1, "name": "问询评估", "script": "先了解顾客体质与近期身体状况，排除禁忌。"},
                {"step": 2, "name": "操作准备", "script": "准备器具、消毒，向顾客说明流程与感受。"},
                {"step": 3, "name": "实施拔罐", "script": "按规范操作，过程中关注顾客反馈。"},
                {"step": 4, "name": "善后建议", "script": "说明拔罐后注意事项与日常调理建议。"},
            ],
            "cautions": ["皮肤破损/高热/孕妇禁忌", "操作人员须持证", "严禁过度拔罐"],
            "aftercare": ["4 小时内不洗澡", "多饮温水", "避免受凉"],
        },
    },
]


def seed_platform_templates(db: Session) -> int:
    """幂等种入平台级培训模板（DbTemplate，tenant_id=None 表示平台级）。

    按 seed_key 唯一性判断：已存在则跳过；返回本次种入数量。
    """
    from qihuang_platform.db.models import DbTemplate, TemplateOwnership

    seeded = 0
    for tpl in _SEED_TEMPLATES:
        seed_key = tpl["seed_key"]
        existing = db.query(DbTemplate).filter(
            DbTemplate.tenant_id.is_(None),
            DbTemplate.name == tpl["name"],
        ).first()
        if existing:
            continue
        row = DbTemplate(
            id=seed_key,  # 固定 ID，天然幂等
            tenant_id=None,  # 平台级模板
            name=tpl["name"],
            kind=tpl["kind"],
            content_json=tpl["content_json"],
            current_version="v1",
            created_by="system",
        )
        db.add(row)
        # 平台级归属：visibility=public，source=platform
        db.add(TemplateOwnership(
            template_id=seed_key,
            owner_tenant_id=None,
            owner_org_id=None,
            visibility="public",
            source="platform",
        ))
        seeded += 1
    if seeded:
        db.commit()
        logger.info("[store_coach.seed] 已种入 %d 个平台级培训模板", seeded)
    return seeded
