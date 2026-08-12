"""活态化 B · 回路三（业务实证加权）+ 审核→图谱回流桥

把真实业务信号（颐掌柜门店合规审核）转化为 KgFeedback(source='business') 行，
与用户/专家反馈同一张表、同一套聚合回写通道，让「审核发现」也参与图谱置信度演化。

设计要点：
  - emit_business_feedback：写一行 business 来源反馈；24h 内同 kg_id+同类型去重，避免刷量。
  - bridge_compliance_scan：门店送审命中中医实体 → business_use 正加权
    （实证该知识被真实业务使用，闭环三·业务实证正向印证）。
  - bridge_compliance_feedback：人工结论 override/escalate（疑错知识被强制拦截/升级）
    → expert_reject 负加权，打通「审核发现的错知识」回流图谱、压低其置信度
    （闭环三·业务实证反向纠偏，补齐 compliance 与 living 两线长期脱节的短板）。

所有实体名→kg_id 经 kg_client.resolve 桥接 8601（与前端反馈入口同一解析链路）。
kg_client 可被 monkeypatch 替换（测试用）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_

from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.kg_write_client import kg_client


def _now() -> datetime:
    return datetime.now(timezone.utc)


def emit_business_feedback(
    db,
    kg_id: str,
    feedback_type: str,
    business_weight: float = 1.0,
    tenant_id: Optional[str] = None,
    store_id: Optional[str] = None,
    comment: Optional[str] = None,
) -> Optional[KgFeedback]:
    """写入一条 business 来源反馈（含 24h 去重）。

    返回新建的 KgFeedback 行；若 24h 内已有同 kg_id+同类型+source='business' 则跳过返回 None。
    该去重防止同一门店对同一知识点反复送审/复核导致刷量式置信度漂移。
    """
    since = _now() - timedelta(hours=24)
    dup = db.query(KgFeedback).filter(
        and_(
            KgFeedback.kg_id == kg_id,
            KgFeedback.feedback_type == feedback_type,
            KgFeedback.source == "business",
            KgFeedback.created_at >= since,
        )
    ).first()
    if dup is not None:
        return None

    note = comment or ""
    if store_id:
        note = f"[store:{store_id}] {note}"
    note = note.strip()

    row = KgFeedback(
        kg_id=kg_id,
        target="node",
        tenant_id=tenant_id,
        source="business",
        business_weight=float(business_weight),
        feedback_type=feedback_type,
        comment=note or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def bridge_compliance_scan(
    db,
    aligned_entities: List[Dict[str, Any]],
    tenant_id: Optional[str] = None,
    store_id: Optional[str] = None,
    business_weight: float = 1.0,
) -> Dict[str, Any]:
    """门店送审命中中医实体 → 落 business_use 正加权（实证该知识被真实业务使用）。

    返回 {emitted, skipped, errors} 统计；解析失败/无匹配不阻断主流程（由调用方兜底）。
    """
    emitted, skipped, errors = 0, 0, 0
    seen: set = set()
    for ent in (aligned_entities or []):
        name = ent.get("entity") if isinstance(ent, dict) else ent
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            res = await kg_client.resolve(name)
        except Exception:
            errors += 1
            continue
        kg_id = _first_kg_id(res)
        if not kg_id:
            errors += 1
            continue
        row = emit_business_feedback(
            db, kg_id, "business_use",
            business_weight=business_weight,
            tenant_id=tenant_id, store_id=store_id,
            comment=f"合规送审命中实体「{name}」",
        )
        if row is None:
            skipped += 1
        else:
            emitted += 1
    return {"emitted": emitted, "skipped": skipped, "errors": errors}


async def bridge_compliance_feedback(
    db,
    aligned_entities: List[Dict[str, Any]],
    decision: str,
    tenant_id: Optional[str] = None,
    store_id: Optional[str] = None,
    business_weight: float = 1.0,
) -> Dict[str, Any]:
    """人工结论回写：override/escalate（疑错知识被强制拦截/升级）→ 落 expert_reject 负加权，
    打通「审核发现的错知识」回流图谱、压低其置信度（闭环三·业务实证反向纠偏）。

    keep/remediated/ignore 不回流（视为正常/已整改，不构成错知识信号）。
    """
    if decision not in ("override", "escalate"):
        return {"emitted": 0, "skipped": 0, "errors": 0, "note": "no_bridge_decision"}
    emitted, skipped, errors = 0, 0, 0
    seen: set = set()
    for ent in (aligned_entities or []):
        name = ent.get("entity") if isinstance(ent, dict) else ent
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            res = await kg_client.resolve(name)
        except Exception:
            errors += 1
            continue
        kg_id = _first_kg_id(res)
        if not kg_id:
            errors += 1
            continue
        row = emit_business_feedback(
            db, kg_id, "expert_reject",
            business_weight=business_weight,
            tenant_id=tenant_id, store_id=store_id,
            comment=f"合规人工结论「{decision}」命中实体「{name}」",
        )
        if row is None:
            skipped += 1
        else:
            emitted += 1
    return {"emitted": emitted, "skipped": skipped, "errors": errors}


def _first_kg_id(res: Any) -> Optional[str]:
    """从 kg_client.resolve 响应中取第一个有效 kg_id；失败/无匹配返回 None。"""
    if not isinstance(res, dict):
        return None
    matches = res.get("matches") or []
    for m in matches:
        kg_id = m.get("kg_id") if isinstance(m, dict) else None
        if kg_id:
            return kg_id
    return None
