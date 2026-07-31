"""
中台能力层 — 封装现有 API 核心能力为商业化接口

路由结构：
- /api/v1/core/*  核心能力（辨证推理/方剂分析/安全审查/图谱查询/智能对话/文献检索）
- /api/v1/health/* 大健康能力（体质辨识/养生方案）
- /api/v1/med/*    医疗专业能力（处方审查/临床辅助）
"""
from fastapi import APIRouter
from qihuang_platform.capability.routers.core import router as core_router
from qihuang_platform.capability.routers.health import router as health_router
from qihuang_platform.capability.routers.acupoint import router as acupoint_router
from qihuang_platform.capability.routers.medical import router as medical_router
from qihuang_platform.capability.routers.education import router as education_router

capability_router = APIRouter()
capability_router.include_router(core_router, prefix="/api/v1/core", tags=["中台-核心能力"])
capability_router.include_router(health_router, prefix="/api/v1/health", tags=["中台-大健康"])
# 3D穴位端点挂载：/api/v1/core/acupoint/*
capability_router.include_router(acupoint_router, prefix="/api/v1/core")
capability_router.include_router(medical_router, prefix="/api/v1/med", tags=["中台-医疗专业"])
capability_router.include_router(education_router, prefix="/api/v1/edu", tags=["中台-培训场景"])

__all__ = ["capability_router"]
