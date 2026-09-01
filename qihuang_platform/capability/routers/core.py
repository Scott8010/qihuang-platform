"""
核心能力路由 — 辨证推理 / 方剂分析 / 安全审查 / 图谱查询 / 智能对话 / 文献检索

映射策略：商业化平台路径 → 现有 8601 API
所有端点需 JWT 认证（通过 deps 注入）
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import require_capability_access
from qihuang_platform.gateway.response import success, error
from qihuang_platform.capability.proxy import proxy

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class DiagnoseRequest(BaseModel):
    symptoms: str = Field(..., description="症状描述，多个症状用逗号或顿号分隔")
    systems: Optional[list[str]] = Field(None, description="辨证体系列表，如 ['bagang','liujing','zangfu']")
    language: str = Field("zh", description="输出语言")

class SafetyCheckRequest(BaseModel):
    formula: Optional[str] = Field(None, description="方剂名称")
    herbs: Optional[str] = Field(None, description="中药名称（逗号分隔）")
    patient_condition: Optional[str] = Field(None, description="患者状况（如妊娠等）")

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户问题")
    history: Optional[list[dict]] = Field(None, description="对话历史 [{role, content}]")

class FormulaAnalysisRequest(BaseModel):
    formula_name: str = Field(..., description="方剂名称")

class ConsensusRequest(BaseModel):
    symptoms: str = Field(..., description="症状描述")
    models: Optional[list[str]] = Field(None, description="参与投票的模型列表")

class SizhenRequest(BaseModel):
    tongue: Optional[str] = Field(None, description="舌象描述")
    face: Optional[str] = Field(None, description="面象描述")
    pulse: Optional[str] = Field(None, description="脉象描述")
    symptoms: Optional[str] = Field(None, description="症状描述")


# ═══════════════════════════════════════════════════════════════
# 辨证推理（注意：具体路由必须在 /{system} 之前注册）
# ═══════════════════════════════════════════════════════════════

@router.post("/reasoning/diagnose", summary="综合辨证推理")
async def diagnose(req: DiagnoseRequest, user: dict = Depends(require_capability_access)):
    """
    综合辨证推理：八纲+六经+脏腑+方证对应+推理链。
    底层透传 GET /reasoning/api/diagnose
    """
    params = {"symptoms": req.symptoms, "language": req.language}
    if req.systems:
        params["systems"] = ",".join(req.systems)
    return await proxy.forward("GET", "/reasoning/api/diagnose", params=params)


@router.post("/reasoning/sizhen", summary="四诊合参")
async def sizhen_hezhan(req: SizhenRequest, user: dict = Depends(require_capability_access)):
    """
    四诊合参：舌诊+面诊+脉象综合辨证
    底层透传 POST /reasoning/api/sizhen
    """
    body = {}
    if req.tongue: body["tongue"] = req.tongue
    if req.face: body["face"] = req.face
    if req.pulse: body["pulse"] = req.pulse
    if req.symptoms: body["symptoms"] = req.symptoms
    return await proxy.forward("POST", "/reasoning/api/sizhen", json_body=body)


@router.post("/reasoning/consensus", summary="多模型共识投票")
async def consensus_vote(req: ConsensusRequest, user: dict = Depends(require_capability_access)):
    """
    多模型共识投票辨证
    底层透传 GET /reasoning/api/consensus
    """
    params = {"symptoms": req.symptoms}
    if req.models:
        params["models"] = ",".join(req.models)
    return await proxy.forward("GET", "/reasoning/api/consensus", params=params)


@router.post("/reasoning/formula", summary="方剂君臣佐使分析")
async def formula_analysis(req: FormulaAnalysisRequest, user: dict = Depends(require_capability_access)):
    """
    方剂君臣佐使详细分析
    底层透传 GET /formula-analysis/api/formula/{name}
    """
    return await proxy.forward("GET", f"/formula-analysis/api/formula/{req.formula_name}")


# ⚠️ 兜底单体系辨证 — 必须在所有具体路由之后注册
@router.post("/reasoning/{system}", summary="单体系辨证")
async def diagnose_system(
    system: str,
    req: DiagnoseRequest,
    user: dict = Depends(require_capability_access),
):
    """
    单体系辨证：bagang/liujing/zangfu/zabing/wenbing
    底层透传 GET /reasoning/api/{system}
    """
    valid_systems = ["bagang", "liujing", "zangfu", "zabing", "wenbing", "modification"]
    if system not in valid_systems:
        raise HTTPException(status_code=400, detail=error(code_key="INVALID_PARAM", message=f"不支持的辨证体系: {system}，有效值: {valid_systems}"))
    params = {"symptoms": req.symptoms, "language": req.language}
    return await proxy.forward("GET", f"/reasoning/api/{system}", params=params)


# ═══════════════════════════════════════════════════════════════
# 用药安全审查
# ═══════════════════════════════════════════════════════════════

@router.post("/safety/check", summary="用药安全审查")
async def safety_check(req: SafetyCheckRequest, user: dict = Depends(require_capability_access)):
    """
    配伍禁忌安全检查（方剂/中药/妊娠）
    底层透传 GET /reasoning/api/check_safety
    """
    params = {}
    if req.formula: params["formula"] = req.formula
    if req.herbs: params["herbs"] = req.herbs
    if req.patient_condition: params["patient_condition"] = req.patient_condition
    return await proxy.forward("GET", "/reasoning/api/check_safety", params=params)


# ═══════════════════════════════════════════════════════════════
# 图谱查询
# ═══════════════════════════════════════════════════════════════

@router.get("/graph/query", summary="图谱语义查询")
async def graph_query(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(require_capability_access),
):
    """图谱语义搜索，底层透传 GET /query/api/search"""
    return await proxy.forward("GET", "/api/v1/herbs", params={"q": q, "limit": limit})


@router.get("/graph/entities/{entity_type}/{entity_id}", summary="图谱实体详情")
async def graph_entity(
    entity_type: str,
    entity_id: str,
    user: dict = Depends(require_capability_access),
):
    """
    图谱节点详情，底层透传 /api/v1/{entity_type}/{entity_id}
    如 /graph/entities/herbs/人参
    """
    type_map = {"herbs": "herbs", "formulas": "formulas", "syndromes": "syndromes"}
    mapped = type_map.get(entity_type, entity_type)
    return await proxy.forward("GET", f"/api/v1/{mapped}/{entity_id}")


# ═══════════════════════════════════════════════════════════════
# 智能对话
# ═══════════════════════════════════════════════════════════════

@router.post("/agent/chat", summary="智能对话（中医问答）")
async def agent_chat(req: ChatRequest, user: dict = Depends(require_capability_access)):
    """
    中医智能对话，支持多轮对话
    底层透传 POST /chat/api/ask
    """
    return await proxy.forward("POST", "/chat/api/ask", json_body={"message": req.message})


# ═══════════════════════════════════════════════════════════════
# 文献检索
# ═══════════════════════════════════════════════════════════════

@router.get("/literature/search", summary="文献检索")
async def literature_search(
    q: Optional[str] = Query(None, description="关键词"),
    status: Optional[str] = Query(None, description="处理状态"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_capability_access),
):
    """文献库检索，底层透传 GET /library/api/list"""
    params = {"limit": limit, "offset": offset}
    if q: params["q"] = q
    if status: params["status"] = status
    return await proxy.forward("GET", "/library/api/list", params=params)


# ═══════════════════════════════════════════════════════════════
# REST 查询（中药/方剂/证候）
# ═══════════════════════════════════════════════════════════════

@router.get("/query/herbs", summary="中药查询")
async def query_herbs(
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_capability_access),
):
    """中药列表/搜索"""
    params = {"limit": limit, "offset": offset}
    if q: params["q"] = q
    return await proxy.forward("GET", "/api/v1/herbs", params=params)


@router.get("/query/herbs/{name}", summary="中药详情")
async def query_herb_detail(name: str, user: dict = Depends(require_capability_access)):
    """中药详情（归经/配伍/禁忌/所在方剂）"""
    return await proxy.forward("GET", f"/api/v1/herbs/{name}")


@router.get("/query/formulas", summary="方剂查询")
async def query_formulas(
    q: Optional[str] = Query(None),
    meridian: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_capability_access),
):
    """方剂列表/搜索"""
    params = {"limit": limit, "offset": offset}
    if q: params["q"] = q
    if meridian: params["meridian"] = meridian
    return await proxy.forward("GET", "/api/v1/formulas", params=params)


@router.get("/query/formulas/{name}", summary="方剂详情")
async def query_formula_detail(name: str, user: dict = Depends(require_capability_access)):
    """方剂详情（组成/证候/经典出处/安全检查）"""
    return await proxy.forward("GET", f"/api/v1/formulas/{name}")


@router.get("/query/syndromes", summary="证候查询")
async def query_syndromes(
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_capability_access),
):
    """证候列表/搜索"""
    params = {"limit": limit, "offset": offset}
    if q: params["q"] = q
    return await proxy.forward("GET", "/api/v1/syndromes", params=params)


@router.get("/query/syndromes/{name}", summary="证候详情")
async def query_syndrome_detail(name: str, user: dict = Depends(require_capability_access)):
    """证候详情（症状/方剂/六经）"""
    return await proxy.forward("GET", f"/api/v1/syndromes/{name}")


@router.get("/query/classics", summary="经典原文查询")
async def query_classics(
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_capability_access),
):
    """经典原文列表/搜索"""
    params = {"limit": limit, "offset": offset}
    if q: params["q"] = q
    return await proxy.forward("GET", "/api/v1/classics", params=params)
