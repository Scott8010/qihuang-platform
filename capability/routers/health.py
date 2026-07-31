"""
大健康能力路由 — 体质辨识 / 养生方案

映射策略：商业化平台路径 → 现有 8601 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_user
from qihuang_platform.capability.proxy import proxy

router = APIRouter()


class ConstitutionAssessRequest(BaseModel):
    """体质辨识请求"""
    tongue: Optional[str] = Field(None, description="舌象描述")
    face: Optional[str] = Field(None, description="面象描述")
    pulse: Optional[str] = Field(None, description="脉象描述")
    symptoms: Optional[str] = Field(None, description="症状描述（逗号分隔）")


@router.post("/constitution/assess", summary="体质辨识")
async def constitution_assess(req: ConstitutionAssessRequest, user: dict = Depends(get_current_user)):
    """
    四诊合参 → 体质辨识 + 调理方案
    底层透传 POST /reasoning/api/sizhen（四诊合参含体质分析）
    """
    body = {}
    if req.tongue: body["tongue"] = req.tongue
    if req.face: body["face"] = req.face
    if req.pulse: body["pulse"] = req.pulse
    if req.symptoms: body["symptoms"] = req.symptoms
    return await proxy.forward("POST", "/reasoning/api/sizhen", json_body=body)


@router.get("/constitutions", summary="九大体质列表")
async def list_constitutions(user: dict = Depends(get_current_user)):
    """获取九大体质类型列表"""
    return await proxy.forward("GET", "/api/v1/constitutions")


@router.get("/meridians", summary="六经列表")
async def list_meridians(user: dict = Depends(get_current_user)):
    """获取六经分类列表"""
    return await proxy.forward("GET", "/api/v1/meridians")
