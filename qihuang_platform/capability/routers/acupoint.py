"""
穴位3D能力路由 — /api/v1/core/acupoint/*

子任务5: 3个新core端点（替换mock）
- GET  /acupoint/model       — 3D模型资源元信息(CDN地址/版本/皮肤配置)
- POST /acupoint/guide       — 穴位指导数据(按体质/经络/节气/症状)
- GET  /acupoint/meridians/{code} — 经络循行路径与穴位坐标
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_user, get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.acupoint.data import acupoint_data

router = APIRouter(prefix="/acupoint", tags=["中台-3D穴位"])


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class AcupointGuideRequest(BaseModel):
    """穴位指导请求"""
    mode: str = Field("symptom", description="指导模式: symptom/constitution/meridian/season")
    query: str = Field(..., description="查询内容（症状/体质/经络码/节气）")
    constitution: Optional[str] = Field(None, description="体质类型（mode=constitution时使用）")
    limit: int = Field(5, ge=1, le=20, description="返回穴位数量")


# ═══════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════

@router.get("/model")
async def get_acupoint_model(user=Depends(get_current_user)):
    """
    获取3D模型资源元信息

    返回模型列表、CDN地址、版本号、皮肤配置等。
    客户端根据此响应加载对应的glTF/OBJ模型文件。
    """
    meta = acupoint_data.get_model_meta()
    return success(data=meta)


@router.post("/guide")
async def acupoint_guide(req: AcupointGuideRequest, user=Depends(get_current_user)):
    """
    穴位保健指导

    根据症状/体质/经络/节气推荐相关穴位，返回穴位详情与保健建议。

    模式说明:
    - symptom: 按症状关键词匹配穴位功能描述
    - constitution: 按中医体质推荐调理穴位
    - meridian: 按经络码获取该经络关键穴位
    - season: 按节气推荐应季保健穴位
    """
    results = acupoint_data.search(req.query)

    if not results:
        return success(data={
            "mode": req.mode,
            "query": req.query,
            "acupoints": [],
            "advice": f"未找到与「{req.query}」相关的穴位，请尝试其他关键词。",
        })

    results = results[:req.limit]

    # 生成保健建议
    names = "、".join([r["name"] for r in results[:3]])
    meridian_names = list(set(r["meridian"]["name"] for r in results))

    q = req.query
    advice_templates = {
        "symptom": f"针对「{q}」相关症状，推荐按摩{names}等穴位，"
                   f"这些穴位主要分布在{','.join(meridian_names[:2])}上。"
                   f"每个穴位用拇指按压3-5分钟，力度以酸胀为度，每日1-2次。",
        "constitution": f"根据{q}体质特点，推荐调理穴位{names}。"
                        f"建议配合艾灸或温灸，每次15分钟，每周2-3次。",
        "meridian": f"{q}经络关键穴位：{names}。沿经络走向轻柔推按，"
                    f"重点按压上述穴位，每条经络推按5-10分钟。",
        "season": f"{q}时节保健穴位推荐：{names}。顺应节气变化调理身体，"
                  f"每个穴位按摩3-5分钟。",
    }

    return success(data={
        "mode": req.mode,
        "query": req.query,
        "acupoints": [acupoint_data._serialize_point(
            acupoint_data.get_by_code(r["code"]) or r
        ) for r in results],
        "advice": advice_templates.get(req.mode, advice_templates["symptom"]),
        "total_found": len(results),
    })


@router.get("/meridians/{meridian_code}")
async def get_meridian_path(
    meridian_code: str,
    include_acupoints: bool = Query(True, description="是否包含各穴位详情"),
    user=Depends(get_current_user),
):
    """
    获取经络循行路径

    返回经络的穴位坐标序列（按循行顺序），可用于前端3D渲染经络线。

    经络码: LU/LI/ST/SP/HT/SI/BL/KI/PC/TE/GB/LR/CV/GV
    """
    meridian_code = meridian_code.upper()

    # 验证经络码
    valid_codes = list(acupoint_data.list_meridians())
    valid_code_set = {m["code"] for m in valid_codes}
    if meridian_code not in valid_code_set:
        valid_str = ", ".join(sorted(valid_code_set))
        return error("INVALID_PARAM", f"不支持的经络码: {meridian_code}，有效值: {valid_str}")

    path = acupoint_data.get_meridian_path(meridian_code)
    if not path:
        return error("NOT_FOUND", f"经络 {meridian_code} 无数据")

    # 如果不需要穴位详情，只返回坐标
    if not include_acupoints:
        path_coords = path["path_points"]
        path["path_coords_only"] = [p["position_3d"] for p in path_coords]

    return success(data=path)


@router.get("/meridians")
async def list_meridians(user=Depends(get_current_user)):
    """
    列出所有经络及其基本信息

    包含经络名称、五行属性、阴阳、穴位数量、颜色等。
    """
    meridians = acupoint_data.list_meridians()
    return success(data={
        "meridians": meridians,
        "total": len(meridians),
    })


@router.get("/search")
async def search_acupoints(
    keyword: str = Query(..., description="搜索关键词（穴位名/拼音/编码/功能）"),
    limit: int = Query(10, ge=1, le=50),
    user=Depends(get_current_user),
):
    """
    搜索穴位

    支持按穴位名称、拼音、编码、功能描述搜索。
    """
    results = acupoint_data.search(keyword)[:limit]
    return success(data={
        "keyword": keyword,
        "acupoints": results,  # search() already returns serialized points
        "total_found": len(results),
    })


@router.get("/symptom-prescription")
async def symptom_prescription(
    symptoms: str = Query(..., description="症状名，逗号分隔，如 近视眼,眼疲劳"),
    user=Depends(get_current_principal),
):
    """
    按症状查穴位处方（主穴必选 / 配穴随症 / 经络 / 疗法 / 调理建议）

    数据来源：qihuang_platform/capability/routers/symptom_acupoints.json（提取自岐黄三境.html SYMPTOMS）
    归属：3D穴位套餐（module:3d），与 /acupoint/guide 同级。
    PAD 接待流程「症状查穴位」抽屉右侧面板消费此接口。

    注册顺序说明：本端点必须定义在 catch-all /{acupoint_code} 之前，
    否则 Starlette 会按注册顺序把 /symptom-prescription 匹配到 catch-all 上。
    """
    import json as _json
    import os as _os

    db_path = _os.path.join(_os.path.dirname(__file__), "symptom_acupoints.json")
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            db = _json.load(f)
    except FileNotFoundError:
        return error("DATA_MISSING", "症状处方数据未加载(symptom_acupoints.json)")

    sym_db = db.get("symptoms", {})
    therapy_map = db.get("therapy_map", {})

    req = [s.strip() for s in symptoms.split(",") if s.strip()]
    prescriptions = []
    merged_main, merged_support, merged_mer, merged_ther = set(), set(), set(), set()

    for s in req:
        info = sym_db.get(s)
        if not info:
            continue
        therapy_names = [therapy_map.get(t, t) for t in info.get("therapy", [])]
        prescriptions.append({
            "symptom": s,
            "meridians": info.get("meridians", []),
            "main": info.get("main", []),
            "support": info.get("support", []),
            "therapy": therapy_names,
            "desc": info.get("desc", ""),
            "source": info.get("source", ""),
        })
        merged_main.update(info.get("main", []))
        merged_support.update(info.get("support", []))
        merged_mer.update(info.get("meridians", []))
        merged_ther.update(info.get("therapy", []))

    return success(data={
        "symptoms": req,
        "prescriptions": prescriptions,
        "merged": {
            "main": list(merged_main),
            "support": list(merged_support),
            "meridians": list(merged_mer),
            "therapy": [therapy_map.get(t, t) for t in merged_ther],
        },
        "total_found": len(prescriptions),
        "total_requested": len(req),
    })


@router.get("/{acupoint_code}")
async def get_acupoint_detail(
    acupoint_code: str,
    user=Depends(get_current_principal),
):
    """
    获取单个穴位详情

    包含3D坐标、位置、功能、释义等完整信息。
    """
    pt = acupoint_data.get_by_code(acupoint_code.upper())
    if not pt:
        return error("NOT_FOUND", f"穴位 {acupoint_code} 不存在")
    return success(data=acupoint_data._serialize_point(pt))
