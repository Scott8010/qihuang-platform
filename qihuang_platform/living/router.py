"""活态化反馈闭环 — HTTP 路由层

端点（前缀 /api/v1/living）：
  POST /feedback                  提交知识反馈（JWT 登录用户）
  GET  /feedback                 反馈列表（审核台：状态/节点/类型过滤+分页）
  POST /feedback/approve         采纳某节点待处理反馈（聚合回写，管理员）
  POST /feedback/reject          驳回反馈（标记排除，管理员）
  GET  /feedback/stats           反馈统计（按类型/待处理）
  GET  /kg/{kg_id}/confidence    实时读取某知识点当前 confidence（查 8601）
  POST /aggregate                触发一次聚合回写（管理员：confidence+纠偏+缺口）
  POST /aggregate/confidence     仅触发 confidence 聚合回写（管理员）
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Any, List, Dict
import json
from datetime import datetime, timezone

from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.db.config import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func
from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.aggregator import aggregate_feedback, process_corrections, process_gaps
from qihuang_platform.living.kg_write_client import kg_client

router = APIRouter(prefix="/api/v1/living", tags=["活态化-反馈闭环"])

_FEEDBACK_TYPES = {
    "adopt", "like", "dislike",
    "expert_adopt", "expert_reject",
    "expert_correction", "gap",
}


class FeedbackReq(BaseModel):
    kg_id: str
    target: str = "node"                      # node | rel
    feedback_type: str
    comment: Optional[str] = None
    # expert_correction 专用
    field: Optional[str] = None
    new_value: Optional[Any] = None
    expert_id: Optional[str] = None
    reason: Optional[str] = None
    # gap 专用
    kg_id_b: Optional[str] = None
    conflict_type: Optional[str] = None
    evidence: Optional[str] = None
    # 活态化 B 架构预留：反馈来源通道。'user'(默认) | 'business'(真实业务实证回灌，预留)
    source: str = "user"
    # 待补全节点：前端搜索到知识点但尚未完成图谱结构化时，kg_id='pending:{name}'
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """提交知识反馈（采纳/点赞/纠偏/缺口等）。需登录用户（JWT）。"""
    if req.feedback_type not in _FEEDBACK_TYPES:
        raise HTTPException(status_code=400, detail=error(
            "INVALID_PARAM",
            f"feedback_type 必须是 {sorted(_FEEDBACK_TYPES)}",
        ))
    # 活态化 B：仅允许预留的 source 取值（当前业务实证通道 'business' 仅占位，暂未启用）
    if req.source not in ("user", "business"):
        raise HTTPException(status_code=400, detail=error(
            "INVALID_PARAM", "source 必须是 'user' 或 'business'",
        ))
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    # new_value 统一以 JSON 字符串存储
    new_value_str = json.dumps(req.new_value, ensure_ascii=False) if req.new_value is not None else None
    fb = KgFeedback(
        kg_id=req.kg_id, target=req.target,
        tenant_id=tenant_id, user_id=user_id,
        feedback_type=req.feedback_type, comment=req.comment,
        field=req.field, new_value=new_value_str,
        expert_id=req.expert_id, reason=req.reason,
        kg_id_b=req.kg_id_b, conflict_type=req.conflict_type, evidence=req.evidence,
        source=req.source,
        entity_name=req.entity_name,
        entity_type=req.entity_type,
    )
    db.add(fb)
    db.commit()
    return success(data={"feedback_id": fb.id, "kg_id": fb.kg_id, "type": fb.feedback_type})


@router.get("/feedback/stats")
async def feedback_stats(
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """反馈统计：按类型计数 + 待处理数。"""
    rows = db.query(KgFeedback.feedback_type, func.count(KgFeedback.id)).group_by(
        KgFeedback.feedback_type).all()
    by_type = {r[0]: r[1] for r in rows}
    total = db.query(func.count(KgFeedback.id)).scalar() or 0
    pending = db.query(func.count(KgFeedback.id)).filter(
        KgFeedback.aggregated_at.is_(None),
        KgFeedback.processed_at.is_(None),
    ).scalar() or 0
    return success(data={"total": total, "pending": pending, "by_type": by_type})


@router.get("/kg/{kg_id}/confidence")
async def get_kg_confidence(kg_id: str, target: str = "node"):
    """实时读取某知识点当前 confidence（查 8601 /kg/api/node/{kg_id}/confidence）。"""
    c = await kg_client.get_confidence(kg_id, target)
    return success(data={"kg_id": kg_id, "target": target, "confidence": c})


# 反馈入口：前端按名字解析 kg_id 时，type → Neo4j 主标签 的映射
_LABEL_BY_TYPE = {"herb": "Herb", "formula": "Formula", "syndrome": "Syndrome"}


@router.get("/resolve")
async def resolve_entity(
    name: str,
    type: str = "herb",
    _: dict = Depends(get_current_user),
):
    """按名称解析知识节点 kg_id（名字→kg_id 桥）。type: herb|formula|syndrome。供前端反馈入口用。"""
    c = await kg_client.resolve(name)
    if "error" in c:
        return error(code_key="SERVICE_UNAVAILABLE", message="图谱解析服务不可用: " + str(c["error"]))
    matches = c.get("matches", []) or []
    target = _LABEL_BY_TYPE.get(type, "Herb")
    exact = [m for m in matches if target in (m.get("labels") or [])]
    chosen = exact[0] if exact else (matches[0] if matches else None)
    return success(data={
        "name": name,
        "type": type,
        "kg_id": chosen["kg_id"] if chosen else None,
        "labels": chosen.get("labels") if chosen else None,
        "total_matches": len(matches),
        "message": None if chosen else "未找到匹配的知识点",
    })


@router.post("/aggregate")
async def trigger_aggregate(
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """触发一次聚合回写（管理员）。confidence + 纠偏 + 缺口 三类一并处理。"""
    agg = await aggregate_feedback(db)
    corr = await process_corrections(db)
    gaps = await process_gaps(db)
    return success(data={"confidence": agg, "corrections": corr, "gaps": gaps})


@router.post("/aggregate/confidence")
async def trigger_confidence_only(
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """仅触发 confidence 聚合回写（管理员）。"""
    agg = await aggregate_feedback(db)
    return success(data=agg)


# ═══════════════ 审核台端点（列表 / 采纳 / 驳回）══════════════

def _serialize_feedback(f: KgFeedback) -> Dict[str, Any]:
    """序列化为审核台可用结构，并派生 status 字段。

    status 派生规则（无新增 DB 列，复用两个时间戳）：
      aggregated + processed → rejected（已驳回）
      aggregated only        → aggregated（已采纳→置信度回写）
      processed only         → processed（已处理：纠偏/缺口）
      neither                → pending（待处理）
    """
    agg = f.aggregated_at is not None
    proc = f.processed_at is not None
    if agg and proc:
        status = "rejected"
    elif agg:
        status = "aggregated"
    elif proc:
        status = "processed"
    else:
        status = "pending"
    # 待补全节点：kg_id='pending:{name}' 时显示 entity_name/entity_type 更直观
    display_name = f.entity_name or (f.kg_id.split(":", 1)[1] if f.kg_id.startswith("pending:") else None)
    return {
        "id": f.id,
        "kg_id": f.kg_id,
        "target": f.target,
        "entity_name": display_name,
        "entity_type": f.entity_type,
        "pending": f.kg_id.startswith("pending:"),
        "tenant_id": f.tenant_id,
        "user_id": f.user_id,
        "feedback_type": f.feedback_type,
        "comment": f.comment,
        "field": f.field,
        "new_value": f.new_value,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "aggregated_at": f.aggregated_at.isoformat() if f.aggregated_at else None,
        "processed_at": f.processed_at.isoformat() if f.processed_at else None,
        "status": status,
        "source": f.source,                 # 活态化 B 预留：反馈来源通道（user/business）
        "business_weight": f.business_weight,  # 活态化 B 预留：业务实证权重（当前恒为 0.0）
    }


@router.get("/feedback")
async def list_feedback(
    request: Request,
    status: str = "pending",            # pending | aggregated | processed | rejected | all
    kg_id: Optional[str] = None,
    feedback_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """反馈列表（审核台用）。支持按状态/节点/类型过滤 + 分页。"""
    q = db.query(KgFeedback)
    if kg_id:
        q = q.filter(KgFeedback.kg_id == kg_id)
    if feedback_type:
        q = q.filter(KgFeedback.feedback_type == feedback_type)
    if status == "pending":
        q = q.filter(KgFeedback.aggregated_at.is_(None), KgFeedback.processed_at.is_(None))
    elif status == "aggregated":
        q = q.filter(KgFeedback.aggregated_at.isnot(None))
    elif status == "processed":
        q = q.filter(KgFeedback.processed_at.isnot(None))
    elif status == "rejected":
        q = q.filter(KgFeedback.aggregated_at.isnot(None), KgFeedback.processed_at.isnot(None))
    # "all" → 不过滤
    total = q.count()
    rows = q.order_by(KgFeedback.created_at.desc()) \
             .offset((page - 1) * page_size).limit(page_size).all()
    items = [_serialize_feedback(r) for r in rows]
    return success(data={
        "items": items, "total": total,
        "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    })


class ApproveReq(BaseModel):
    kg_id: str
    target: str = "node"


@router.post("/feedback/approve")
async def approve_feedback(
    req: ApproveReq,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """采纳某节点的待处理反馈 → 聚合该节点 confidence 并回写 8601（管理员）。

    待补全节点（kg_id 以 'pending:' 开头）仅作标记，不回写图谱。
    """
    if req.kg_id.startswith("pending:"):
        from sqlalchemy import func as _func
        now = datetime.now(timezone.utc)
        n = db.query(KgFeedback).filter(
            KgFeedback.kg_id == req.kg_id,
            KgFeedback.aggregated_at.is_(None),
            KgFeedback.processed_at.is_(None),
        ).update({"aggregated_at": now, "processed_at": now}, synchronize_session=False)
        db.commit()
        return success(data={"kg_id": req.kg_id, "target": req.target, "marked": n, "note": "待补全节点已标记，未回写图谱"})
    agg = await aggregate_feedback(db, kg_id=req.kg_id)
    new_c = await kg_client.get_confidence(req.kg_id, req.target)
    return success(data={
        "kg_id": req.kg_id,
        "target": req.target,
        "new_confidence": new_c,
        "summary": agg,
    })


class RejectReq(BaseModel):
    kg_id: Optional[str] = None
    feedback_ids: Optional[List[str]] = None


@router.post("/feedback/reject")
async def reject_feedback(
    req: RejectReq,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """驳回反馈：标记排除（不再参与聚合/纠偏/缺口处理）。

    支持按节点(kg_id)或按 id 列表(feedback_ids)批量驳回。
    标记方式：同时置 aggregated_at 与 processed_at，使其从所有处理通道排除。
    """
    q = db.query(KgFeedback)
    if req.feedback_ids:
        q = q.filter(KgFeedback.id.in_(req.feedback_ids))
    elif req.kg_id:
        q = q.filter(KgFeedback.kg_id == req.kg_id)
    else:
        raise HTTPException(status_code=400, detail=error(
            "INVALID_PARAM", "kg_id 与 feedback_ids 至少提供一个"
        ))
    now = datetime.now(timezone.utc)
    pending = q.filter(
        KgFeedback.aggregated_at.is_(None),
        KgFeedback.processed_at.is_(None),
    ).all()
    for r in pending:
        r.aggregated_at = now
        r.processed_at = now
    db.commit()
    return success(data={"rejected": len(pending)})


@router.get("/quiz")
async def quiz_summary(
    _: dict = Depends(get_current_admin),
):
    """读取模型互考能力矩阵 + 知识盲点（控制端展示用，活态化 A）。透传 8601 /kg/api/quiz。"""
    data = await kg_client.get_quiz_summary()
    if "error" in data:
        return error(code_key="SERVICE_UNAVAILABLE", message="图谱服务不可用: " + str(data["error"]))
    return success(data=data)


@router.post("/quiz/run")
async def quiz_run(
    max_quizzes: int = 10,
    _: dict = Depends(get_current_admin),
):
    """触发一轮模型互考（活态化 A）。

    后台让 4 个大模型互考（出题→作答→评分），更新模型能力矩阵与知识盲点。
    透传 8601 /kg/api/quiz/run。注意该过程涉及多次 LLM 调用，耗时数秒到数十秒。
    """
    data = await kg_client.run_quiz(max_quizzes)
    if "error" in data:
        return error(code_key="SERVICE_UNAVAILABLE", message="图谱服务不可用: " + str(data["error"]))
    return success(data=data)
