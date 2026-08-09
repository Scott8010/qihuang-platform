"""活态化聚合层 — 把反馈事件聚合成 confidence 增量并回写 8601 /kg/api

算法权重来自 P1 设计文档第五节（经验初值，后续可调）：
  delta = adopt*0.001 + like*0.0005 + expert_adopt*0.01
        - dislike*0.005 - expert_reject*0.02
  new_c = clamp(old + delta, 0.05, 0.99)   # 保底 0.05，避免彻底抹除
"""
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import func
from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.kg_write_client import kg_client

# 反馈类型 → 置信度权重
_WEIGHTS = {
    "adopt": 0.001,
    "like": 0.0005,
    "expert_adopt": 0.01,
    "dislike": -0.005,
    "expert_reject": -0.02,
    # 活态化 B · 回路三（业务实证加权）业务使用信号基础正加权（小值，配合 business_weight 放大）
    "business_use": 0.0003,
}
_BASELINE = 0.8          # 8601 节点无 confidence 属性时的兜底基线
_MIN, _MAX = 0.05, 0.99  # 保底下限（P1 设计）

# 活态化 B · 回路三（业务实证加权）增益系数 —— 可由环境变量 LIVING_BUSINESS_GAIN 激活。
# 默认 0.0：仅 business_use 基础正加权生效，不按业务权重放大（仿真期安全）。
# 真实业务实证数据回灌（source='business' 且 business_weight>0）后，设为 >0（如 0.5）即激活放大：
#   delta *= (1 + LIVING_BUSINESS_GAIN * business_weight)
_BUSINESS_GAIN = float(os.getenv("LIVING_BUSINESS_GAIN", "0.0"))


def _business_multiplier(f: KgFeedback) -> float:
    """活态化 B 回路三（业务实证加权）预留乘数。

    当前 business_weight 恒为 0.0 → 返回 1.0（不改变 delta）。
    激活后改为：1.0 + _BUSINESS_GAIN * f.business_weight。
    """
    if f.source == "business" and f.business_weight:
        return 1.0 + _BUSINESS_GAIN * float(f.business_weight)
    return 1.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _parse_value(raw: Optional[str]):
    """new_value 以 JSON 字符串存库，处理时还原为原始类型。"""
    if raw is None:
        return None
    import json
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


async def aggregate_feedback(db, client=None, kg_id: Optional[str] = None) -> Dict[str, Any]:
    """聚合未处理反馈 → 计算新 confidence → 回写 8601。

    kg_id 非空时仅聚合该节点的待处理反馈（审核台「按节点采纳」用）。
    返回聚合摘要；client 可注入（测试用）。
    """
    client = client or kg_client
    # ── 活态化 A · 杠杆①投票加权：拉取模型互考能力矩阵作回写可信度上下文 ──
    quiz_ctx: Dict[str, Any] = {}
    if hasattr(client, "get_quiz_summary"):
        try:
            quiz_ctx = await client.get_quiz_summary() or {}
        except Exception:
            quiz_ctx = {}
    caps = quiz_ctx.get("capabilities") or []
    model_trust = (sum((c.get("accuracy") or 0) for c in caps) / len(caps)) if caps else 0.8
    blind_set = {b.get("kg_id") for b in (quiz_ctx.get("blind_spots") or [])}
    q = db.query(KgFeedback).filter(KgFeedback.aggregated_at.is_(None))
    if kg_id:
        q = q.filter(KgFeedback.kg_id == kg_id)
    pending = q.all()

    groups: Dict[tuple, dict] = {}
    for f in pending:
        # 待补全节点（pending: 前缀）暂不参与 confidence 聚合，避免向 8601 写无效 kg_id
        if f.kg_id.startswith("pending:"):
            continue
        key = (f.kg_id, f.target or "node")
        g = groups.get(key)
        if g is None:
            g = {t: 0 for t in _WEIGHTS}
            g["rows"] = []
            groups[key] = g
        g["rows"].append(f)
        if f.feedback_type in _WEIGHTS:
            g[f.feedback_type] += 1

    items, processed = [], []
    for (kg_id, target), g in groups.items():
        delta = sum(_WEIGHTS[t] * g.get(t, 0) for t in _WEIGHTS)
        # 活态化 A · 杠杆①投票加权：模型互考能力作回写可信度上下文
        if kg_id in blind_set:
            delta *= 0.5  # 模型常答错该节点 → 用户反馈更谨慎
        else:
            delta *= (0.8 + 0.2 * model_trust)  # 模型整体越强，回写越自信
        # 活态化 B · 回路三（业务实证加权）架构预留：业务反馈权重乘数（当前恒为 1.0，无副作用）
        biz_mult = max((_business_multiplier(r) for r in g["rows"]), default=1.0)
        delta *= biz_mult
        if abs(delta) < 1e-12:
            # 无 confidence 信号（如仅纠偏/缺口）→ 标记避免重复扫描，跳过写
            for r in g["rows"]:
                r.aggregated_at = datetime.now(timezone.utc)
            processed.extend(g["rows"])
            continue
        cur = await client.get_confidence(kg_id, target)
        base = cur if isinstance(cur, (int, float)) else _BASELINE
        new_c = _clamp(base + delta, _MIN, _MAX)
        items.append({"kg_id": kg_id, "target": target, "confidence_abs": round(new_c, 4)})
        for r in g["rows"]:
            r.aggregated_at = datetime.now(timezone.utc)
        processed.extend(g["rows"])

    batch_result: Dict[str, Any] = {}
    if items:
        batch_result = await client.batch_update_confidence(items)

    db.commit()
    return {
        "kg_ids_processed": len(groups),
        "items_written": len(items),
        "feedback_rows_processed": len(processed),
        "batch_result": batch_result,
    }


async def process_corrections(db, client=None) -> Dict[str, Any]:
    """专家纠偏类反馈 → 调 8601 /kg/api/correction。"""
    client = client or kg_client
    pending = db.query(KgFeedback).filter(
        KgFeedback.feedback_type == "expert_correction",
        KgFeedback.processed_at.is_(None),
    ).all()
    details = []
    for f in pending:
        if f.kg_id.startswith("pending:"):
            # 待补全节点暂无法回写图谱，仅作标记
            details.append({"kg_id": f.kg_id, "result": "skipped_pending"})
            f.processed_at = datetime.now(timezone.utc)
            continue
        res = await client.apply_correction(
            kg_id=f.kg_id, field=f.field,
            new_value=_parse_value(f.new_value),
            expert_id=f.expert_id or "platform",
            reason=f.reason or f.comment or "P2自动纠偏",
        )
        details.append({"kg_id": f.kg_id, "result": res})
        f.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"corrections_processed": len(pending), "details": details}


async def process_gaps(db, client=None) -> Dict[str, Any]:
    """缺口类反馈 → 调 8601 /kg/api/gap。"""
    client = client or kg_client
    pending = db.query(KgFeedback).filter(
        KgFeedback.feedback_type == "gap",
        KgFeedback.processed_at.is_(None),
    ).all()
    details = []
    for f in pending:
        if f.kg_id.startswith("pending:"):
            details.append({"kg_id_a": f.kg_id, "result": "skipped_pending"})
            f.processed_at = datetime.now(timezone.utc)
            continue
        res = await client.mark_gap(
            kg_id_a=f.kg_id, kg_id_b=f.kg_id_b,
            conflict_type=f.conflict_type or "user_reported",
            evidence=f.evidence or f.comment or "",
        )
        details.append({"kg_id_a": f.kg_id, "result": res})
        f.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"gaps_processed": len(pending), "details": details}
