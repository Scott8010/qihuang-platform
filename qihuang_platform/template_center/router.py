"""多租户能力中心 — 模板中心路由（二期）

前缀 /admin/v1/template-center，提供平台↔机构模板全生命周期：
  - 模板 CRUD（自建编辑）
  - 模板克隆（平台→机构 / 机构→机构，归属关系落 template_ownership）
  - 问卷→模板草稿（门店问卷沉淀为能力中心模板）
  - 机构自建模板同步提交平台审核（template_review_submission）
  - 平台审核：采纳 / 强下架（REJECTED = 强制从共享池下架）
  - 跨租户双向同步：平台→机构下发(push) / 机构→平台贡献(contribute) + 血缘(lineage)
  - 关插件申请(机构/开放通道) + 平台审批(approve/reject)
  - 模板导出/导入 JSON（跨环境迁移/备份）
  - 版本历史查询 / 版本回滚 / 运营统计聚合（Stage C 深度运营）

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
    CrossTenantSyncLog, PluginDisableRequest, Org,
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


# ─────────────────────────── 序列化（⑤ 同步 / ⑤-a 关插件） ───────────────────────────

def _serialize_sync_log(log: CrossTenantSyncLog) -> Dict[str, Any]:
    return {
        "id": log.id,
        "action": log.action,
        "source_template_id": log.source_template_id,
        "target_template_id": log.target_template_id,
        "from_tenant_id": log.from_tenant_id,
        "from_org_id": log.from_org_id,
        "to_tenant_id": log.to_tenant_id,
        "to_org_id": log.to_org_id,
        "created_by": log.created_by,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _serialize_disable_request(d: PluginDisableRequest) -> Dict[str, Any]:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "org_id": d.org_id,
        "plugin_key": d.plugin_key,
        "reason": d.reason,
        "submitter_id": d.submitter_id,
        "status": d.status,
        "reviewer_id": d.reviewer_id,
        "review_note": d.review_note,
        "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None,
        "reviewed_at": d.reviewed_at.isoformat() if d.reviewed_at else None,
    }


# ─────────────────────────── ⑤ 核心：跨租户双向同步 ───────────────────────────

class PushTemplateReq(BaseModel):
    target_org_ids: List[str]
    target_tenant_id: Optional[str] = None
    visibility: str = "private"


@router.post("/templates/{template_id}/push")
async def push_template_to_orgs(
    template_id: str,
    req: PushTemplateReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台→机构批量下发：把官方模板克隆到 N 家机构。

    - 每家机构生成 source='clone' 副本，parent_template_id 指向源（血缘）；
    - 每次同步写 CrossTenantSyncLog 审计（支撑 Stage C 运营）。
    - 机构不存在则跳过，不中断批量。
    """
    src = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not src:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "源模板不存在"))
    user_id = getattr(request.state, "user_id", None)
    created_ids = []
    logs = []
    for org_id in req.target_org_ids:
        org = db.query(Org).filter(Org.id == org_id).first()
        if not org:
            continue
        tenant_id = req.target_tenant_id or org.tenant_id
        new_t = DbTemplate(
            tenant_id=tenant_id,
            name=src.name + "（平台下发）",
            kind=src.kind,
            content_json=src.content_json,
            current_version="v1",
            parent_template_id=src.id,
            created_by=user_id,
        )
        db.add(new_t)
        db.flush()
        db.add(TemplateOwnership(
            template_id=new_t.id,
            owner_tenant_id=tenant_id,
            owner_org_id=org_id,
            visibility=req.visibility,
            source="clone",
        ))
        logs.append(CrossTenantSyncLog(
            action="push",
            source_template_id=src.id,
            target_template_id=new_t.id,
            from_tenant_id=src.tenant_id,
            to_tenant_id=tenant_id,
            to_org_id=org_id,
            created_by=user_id,
        ))
        created_ids.append(new_t.id)
    db.add_all(logs)
    db.commit()
    return success(data={
        "pushed_count": len(created_ids),
        "target_template_ids": created_ids,
    }, message=f"已下发至 {len(created_ids)} 家机构")


@router.get("/templates/{template_id}/lineage")
async def get_template_lineage(
    template_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """血缘视图：源模板 + 其全部直接克隆副本（parent_template_id == 源）。"""
    src = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not src:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    children = db.query(DbTemplate).filter(
        DbTemplate.parent_template_id == template_id).all()
    return success(data={
        "source": _serialize_template(src),
        "clones": [_serialize_template(c) for c in children],
        "clone_count": len(children),
    })


class ContributeTemplateReq(BaseModel):
    visibility: str = "public"        # 贡献到平台共享池默认公开
    submit_for_review: bool = False   # 是否同步提交平台审核（进入策展池）


@router.post("/templates/{template_id}/contribute")
async def contribute_template_to_platform(
    template_id: str,
    req: ContributeTemplateReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """机构→平台克隆记血缘：把机构模板贡献到平台共享池（source='clone' + parent_template_id）。"""
    src = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not src:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "源模板不存在"))
    user_id = getattr(request.state, "user_id", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    org_id = getattr(request.state, "org_id", None)
    new_t = DbTemplate(
        tenant_id=None,  # 平台池：无租户归属
        name=src.name + "（机构贡献）",
        kind=src.kind,
        content_json=src.content_json,
        current_version="v1",
        parent_template_id=src.id,
        created_by=user_id,
    )
    db.add(new_t)
    db.flush()
    db.add(TemplateOwnership(
        template_id=new_t.id,
        owner_tenant_id=None,
        owner_org_id=None,
        visibility=req.visibility,
        source="clone",
    ))
    db.add(CrossTenantSyncLog(
        action="contribute",
        source_template_id=src.id,
        target_template_id=new_t.id,
        from_tenant_id=tenant_id,
        from_org_id=org_id,
        to_tenant_id=None,
        created_by=user_id,
    ))
    if req.submit_for_review:
        db.add(TemplateReviewSubmission(
            template_id=new_t.id,
            submitter_tenant_id=tenant_id,
            submitter_org_id=org_id,
            status="PENDING",
        ))
    db.commit()
    db.refresh(new_t)
    own = _get_ownership(db, new_t.id, None)
    data = _serialize_template(new_t, own)
    if req.submit_for_review:
        data["review_status"] = "PENDING"
    return success(data=data, message="已贡献至平台共享池")


# ─────────────────────────── ⑤-a 关插件申请（决策①=B：机构长可申请） ───────────────────────────

class PluginDisableReq(BaseModel):
    reason: Optional[str] = None


@router.post("/orgs/{org_id}/plugins/{plugin_key}/disable-request")
async def create_plugin_disable_request(
    org_id: str,
    plugin_key: str,
    req: PluginDisableReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """机构长申请关闭某插件（平台审核后才生效）。幂等：已有 PENDING 不重复建。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    existing = db.query(PluginDisableRequest).filter(
        PluginDisableRequest.org_id == org_id,
        PluginDisableRequest.plugin_key == plugin_key,
        PluginDisableRequest.status == "PENDING",
    ).first()
    if existing:
        return success(data=_serialize_disable_request(existing), message="已有待审申请")
    d = PluginDisableRequest(
        tenant_id=tenant_id,
        org_id=org_id,
        plugin_key=plugin_key,
        reason=req.reason,
        status="PENDING",
        submitter_id=user_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return success(data=_serialize_disable_request(d), message="关插件申请已提交，等待平台审核")


@router.get("/plugin-disable-requests")
async def list_plugin_disable_requests(
    request: Request,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台查看关插件申请列表（按状态过滤）。"""
    q = db.query(PluginDisableRequest)
    if status:
        q = q.filter(PluginDisableRequest.status == status)
    rows = q.order_by(PluginDisableRequest.submitted_at.desc()).all()
    return success(data={"items": [_serialize_disable_request(s) for s in rows], "total": len(rows)})


@router.post("/plugin-disable-requests/{request_id}/approve")
async def approve_plugin_disable_request(
    request_id: str,
    req: ReviewDecisionReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台批准关插件：status=APPROVED（生效依据；HB/8602 读取已批准项执行下架）。"""
    d = db.query(PluginDisableRequest).filter(PluginDisableRequest.id == request_id).first()
    if not d:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "申请不存在"))
    d.status = "APPROVED"
    d.reviewer_id = getattr(request.state, "user_id", None)
    d.review_note = req.review_note
    d.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return success(data=_serialize_disable_request(d))


@router.post("/plugin-disable-requests/{request_id}/reject")
async def reject_plugin_disable_request(
    request_id: str,
    req: ReviewDecisionReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """平台驳回关插件：status=REJECTED。"""
    d = db.query(PluginDisableRequest).filter(PluginDisableRequest.id == request_id).first()
    if not d:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "申请不存在"))
    d.status = "REJECTED"
    d.reviewer_id = getattr(request.state, "user_id", None)
    d.review_note = req.review_note
    d.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return success(data=_serialize_disable_request(d))


# ─────────────────────────── ⑥ Stage C：版本回滚 + 导出/导入 JSON ───────────────────────────

class TemplateImportReq(BaseModel):
    export: Dict[str, Any]                         # 由 /export 产出的 JSON 载荷
    target_org_id: Optional[str] = None
    target_tenant_id: Optional[str] = None
    visibility: str = "private"


class TemplateRollbackReq(BaseModel):
    version_tag: str                               # 要回滚到的目标版本号，如 v1 / v2


def _serialize_version(v: TemplateVersion) -> Dict[str, Any]:
    return {
        "version_tag": v.version_tag,
        "snapshot_json": v.snapshot_json,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("/templates/{template_id}/export")
async def export_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """导出模板为 JSON（含归属 + 全量版本快照），供跨环境迁移/备份（Stage C 深度运营）。"""
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    own = _get_ownership(db, template_id, None)
    versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template_id).order_by(
        TemplateVersion.created_at.asc()).all()
    payload = {
        "kind": "qihuang.template_center.template",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "template": {
            "name": t.name,
            "kind": t.kind,
            "content_json": t.content_json,
            "current_version": t.current_version,
        },
        "ownership": {
            "visibility": own.visibility if own else "private",
            "source": own.source if own else "self",
        },
        "versions": [_serialize_version(v) for v in versions],
    }
    return success(data=payload)


@router.post("/templates/import")
async def import_template(
    req: TemplateImportReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """导入模板 JSON（由 /export 产出）：重建为新模板（新 id），克隆版本快照。

    - 带 target_org_id → source='self'（机构私有）；否则 source='platform'。
    - 血缘不跨环境保留（新模板 parent_template_id 为空）。
    """
    exp = req.export or {}
    tpl = exp.get("template") or {}
    name = tpl.get("name", "导入模板")
    kind = tpl.get("kind", "herb")
    content_json = tpl.get("content_json", {})
    if not content_json and not tpl:
        raise HTTPException(status_code=400, detail=error("BAD_REQUEST", "导出载荷为空"))
    tenant_id = req.target_tenant_id or getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    org_id = req.target_org_id
    new_t = DbTemplate(
        tenant_id=tenant_id,
        name=name + "（导入）",
        kind=kind,
        content_json=content_json,
        current_version=tpl.get("current_version", "v1"),
        created_by=user_id,
    )
    db.add(new_t)
    db.flush()
    db.add(TemplateOwnership(
        template_id=new_t.id,
        owner_tenant_id=tenant_id,
        owner_org_id=org_id,
        visibility=req.visibility,
        source="self" if org_id else "platform",
    ))
    for v in exp.get("versions", []):
        db.add(TemplateVersion(
            template_id=new_t.id,
            version_tag=v.get("version_tag", "v1"),
            snapshot_json=v.get("snapshot_json", {}),
            created_by=user_id,
        ))
    db.commit()
    db.refresh(new_t)
    own = _get_ownership(db, new_t.id, org_id)
    data = _serialize_template(new_t, own)
    versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == new_t.id).all()
    data["versions"] = [_serialize_version(v) for v in versions]
    return success(data=data, message="模板已导入")


# ─────────────────────────── 版本历史 & 回滚（Stage C 深度运营） ───────────────────────────

@router.get("/templates/{template_id}/versions")
async def list_template_versions(
    template_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """模板版本快照列表（按时间倒序），供前端做版本历史展示与回滚。"""
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    versions = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template_id).order_by(
        TemplateVersion.created_at.desc()).all()
    return success(data={
        "items": [_serialize_version(v) for v in versions],
        "current_version": t.current_version,
        "total": len(versions),
    })


@router.post("/templates/{template_id}/rollback")
async def rollback_template(
    template_id: str,
    req: TemplateRollbackReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """版本回滚：把模板内容恢复到指定版本的快照，并把 current_version 指向该版本。

    回滚前先把「当前内容」快照为一次新版本（version_tag=当前版本号），保证可再撤销。
    已是目标版本则直接返回，避免产生冗余快照。
    """
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    if req.version_tag == t.current_version:
        own = _get_ownership(db, template_id, None)
        return success(data=_serialize_template(t, own), message="已是该版本，无需回滚")
    ver = db.query(TemplateVersion).filter(
        TemplateVersion.template_id == template_id,
        TemplateVersion.version_tag == req.version_tag,
    ).first()
    if not ver:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", f"版本 {req.version_tag} 不存在"))
    user_id = getattr(request.state, "user_id", None)
    # 先快照当前状态（保留可撤销）
    db.add(TemplateVersion(
        template_id=t.id,
        version_tag=t.current_version,
        snapshot_json=t.content_json,
        created_by=user_id,
    ))
    t.content_json = ver.snapshot_json
    t.current_version = req.version_tag
    db.commit()
    db.refresh(t)
    own = _get_ownership(db, template_id, None)
    return success(data=_serialize_template(t, own), message=f"已回滚至 {req.version_tag}")


# ─────────────────────────── 运营统计（Stage C 深度运营） ───────────────────────────

@router.get("/stats")
async def template_center_stats(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """能力中心运营统计：模板/版本/克隆/审核/跨租户同步/关插件 聚合一览。"""
    total_templates = db.query(func.count(DbTemplate.id)).scalar() or 0
    by_kind_rows = db.query(DbTemplate.kind, func.count(DbTemplate.id)).group_by(
        DbTemplate.kind).all()
    templates_by_kind = {k: c for k, c in by_kind_rows}
    total_versions = db.query(func.count(TemplateVersion.id)).scalar() or 0
    total_clones = db.query(func.count(TemplateOwnership.id)).filter(
        TemplateOwnership.source == "clone").scalar() or 0
    review_rows = db.query(
        TemplateReviewSubmission.status, func.count(TemplateReviewSubmission.id)
    ).group_by(TemplateReviewSubmission.status).all()
    reviews = {s: c for s, c in review_rows}
    sync_rows = db.query(
        CrossTenantSyncLog.action, func.count(CrossTenantSyncLog.id)
    ).group_by(CrossTenantSyncLog.action).all()
    sync = {a: c for a, c in sync_rows}
    disable_rows = db.query(
        PluginDisableRequest.status, func.count(PluginDisableRequest.id)
    ).group_by(PluginDisableRequest.status).all()
    disable = {s: c for s, c in disable_rows}
    return success(data={
        "totals": {"templates": total_templates, "versions": total_versions, "clones": total_clones},
        "templates_by_kind": templates_by_kind,
        "reviews": reviews,
        "sync": sync,
        "disable_requests": disable,
    })
