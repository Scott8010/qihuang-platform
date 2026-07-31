"""
大健康能力路由 — 体质辨识 / 调理方案 / 健康档案 / 穴位保健

映射策略：商业化平台路径 → 现有 8601 API
"""
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from pydantic import BaseModel, Field

from qihuang_platform.db.models import (
    HealthProfile, HealthAssessment, HealthPlan, HealthEvent,
)
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.gateway.deps import get_current_user
from qihuang_platform.gateway.response import success, error
from qihuang_platform.capability.proxy import proxy
from qihuang_platform.acupoint.data import acupoint_data

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 体质 → 穴位 / 饮食 / 生活方式 / 商品 / 手法 映射表
# ═══════════════════════════════════════════════════════════

# 体质 → 推荐穴位名称
CONSTITUTION_ACUPOINTS: Dict[str, List[str]] = {
    "平和质": [],
    "气虚质": ["脾俞", "足三里", "气海"],
    "阳虚质": ["关元", "命门", "神阙"],
    "阴虚质": ["太溪", "三阴交", "涌泉"],
    "痰湿质": ["丰隆", "阴陵泉", "中脘"],
    "湿热质": ["阴陵泉", "曲池", "合谷"],
    "血瘀质": ["血海", "膈俞", "三阴交"],
    "气郁质": ["太冲", "期门", "膻中"],
    "特禀质": ["足三里", "风池", "大椎"],
}

# 体质 → 饮食建议
CONSTITUTION_DIET: Dict[str, Dict] = {
    "平和质": {
        "principle": "均衡饮食，不偏不倚",
        "recommend": ["五谷杂粮", "蔬菜水果", "适量优质蛋白", "坚果"],
        "avoid": ["偏食", "过食辛辣", "暴饮暴食"],
    },
    "气虚质": {
        "principle": "益气健脾",
        "recommend": ["山药", "黄芪", "红枣", "鸡肉", "粳米", "土豆"],
        "avoid": ["生冷食物", "油腻食物", "难消化食物"],
    },
    "阳虚质": {
        "principle": "温阳散寒",
        "recommend": ["羊肉", "生姜", "桂圆", "韭菜", "核桃", "板栗"],
        "avoid": ["冷饮", "西瓜", "苦瓜", "绿豆等寒凉食物"],
    },
    "阴虚质": {
        "principle": "滋阴清热",
        "recommend": ["银耳", "百合", "枸杞", "鸭肉", "黑芝麻", "桑葚"],
        "avoid": ["辛辣", "烧烤", "羊肉等温热食物"],
    },
    "痰湿质": {
        "principle": "化痰祛湿，健脾化浊",
        "recommend": ["薏苡仁", "冬瓜", "萝卜", "海带", "荷叶", "赤小豆"],
        "avoid": ["甜腻食物", "肥肉", "奶油", "酒类"],
    },
    "湿热质": {
        "principle": "清热利湿",
        "recommend": ["绿豆", "苦瓜", "黄瓜", "薏苡仁", "芹菜", "冬瓜"],
        "avoid": ["辛辣", "酒类", "烧烤", "煎炸食物"],
    },
    "血瘀质": {
        "principle": "活血化瘀",
        "recommend": ["山楂", "玫瑰花", "黑豆", "醋", "桃仁", "红花"],
        "avoid": ["寒凉收涩食物", "高脂肪食物"],
    },
    "气郁质": {
        "principle": "疏肝理气，解郁散结",
        "recommend": ["柑橘", "佛手", "菊花茶", "荞麦", "刀豆", "蘑菇"],
        "avoid": ["收敛酸涩食物", "冰冷食物"],
    },
    "特禀质": {
        "principle": "益气固表，抗敏防病",
        "recommend": ["灵芝", "黄芪", "大枣", "蜂蜜", "粳米"],
        "avoid": ["海鲜", "蚕豆", "已知过敏食物"],
    },
}

# 体质 → 生活方式建议
CONSTITUTION_LIFESTYLE: Dict[str, Dict] = {
    "平和质": {
        "exercise": "规律有氧运动，如快走、太极拳、游泳",
        "sleep": "保持规律作息，早睡早起，7-8小时睡眠",
        "emotion": "保持心情平和，劳逸结合",
    },
    "气虚质": {
        "exercise": "柔和运动，如太极、八段锦，忌剧烈运动和大汗",
        "sleep": "充足睡眠，避免熬夜，适当午休",
        "emotion": "避免过度思虑，保持乐观",
    },
    "阳虚质": {
        "exercise": "温热运动，如慢跑、站桩，忌冷水浴和冬泳",
        "sleep": "早睡晚起，注意保暖，避免空调直吹",
        "emotion": "保持积极乐观心态，多晒太阳",
    },
    "阴虚质": {
        "exercise": "中等强度，如游泳、瑜伽，忌出汗过多",
        "sleep": "午休30分钟，避免熬夜",
        "emotion": "避免烦躁易怒，静心养神",
    },
    "痰湿质": {
        "exercise": "持续有氧运动，如慢跑、游泳，逐渐加量",
        "sleep": "避免久卧，保持活跃",
        "emotion": "避免安逸贪睡，积极参与社交",
    },
    "湿热质": {
        "exercise": "大运动量，如跑步、球类，出汗为度",
        "sleep": "避免熬夜和过度劳累",
        "emotion": "保持心态平和，避免急躁",
    },
    "血瘀质": {
        "exercise": "促进血液循环，如舞蹈、太极剑、健步走",
        "sleep": "规律作息，避免久坐久卧",
        "emotion": "保持心情舒畅，多与人交流",
    },
    "气郁质": {
        "exercise": "户外群体运动，如跑步、登山、球类",
        "sleep": "规律睡眠，睡前避免咖啡浓茶",
        "emotion": "主动社交，疏解压力，培养兴趣爱好",
    },
    "特禀质": {
        "exercise": "适度运动，增强体质，如太极、散步",
        "sleep": "规律作息，保证充足睡眠",
        "emotion": "避免过敏原刺激，保持心态稳定",
    },
}

# 体质 → 商品推荐
CONSTITUTION_PRODUCTS: Dict[str, List[Dict]] = {
    "平和质": [
        {"name": "养生茶饮组合", "category": "茶饮", "desc": "日常调理养生茶"},
    ],
    "气虚质": [
        {"name": "黄芪精口服液", "category": "滋补", "desc": "益气健脾"},
        {"name": "山药薏米粉", "category": "食疗", "desc": "健脾益气"},
    ],
    "阳虚质": [
        {"name": "金匮肾气丸", "category": "中成药", "desc": "温补肾阳"},
        {"name": "艾灸条", "category": "理疗", "desc": "温阳散寒，用于关元、命门穴位"},
    ],
    "阴虚质": [
        {"name": "六味地黄丸", "category": "中成药", "desc": "滋阴补肾"},
        {"name": "银耳百合羹", "category": "食疗", "desc": "滋阴润燥"},
    ],
    "痰湿质": [
        {"name": "参苓白术散", "category": "中成药", "desc": "健脾祛湿"},
        {"name": "薏苡仁茶", "category": "茶饮", "desc": "利湿化痰"},
    ],
    "湿热质": [
        {"name": "龙胆泻肝丸", "category": "中成药", "desc": "清利湿热"},
        {"name": "绿豆薏仁汤", "category": "食疗", "desc": "清热利湿"},
    ],
    "血瘀质": [
        {"name": "血府逐瘀丸", "category": "中成药", "desc": "活血化瘀"},
        {"name": "玫瑰花茶", "category": "茶饮", "desc": "理气活血"},
    ],
    "气郁质": [
        {"name": "逍遥丸", "category": "中成药", "desc": "疏肝解郁"},
        {"name": "佛手柑茶", "category": "茶饮", "desc": "理气宽中"},
    ],
    "特禀质": [
        {"name": "玉屏风散", "category": "中成药", "desc": "益气固表"},
        {"name": "灵芝孢子粉", "category": "保健", "desc": "增强免疫力"},
    ],
}

# 体质 → 保健手法
CONSTITUTION_TECHNIQUE: Dict[str, str] = {
    "平和质": "日常按揉保健",
    "气虚质": "温灸补法，轻柔按揉",
    "阳虚质": "艾灸为主，温补阳气",
    "阴虚质": "轻柔按揉，忌重刺激",
    "痰湿质": "中等力度按揉，配合艾灸",
    "湿热质": "点按泻法，清热利湿",
    "血瘀质": "点按配合推拿，活血化瘀",
    "气郁质": "揉按疏理，配合深呼吸",
    "特禀质": "轻柔按揉，温和刺激",
}

# 免责声明
HEALTH_DISCLAIMER = (
    "本方案由AI辅助生成，仅供参考，不作为医疗诊断或治疗依据。"
    "如有健康问题请及时就医，遵医嘱进行治疗。"
)

# 方案生成状态（内存态，开发阶段使用，生产环境替换为 Redis）
_plan_status: Dict[str, str] = {}


# ═══════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════

class ConstitutionAssessRequest(BaseModel):
    """体质辨识请求"""
    tongue: Optional[str] = Field(None, description="舌象描述")
    face: Optional[str] = Field(None, description="面象描述")
    pulse: Optional[str] = Field(None, description="脉象描述")
    symptoms: Optional[str] = Field(None, description="症状描述（逗号分隔）")


class PlanCreateRequest(BaseModel):
    """调理方案生成请求"""
    assessment_id: str = Field(..., description="体质评估ID")
    profile_id: Optional[str] = Field(None, description="健康档案ID")


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _get_user_id(user: dict) -> str:
    """从用户信息中提取 user_id（兼容 sub 和 user_id 两种字段）"""
    return user.get("sub") or user.get("user_id", "")


def _get_tenant_id(user: dict) -> str:
    """从用户信息中提取 tenant_id"""
    return user.get("tenant_id", "")


def _build_acupoint_detail(name: str, technique: str) -> Optional[Dict]:
    """根据穴位名称查找穴位详细信息"""
    results = acupoint_data.search(name)
    if results:
        pt = results[0]
        return {
            "name": pt["name"],
            "code": pt["code"],
            "meridian": pt["meridian"]["name"],
            "meridian_code": pt["meridian"]["code"],
            "benefit": pt.get("gongneng", ""),
            "technique": technique,
            "location": pt.get("location", ""),
        }
    return None


async def _generate_plan_background(
    plan_id: str,
    assessment_id: str,
    tenant_id: str,
    user_id: str,
    profile_id: Optional[str],
):
    """后台生成调理方案"""
    db = SessionLocal()
    try:
        # 查询评估结果
        assessment = db.query(HealthAssessment).filter_by(id=assessment_id).first()
        if not assessment:
            _plan_status[plan_id] = "failed"
            return

        constitution_type = assessment.constitution_type or "平和质"

        # 透传到 8601 获取辨证结果（复用四诊合参接口）
        sizhen_body: Dict[str, Any] = {}
        if assessment.raw_answers:
            sizhen_body = assessment.raw_answers
        if assessment.ai_analysis:
            sizhen_body["analysis"] = assessment.ai_analysis

        await proxy.forward("POST", "/reasoning/api/sizhen", json_body=sizhen_body)

        # 生成饮食建议
        diet = CONSTITUTION_DIET.get(constitution_type, CONSTITUTION_DIET["平和质"])

        # 生成生活方式建议
        lifestyle = CONSTITUTION_LIFESTYLE.get(
            constitution_type, CONSTITUTION_LIFESTYLE["平和质"]
        )

        # 生成穴位保健方案
        acupoint_names = CONSTITUTION_ACUPOINTS.get(constitution_type, [])
        technique = CONSTITUTION_TECHNIQUE.get(constitution_type, "日常按揉保健")
        acupoint_list = []
        for name in acupoint_names:
            detail = _build_acupoint_detail(name, technique)
            if detail:
                acupoint_list.append(detail)

        # 生成商品推荐
        products = CONSTITUTION_PRODUCTS.get(constitution_type, [])

        # 更新方案记录
        plan = db.query(HealthPlan).filter_by(id=plan_id).first()
        if plan:
            plan.diet_plan = diet
            plan.lifestyle_plan = lifestyle
            plan.acupoint_plan = {
                "recommended_acupoints": acupoint_list,
                "technique": technique,
            }
            plan.product_recommendations = products
            plan.disclaimer = HEALTH_DISCLAIMER
            db.commit()

        # 记录健康事件
        event = HealthEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="plan_generated",
            event_data={
                "plan_id": plan_id,
                "constitution_type": constitution_type,
            },
        )
        db.add(event)
        db.commit()

        _plan_status[plan_id] = "completed"
    except Exception as e:
        _plan_status[plan_id] = f"failed: {str(e)}"
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# 端点 1: POST /constitution/assess — 体质辨识
# ═══════════════════════════════════════════════════════════

@router.post("/constitution/assess", summary="体质辨识")
async def constitution_assess(
    req: ConstitutionAssessRequest,
    user: dict = Depends(get_current_user),
):
    """
    四诊合参 → 体质辨识 + 调理方案
    底层透传 POST /reasoning/api/sizhen（四诊合参含体质分析）
    """
    body = {}
    if req.tongue:
        body["tongue"] = req.tongue
    if req.face:
        body["face"] = req.face
    if req.pulse:
        body["pulse"] = req.pulse
    if req.symptoms:
        body["symptoms"] = req.symptoms
    return await proxy.forward("POST", "/reasoning/api/sizhen", json_body=body)


# ═══════════════════════════════════════════════════════════
# 端点 2: GET /constitutions — 九大体质列表
# ═══════════════════════════════════════════════════════════

@router.get("/constitutions", summary="九大体质列表")
async def list_constitutions(user: dict = Depends(get_current_user)):
    """获取九大体质类型列表"""
    return await proxy.forward("GET", "/api/v1/constitutions")


# ═══════════════════════════════════════════════════════════
# 端点 3: GET /meridians — 六经列表
# ═══════════════════════════════════════════════════════════

@router.get("/meridians", summary="六经列表")
async def list_meridians(user: dict = Depends(get_current_user)):
    """获取六经分类列表"""
    return await proxy.forward("GET", "/api/v1/meridians")


# ═══════════════════════════════════════════════════════════
# 端点 4: POST /plans — 调理方案生成（异步轮询模式）
# ═══════════════════════════════════════════════════════════

@router.post("/plans", summary="生成调理方案")
async def create_plan(
    req: PlanCreateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    根据体质评估结果生成调理方案（饮食 / 生活方式 / 穴位保健 / 商品推荐）

    异步轮询模式：立即返回 plan_id，后台生成方案内容，
    客户端通过 GET /plans/{plan_id} 轮询查询生成状态。
    """
    tenant_id = _get_tenant_id(user)
    user_id = _get_user_id(user)

    db = SessionLocal()
    try:
        # 校验评估记录是否存在
        assessment = db.query(HealthAssessment).filter_by(
            id=req.assessment_id, tenant_id=tenant_id
        ).first()
        if not assessment:
            return error("NOT_FOUND", "体质评估记录不存在")

        # 创建方案记录（方案内容暂为空，后台填充）
        plan_id = str(uuid.uuid4())
        plan = HealthPlan(
            id=plan_id,
            tenant_id=tenant_id,
            user_id=user_id,
            profile_id=req.profile_id or assessment.profile_id,
            assessment_id=req.assessment_id,
            diet_plan=None,
            lifestyle_plan=None,
            acupoint_plan=None,
            product_recommendations=None,
            disclaimer=HEALTH_DISCLAIMER,
        )
        db.add(plan)
        db.commit()

        # 设置生成状态为「生成中」
        _plan_status[plan_id] = "generating"

        # 启动后台生成任务
        background_tasks.add_task(
            _generate_plan_background,
            plan_id,
            req.assessment_id,
            tenant_id,
            user_id,
            req.profile_id,
        )

        return success(
            data={"plan_id": plan_id, "status": "generating"},
            message="方案生成中，请稍后轮询查询",
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# 端点 5: GET /plans/{plan_id} — 查询调理方案状态和详情
# ═══════════════════════════════════════════════════════════

@router.get("/plans/{plan_id}", summary="查询调理方案")
async def get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """查询调理方案状态和详情，返回方案详情或「生成中」状态"""
    tenant_id = _get_tenant_id(user)

    db = SessionLocal()
    try:
        plan = db.query(HealthPlan).filter_by(
            id=plan_id, tenant_id=tenant_id
        ).first()
        if not plan:
            return error("NOT_FOUND", "调理方案不存在")

        # 检查生成状态
        status = _plan_status.get(plan_id, "completed")

        # 仍在生成中
        if status == "generating":
            return success(
                data={"plan_id": plan_id, "status": "generating"},
                message="方案生成中，请稍后查询",
            )

        # 生成失败
        if status.startswith("failed"):
            return error("INTERNAL_ERROR", f"方案生成失败: {status}")

        # 生成完成，返回完整方案
        plan_data = {
            "plan_id": plan.id,
            "status": "completed",
            "assessment_id": plan.assessment_id,
            "profile_id": plan.profile_id,
            "constitution_type": None,
            "diet_plan": plan.diet_plan,
            "lifestyle_plan": plan.lifestyle_plan,
            "acupoint_plan": plan.acupoint_plan,
            "product_recommendations": plan.product_recommendations,
            "disclaimer": plan.disclaimer,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }

        # 补充体质类型
        if plan.assessment_id:
            assessment = db.query(HealthAssessment).filter_by(
                id=plan.assessment_id
            ).first()
            if assessment:
                plan_data["constitution_type"] = assessment.constitution_type

        return success(data=plan_data)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# 端点 6: GET /archive/timeline — 健康档案时间轴
# ═══════════════════════════════════════════════════════════

@router.get("/archive/timeline", summary="健康档案时间轴")
async def health_timeline(user: dict = Depends(get_current_user)):
    """
    查询用户的健康档案时间轴

    聚合 HealthAssessment + HealthPlan + HealthEvent，按时间倒序排列。
    """
    tenant_id = _get_tenant_id(user)
    user_id = _get_user_id(user)

    db = SessionLocal()
    try:
        timeline: List[Dict[str, Any]] = []

        # 查询体质评估记录
        assessments = db.query(HealthAssessment).filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).all()
        for a in assessments:
            timeline.append({
                "type": "assessment",
                "title": f"体质辨识 — {a.constitution_type or '未知'}",
                "data": {
                    "assessment_id": a.id,
                    "constitution_type": a.constitution_type,
                    "scores": a.scores,
                    "ai_analysis": a.ai_analysis,
                },
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })

        # 查询调理方案记录
        plans = db.query(HealthPlan).filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).all()
        for p in plans:
            timeline.append({
                "type": "plan",
                "title": "调理方案生成",
                "data": {
                    "plan_id": p.id,
                    "assessment_id": p.assessment_id,
                    "has_diet": p.diet_plan is not None,
                    "has_lifestyle": p.lifestyle_plan is not None,
                    "has_acupoint": p.acupoint_plan is not None,
                    "has_products": p.product_recommendations is not None,
                },
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })

        # 查询健康事件记录
        events = db.query(HealthEvent).filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).all()
        for e in events:
            timeline.append({
                "type": "event",
                "title": e.event_type or "健康事件",
                "data": e.event_data,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            })

        # 按时间倒序排列
        timeline.sort(key=lambda x: x["created_at"] or "", reverse=True)

        return success(data={"timeline": timeline, "total": len(timeline)})
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# 端点 7: GET /acupoints/guide — 穴位保健指导
# ═══════════════════════════════════════════════════════════

@router.get("/acupoints/guide", summary="穴位保健指导")
async def acupoint_guide(
    constitution_type: str = Query(..., description="体质类型，如：气虚质"),
    meridian: Optional[str] = Query(None, description="可选经络代码，如：LU、ST"),
    user: dict = Depends(get_current_user),
):
    """
    基于体质推荐穴位保健方案

    返回推荐穴位列表（含名称、代码、经络、功效、手法），
    可通过 meridian 参数进一步聚焦到特定经络。
    """
    # 获取体质对应的推荐穴位名称
    acupoint_names = CONSTITUTION_ACUPOINTS.get(constitution_type, [])
    technique = CONSTITUTION_TECHNIQUE.get(constitution_type, "日常按揉保健")

    # 构建穴位详情列表
    recommended_acupoints: List[Dict[str, Any]] = []
    for name in acupoint_names:
        detail = _build_acupoint_detail(name, technique)
        if detail:
            # 如果指定了经络过滤，只返回对应经络的穴位
            if meridian:
                if detail.get("meridian_code") == meridian.upper():
                    recommended_acupoints.append(detail)
            else:
                recommended_acupoints.append(detail)

    # 如果指定了经络，获取该经络的全部穴位作为参考
    meridian_focus = None
    if meridian:
        meridian_points = acupoint_data.get_by_meridian(meridian)
        if meridian_points:
            meridian_list = acupoint_data.list_meridians()
            meridian_detail = next(
                (m for m in meridian_list if m["code"] == meridian.upper()), None
            )
            meridian_focus = {
                "code": meridian.upper(),
                "name": meridian_detail["name"] if meridian_detail else meridian.upper(),
                "acupoint_count": len(meridian_points),
                "acupoints": [
                    {
                        "code": p["code"],
                        "name": p["chinese_name"],
                        "pinyin": p["pinyin"],
                    }
                    for p in meridian_points
                ],
            }

    return success(data={
        "constitution": constitution_type,
        "recommended_acupoints": recommended_acupoints,
        "meridian_focus": meridian_focus,
        "technique": technique,
        "disclaimer": HEALTH_DISCLAIMER,
    })
