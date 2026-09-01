"""
多租户能力中心 — 开放接口（HMAC 友好）
─────────────────────────────────────────────
前缀 /api/v1/template-center，供外部系统（颐掌柜 HB 等）通过
「API Key + HMAC-SHA256 签名」或「JWT Token」调用。仅暴露：
  - 模板列表 / 详情（只读）
  - 机构自建模板（落库 private）
  - 提交平台审核（生成 PENDING 审核单）
审核动作（approve/reject）仍走 /admin/v1/template-center（仅平台管理员）。

设计要点：
- 鉴权用 get_current_principal（API Key 优先，回退 JWT）；
  API Key 路径只注入 tenant_id，所以 org_id / created_by 由请求体携带。
- 复用 template_center.router 内的私有序列化/查找函数，逻辑零分叉。
- 归属 source：API Key 调用且传 org_id → "self"；不传 → "platform"
  （保留 HB 后续可纯平台官方模板的扩展位）。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, Dict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.db.config import get_db
from qihuang_platform.db.models import (
    DbTemplate,
    TemplateOwnership,
    TemplateReviewSubmission,
    PluginDisableRequest,
)
from qihuang_platform.template_center.router import (
    _serialize_template,
    _serialize_submission,
    _get_ownership,
)

router = APIRouter(prefix="/api/v1/template-center", tags=["能力中心-开放接口"])
# 挂载别名（main.py 引用）
template_center_open_router = router


# ─────────────────────────── Pydantic ───────────────────────────

# HB 调用契约：kind 仅允许这 4 类（默认 herb）
OPEN_TEMPLATE_KINDS = ("herb", "script", "product", "project")

class OpenTemplateCreateReq(BaseModel):
    name: str
    kind: str = "herb"
    content_json: Dict[str, Any] = Field(default_factory=dict)
    org_id: Optional[str] = None       # HB 调用时传=其机构 id；API Key 路径必填
    visibility: str = "private"

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in OPEN_TEMPLATE_KINDS:
            raise ValueError(
                f"kind 必须为 {list(OPEN_TEMPLATE_KINDS)} 之一（默认 herb）"
            )
        return v


# ─────────────────────────── 模板创建（机构自建 / 平台落库） ───────────────────────────

@router.post("/templates")
async def open_create_template(
    req: OpenTemplateCreateReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_principal),
):
    """通过开放通道创建模板。API Key / JWT 均可用。

    - API Key 路径：created_by = "apikey:<key>"，tenant_id 取自 key；
      org_id 必须由请求体携带（HB 机构归属）。
    - JWT 路径：created_by = user_id，org_id 优先取请求体，再回退 request.state。
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    app_key = getattr(request.state, "app_key", None)
    org_id = req.org_id or getattr(request.state, "org_id", None)
    # 🔴 HB 集成致命坑（2026-08-20 反馈）：
    # API Key 路径下 8602 只注入 tenant_id，不注入 org_id/user_id。
    # 若此处不卡死，HB 漏传 org_id 时模板会静默归为「平台官方」而非「HB 机构自建」。
    # 故 API Key 路径强制要求请求体携带 org_id；JWT 路径可回退 request.state.org_id。
    if app_key and not org_id:
        raise HTTPException(
            status_code=400,
            detail=error(
                "ORG_ID_REQUIRED",
                "API Key 路径创建机构模板必须在请求体携带 org_id，"
                "否则模板会被归为平台官方而非 HB 机构自建",
            ),
        )
    if not user_id and app_key:
        user_id = f"apikey:{app_key}"
    t = DbTemplate(
        tenant_id=tenant_id,
        name=req.name,
        kind=req.kind,
        content_json=req.content_json,
        current_version="v1",
        created_by=user_id,
    )
    db.add(t)
    db.flush()
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
    own = _get_ownership(db, t.id, org_id)
    return success(data=_serialize_template(t, own), message="模板已建（开放通道）")


# ─────────────────────────── 只读：列表 / 详情 ───────────────────────────

@router.get("/templates")
async def open_list_templates(
    request: Request,
    kind: Optional[str] = None,
    org_id: Optional[str] = None,
    visibility: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_principal),
):
    """模板列表（按 kind / org_id / visibility 过滤）。"""
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
    return success(
        data={"items": [_serialize_template(t, o) for t, o in rows], "total": len(rows)}
    )


@router.get("/templates/{template_id}")
async def open_get_template(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_principal),
):
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    # 🔒 跨租户隔离（IDOR 修复）：仅本人租户模板或平台公共模板(tenant_id=None)可读；
    # 其余租户私有模板一律按 404 处理，避免泄露他人模板内容与存在性。
    caller_tenant = getattr(request.state, "tenant_id", None)
    if t.tenant_id is not None and t.tenant_id != caller_tenant:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    own = _get_ownership(db, template_id, None)
    return success(data=_serialize_template(t, own))


# ─────────────────────────── 提交平台审核 ───────────────────────────

@router.post("/templates/{template_id}/submit")
async def open_submit_template(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_principal),
):
    """机构自建模板通过开放通道提交平台审核。幂等：已有 PENDING 不重复建。"""
    t = db.query(DbTemplate).filter(DbTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    # 🔒 跨租户隔离（IDOR 修复）：只能提交本人租户模板审核，禁止冒用他人机构身份提交。
    # 平台公共模板(tenant_id=None)不属于任何租户，不允许经开放通道提交。
    caller_tenant = getattr(request.state, "tenant_id", None)
    if t.tenant_id is None or t.tenant_id != caller_tenant:
        raise HTTPException(status_code=404, detail=error("NOT_FOUND", "模板不存在"))
    tenant_id = caller_tenant
    own = _get_ownership(db, template_id, None)
    org_id = own.owner_org_id if own else None
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


# ─────────────────────────── 关插件申请（决策①=B：机构长可申请，开放通道） ───────────────────────────

class OpenPluginDisableReq(BaseModel):
    org_id: str                                  # API Key 路径只注入 tenant_id，org_id 必须请求体携带
    plugin_key: str                             # health-advisor / store-coach / ...
    reason: Optional[str] = None


@router.post("/plugins/disable-request")
async def open_create_plugin_disable_request(
    req: OpenPluginDisableReq,
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_principal),
):
    """机构通过开放通道申请关闭某插件（决策①=B）。幂等：已有 PENDING 不重复建。

    - API Key 路径：tenant_id 取密钥绑定租户，org_id 由请求体携带；
    - JWT 路径：取 request.state.tenant_id / org_id（请求体可覆盖）。
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    app_key = getattr(request.state, "app_key", None)
    if not user_id and app_key:
        user_id = f"apikey:{app_key}"
    existing = db.query(PluginDisableRequest).filter(
        PluginDisableRequest.org_id == req.org_id,
        PluginDisableRequest.plugin_key == req.plugin_key,
        PluginDisableRequest.status == "PENDING",
    ).first()
    if existing:
        return success(data={
            "id": existing.id, "status": existing.status,
        }, message="已有待审申请")
    d = PluginDisableRequest(
        tenant_id=tenant_id,
        org_id=req.org_id,
        plugin_key=req.plugin_key,
        reason=req.reason,
        status="PENDING",
        submitter_id=user_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return success(data={
        "id": d.id, "org_id": d.org_id, "plugin_key": d.plugin_key,
        "status": d.status,
    }, message="关插件申请已提交，等待平台审核")
