"""多租户能力中心 — 模板中心路由（二期）

前缀 /admin/v1/template-center，提供平台↔机构模板全生命周期：
  - 模板 CRUD（自建编辑）
  - 模板克隆（平台→机构 / 机构→机构，归属关系落 template_ownership）
  - 问卷→模板草稿（门店问卷沉淀为能力中心模板）
  - 机构自建模板同步提交平台审核（template_review_submission）
  - 平台审核：采纳 / 强下架（REJECTED = 强制从共享池下架）

鉴权约定：
  - 读/机构自建：get_current_user（机构用户即可）
  - 平台审核动作（approve/reject）：get_current_admin（平台管理员）
租户隔离靠 request.state.tenant_id / org_id 注入。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Any, List, Dict
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.db.config import get_db
from qihuang_platform.db.models import (
    DbTemplate, TemplateOwnership, TemplateReviewSubmission,
    TemplateVersion, StoreQuestionnaire,
)

router = APIRouter(prefix="/admin/v1/template-center", tags=["多租户能力中心-模板"])
# 包导出别名（main.py 以 template_center_router 引用）
template_center_router = router


# ─────────────────────────── Pydantic 请求体 ───────────────────────────

class TemplateCreateReq(BaseModel):
    name: str
    kind: str = "herb"                 # herb/formula/syndrome/...
    content_json: Dict[str, Any] = Field(default_factory=dict)
    org_id: Optional[str] = None       # 机构自建时填；平台级留空
    visibility: str = "private"        # platform / public / private


class TemplateEditReq(BaseModel):
    name: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    visibility: Optional[str] = None


class TemplateCloneReq(BaseModel):
    target_org_id: str
    target_tenant_id: Optional[str] = None
    visibility: str = "private"


class QuestionnaireCreateReq(BaseModel):
    title: str
    description: Optional[str] = None
    schema: Dict[str, Any] = Field(default_factory=dict)  # 问卷题目结构
    org_id: Optional[str] = None


class ReviewDecisionReq(BaseModel):
    review_note: Optional[str] = None


# ─────────────────────────── 序列化 ───────────────────────────

def _serialize_template(t: DbTemplate, ownership: Optional[TemplateOwnership] = None) -> Dict[str, Any]:
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "name": t.name,
        "kind": t.kind,
        "content_json": t.content_json,
        "current_version": t.current_version,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "ownership": {
            "visibility": ownership.visibility if ownership else None,
            "source": ownership.source if ownership else None,
            "owner_org_id": ownership.owner_org_id if ownership else None,
        } if ownership else None,
    }


def _serialize_submission(s: TemplateReviewSubmission) -> Dict[str, Any]:
    return {
        "id": s.id,
        "template_id": s.template_id,
        "submitter_tenant_id": s.submitter_tenant_id,
        "submitter_org_id": s.submitter_org_id,
        "status": s.status,
        "reviewer_id": s.reviewer_id,
        "review_note": s.review_note,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
    }


def _bump_version(tag: str) -> str:
    """v1 → v2；无法解析则 v1。"""
    if tag and tag.startswith("v") and tag[1:].isdigit():
        return "v" + str(int(tag[1:]) + 1)
    return "v1"


def _get_ownership(db: Session, template_id: str, org_id: Optional[str]) -> Optional[TemplateOwnership]:
    q = db.query(TemplateOwnership).filter(TemplateOwnership.template_id == template_id)
    if org_id:
        q = q.filter(TemplateOwnership.owner_org_id == org_id)
    return q.first()


# ─────────────────────────── 模板 CRUD ───────────────────────────

@router.post("/templates")
async def create_template(
    req: TemplateCreateReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """创建模板（平台或机构自建）。自动建立归属关系（template_ownership）。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    org_id = req.org_id or getattr(request.state, "org_id", None)
    t = DbTemplate(
        tenant_id=tenant_id,
        name=req.name,
        kind=req.kind,
        content_json=req.content_json,
        current_version="v1",
        created_by=user_id,
    )
    db.add(t)
    db.flush()  # 取 t.id
    owner = TemplateOwnership(
        template_id=t.id,
        owner_tenant_id=tenant_id,
        owner_org_id=org_id,
        visibility=req.visibility,
        source="self" if org_id else "platform",
    )
    db.add(owner)
    db.commit()
    db.refresh(t)
    return success(data=_serialize_template(t, owner))


@router.get("/templates")
async def list_templates(
    request: Request,
    kind: Optional[str] = None,
    org_id: Optional[str] = None,
    visibility: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """模板列表（按类型/归属机构/可见性过滤）。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    q = db.query(DbTemplate, TemplateOwnership).outerjoin(
        TemplateOwnership, TemplateOwnership.template_id == DbTemplate.id
    )
    q = q.filter(or_(DbTemplate.tenant_id == tenant_id, DbTemplate.tenant_id.is_(None)))
    if kind:
        q = q.filter(DbTemplate.kind == kind)
    if org_id:
        q = q.filter(TemplateOwnership.owner_org_id == org_id)
    if visibility:
        q = q.filter(TemplateOwnership.visibility == visibility)
    rows = q.order_by(DbTemplate.created_at.desc()).all()
    items = [_serialize_template(t, own) for t, own in rows]
    return success(data={"items": items, "total": len(items)})


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    own = _get_ownership(db, template_id, None)
    return success(data=_serialize_template(t, own))


@router.put("/templates/{template_id}")
async def edit_template(
    template_id: str,
    req: TemplateEditReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """编辑模板：先把当前内容快照成 TemplateVersion，再更新主记录（current_version 自增）。"""
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    user_id = getattr(request.state, "user_id", None)
    # 快照当前版本
    db.add(TemplateVersion(
        template_id=t.id,
        version_tag=t.current_version,
        snapshot_json=t.content_json,
        created_by=user_id,
    ))
    if req.name is not None:
        t.name = req.name
    if req.content_json is not None:
        t.content_json = req.content_json
    new_tag = _bump_version(t.current_version)
    t.current_version = new_tag
    if req.visibility is not None:
        own = _get_ownership(db, template_id, getattr(request.state, "org_id", None))
        if own:
            own.visibility = req.visibility
    db.commit()
    db.refresh(t)
    own = _get_ownership(db, template_id, None)
    return success(data=_serialize_template(t, own))


@router.post("/templates/{template_id}/clone")
async def clone_template(
    template_id: str,
    req: TemplateCloneReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """克隆模板到目标机构（归属关系 source='clone'）。返回新模板。"""
    src = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not src:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "源模板不存在"))
    tenant_id = req.target_tenant_id or getattr(request.state, "tenant_id", None)
    new_t = DbTemplate(
        tenant_id=tenant_id,
        name=src.name + "（副本）",
        kind=src.kind,
        content_json=src.content_json,
        current_version="v1",
        created_by=getattr(request.state, "user_id", None),
    )
    db.add(new_t)
    db.flush()
    db.add(TemplateOwnership(
        template_id=new_t.id,
        owner_tenant_id=tenant_id,
        owner_org_id=req.target_org_id,
        visibility=req.visibility,
        source="clone",
    ))
    db.commit()
    db.refresh(new_t)
    own = _get_ownership(db, new_t.id, req.target_org_id)
    return success(data=_serialize_template(new_t, own))


# ─────────────────────────── 提交平台审核 ───────────────────────────

@router.post("/templates/{template_id}/submit")
async def submit_template(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """机构自建模板同步提交平台审核（生成 PENDING 审核单）。"""
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    tenant_id = getattr(request.state, "tenant_id", None)
    org_id = getattr(request.state, "org_id", None)
    # 幂等：已有 PENDING 则不再重复
    existing = db.query(TemplateReviewSubmission).filter(
        TemplateReviewSubmission.template_id == template_id,
        TemplateReviewSubmission.status == "PENDING",
    ).first()
    if existing:
        return success(data=_serialize_submission(existing), message="已有待审单")
    sub = TemplateReviewSubmission(
        template_id=template_id,
        submitter_tenant_id=tenant_id,
        submitter_org_id=org_id,
        status="PENDING",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return success(data=_serialize_submission(sub))


@router.get("/review/submissions")
async def list_submissions(
    request: Request,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """审核单列表（按状态过滤）。"""
    q = db.query(TemplateReviewSubmission)
    if status:
        q = q.filter(TemplateReviewSubmission.status == status)
    rows = q.order_by(TemplateReviewSubmission.submitted_at.desc()).all()
    return success(data={"items": [_serialize_submission(s) for s in rows], "total": len(rows)})


@router.post("/review/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: str,
    req: ReviewDecisionReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台采纳：审核单置 APPROVED，并将归属可见性提升为 public（进入共享池）。"""
    sub = db.query(TemplateReviewSubmission).filter(
        TemplateReviewSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "审核单不存在"))
    sub.status = "APPROVED"
    sub.reviewer_id = getattr(request.state, "user_id", None)
    sub.review_note = req.review_note
    sub.reviewed_at = datetime.now(timezone.utc)
    own = _get_ownership(db, sub.template_id, sub.submitter_org_id)
    if own:
        own.visibility = "public"
    db.commit()
    return success(data=_serialize_submission(sub))


@router.post("/review/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: str,
    req: ReviewDecisionReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台强下架：审核单置 REJECTED，并将归属可见性收回为 private（强制移出共享池）。"""
    sub = db.query(TemplateReviewSubmission).filter(
        TemplateReviewSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "审核单不存在"))
    sub.status = "REJECTED"
    sub.reviewer_id = getattr(request.state, "user_id", None)
    sub.review_note = req.review_note
    sub.reviewed_at = datetime.now(timezone.utc)
    own = _get_ownership(db, sub.template_id, sub.submitter_org_id)
    if own:
        own.visibility = "private"
    db.commit()
    return success(data=_serialize_submission(sub))


# ─────────────────────────── 门店问卷 → 模板草稿 ───────────────────────────

@router.post("/questionnaires")
async def create_questionnaire(
    req: QuestionnaireCreateReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """创建门店问卷模板（采集用结构化问卷）。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    org_id = req.org_id or getattr(request.state, "org_id", None)
    q = StoreQuestionnaire(
        tenant_id=tenant_id,
        org_id=org_id,
        title=req.title,
        description=req.description,
        schema_json=req.schema,
        created_by=getattr(request.state, "user_id", None),
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return success(data={
        "id": q.id, "title": q.title, "schema_json": q.schema_json,
        "org_id": q.org_id, "status": q.status,
    })


@router.get("/questionnaires")
async def list_questionnaires(
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    q = db.query(StoreQuestionnaire).filter(StoreQuestionnaire.tenant_id == tenant_id)
    rows = q.order_by(StoreQuestionnaire.created_at.desc()).all()
    items = [{
        "id": r.id, "title": r.title, "schema_json": r.schema_json,
        "org_id": r.org_id, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return success(data={"items": items, "total": len(items)})


@router.post("/questionnaires/{questionnaire_id}/to-draft")
async def questionnaire_to_draft(
    questionnaire_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """问卷→模板草稿：把门店问卷结构沉淀为能力中心模板（kind 由 schema 推导，缺省 herb）。"""
    q = db.query(StoreQuestionnaire).filter(StoreQuestionnaire.id == questionnaire_id).first()
    if not q:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "问卷不存在"))
    schema = q.schema_json or {}
    kind = schema.get("kind") or "herb"
    tenant_id = getattr(request.state, "tenant_id", None)
    t = DbTemplate(
        tenant_id=tenant_id,
        name=q.title + "（问卷草稿）",
        kind=kind,
        content_json={"from_questionnaire": q.id, "schema": schema},
        current_version="v1",
        created_by=getattr(request.state, "user_id", None),
    )
    db.add(t)
    db.flush()
    db.add(TemplateOwnership(
        template_id=t.id,
        owner_tenant_id=tenant_id,
        owner_org_id=q.org_id,
        visibility="private",
        source="self",
    ))
    db.commit()
    db.refresh(t)
    own = _get_ownership(db, t.id, q.org_id)
    return success(data=_serialize_template(t, own), message="问卷已沉淀为模板草稿")
