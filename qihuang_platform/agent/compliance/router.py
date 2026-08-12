"""
第一个 Agent 能力：内容合规审核（business_embedded，融入业务流，非对话窗口）。

端点（全部需 JWT，tenant_id 由网关注入 request.state）：
  POST /api/v1/agent/compliance/scan      门店送审文案 -> L0+L1+L2 三轨融合判定
  POST /api/v1/agent/compliance/feedback  人工结论回写（钉 material_id，客观真实）
  GET  /api/v1/agent/compliance/dashboard 四态看板（按门店行级隔离）
  GET  /api/v1/agent/compliance/audit     审计日志查询（仅管理员）

底层架构（老黄 2026-08-11/12 拍板「从底层搭建」）：
  - L1 合规知识底座（kb.ComplianceKB）：Neo4j 独立 label `ComplianceClause` 横向隔离
  - L2 语义推理引擎（engine_l2.ComplianceEngineL2）：L0 硬红线 + L1 检索 + L2 LLM
  - 回写钉业务实体（store.ComplianceStore）：material_key→MAT-XXXX 幂等，不替门店改文案

嵌套多租户隔离：
    8602 tenant(颐掌柜) ⊇ 颐掌柜门店(store_id)
    - store_id 作为 institution_id（行级沙箱键）隔离各家门店数据；
    - tenant_id 附运营平台计量 / 审计 / 跨租户汇聚，不污染引擎数据。
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.compliance.engine_l2 import compliance_engine
from qihuang_platform.agent.compliance.audit import (
    AuditStore, make_scan_audit, make_feedback_audit,
)
import os

router = APIRouter()

# 审计日志存储（与 materials.jsonl 同目录）
_AUDIT_PATH = os.path.join(
    os.path.dirname(__file__), "seed", "audit.jsonl"
)
_audit_store = AuditStore(_AUDIT_PATH)


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class ComplianceScanRequest(BaseModel):
    text: str = Field(..., min_length=1, description="待检经营文案")
    store_id: str = Field(..., description="门店 ID（颐掌柜业务租户，行级沙箱键）")
    material_type: Optional[str] = Field(None, description="物料类型，如 朋友圈/海报/直播话术")
    port: Optional[str] = Field(None, description="来源端，如 wechat/store_page")
    material_key: Optional[str] = Field(
        None, description="业务主键（同业务反复重提时给定，幂等覆盖同一条物料，避免看板堆积历史）"
    )
    persist: bool = Field(True, description="是否真实入库（false 仅试算不落库）")


class ComplianceFeedbackRequest(BaseModel):
    material_id: str = Field(..., description="物料 ID（scan 返回的 MAT-XXXX）")
    decision: Literal["keep", "override", "remediated", "ignore", "escalate"] = Field(
        ..., description="人工结论：keep保留/override强制拦截/remediated已整改/ignore忽略/escalate升级"
    )
    action_taken: Literal["none", "released", "replaced", "removed", "ticket_created"] = Field(
        ..., description="执行动作：none无/released放行/replaced已替换/removed已移除/ticket_created已建工单"
    )
    note: Optional[str] = Field(None, description="人工备注")
    operator: Optional[str] = Field(None, description="操作员标识（缺省取当前登录用户）")


# ═══════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════

@router.post("/compliance/scan")
async def compliance_scan(
    req: ComplianceScanRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """门店送审：L0 硬红线 + L1 检索 + L2 推理三轨融合，回写钉业务实体。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    result = await compliance_engine.analyze(
        text=req.text,
        material_type=req.material_type,
        port=req.port,
        institution_id=req.store_id,
        material_key=req.material_key,
        persist=req.persist,
    )
    # 附运营平台租户上下文：供 8602 侧计量/审计/跨租户汇聚，不污染引擎库
    result["tenant_id"] = tenant_id
    result["store_id"] = req.store_id
    # 审计留痕
    _audit_store.append(make_scan_audit(
        operator=getattr(request.state, "user_id", "unknown"),
        tenant_id=tenant_id,
        store_id=req.store_id,
        material_id=result["material_id"],
        state=result["state"],
        hit_count=result.get("hit_count", 0),
        text_preview=req.text[:120],
    ))
    return success(data=result)


@router.post("/compliance/feedback")
async def compliance_feedback(
    req: ComplianceFeedbackRequest,
    request: Request,
    user: dict = Depends(get_current_admin),
):
    """人工结论回写：钉在 scan 返回的 material_id 上，客观真实，不替门店改文案。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    # 记录变更前状态（用于审计）
    material_before = compliance_engine.store.get(req.material_id)
    state_before = material_before.get("state") if material_before else None
    result = await compliance_engine.feedback(
        material_id=req.material_id,
        decision=req.decision,
        action_taken=req.action_taken,
        note=req.note,
        operator=req.operator or getattr(request.state, "user_id", "unknown"),
    )
    if result is None:
        return error(code_key="NOT_FOUND", message=f"物料 {req.material_id} 不存在于引擎库")
    result["tenant_id"] = tenant_id
    # 审计留痕
    _audit_store.append(make_feedback_audit(
        operator=getattr(request.state, "user_id", "unknown"),
        tenant_id=tenant_id,
        material_id=req.material_id,
        state_before=state_before,
        state_after=result["state"],
        decision=req.decision,
        action_taken=req.action_taken,
        note=req.note,
    ))
    return success(data=result)


@router.get("/compliance/dashboard")
async def compliance_dashboard(
    store_id: Optional[str] = None,
    port: Optional[str] = None,
    request: Request = None,
    user: dict = Depends(get_current_admin),
):
    """四态看板：按门店 institution_id 行级隔离；附 tenant 视角标注。"""
    tenant_id = getattr(request.state, "tenant_id", None) if request else None
    result = await compliance_engine.dashboard(institution_id=store_id, port=port)
    result["tenant_id"] = tenant_id
    return success(data=result)


@router.get("/compliance/audit")
async def compliance_audit(
    action: Optional[str] = None,
    material_id: Optional[str] = None,
    operator: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    request: Request = None,
    user: dict = Depends(get_current_admin),
):
    """审计日志查询（仅管理员）：合规操作留痕，支持按操作类型/物料/操作人过滤。"""
    records = _audit_store.query(
        action=action,
        material_id=material_id,
        operator=operator,
        limit=limit,
        offset=offset,
    )
    return success(data={
        "total": _audit_store.count(),
        "returned": len(records),
        "records": records,
    })
