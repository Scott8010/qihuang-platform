"""
store_coach · 路由（Agent 中台接入点）— 门店话术对练能力（#376 S1）

端点：
  POST /api/v1/agent/store-coach/sessions  创建话术对练会话（AI 扮演顾客）
  POST /api/v1/agent/store-coach/evaluate  提交店员话术 → AI 顾客接话 + 四维评分 + 合规横切
  GET  /api/v1/agent/store-coach/dashboard 本店话术训练学情看板
鉴权：JWT（get_current_principal 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan("store-coach")）
能力引擎：8602 自有 4 引擎 LLM 客户端双角色（engine.customer_reply 扮演顾客 + engine.evaluate 四维评分）
合规护栏（对齐方案七风险表）：话术输出过 compliance 审核，违规自动标红拦截；不夸大疗效/不承诺治愈。
与 edu/coach（中医辨证对练）完全独立，不混表、不混语义（老黄 2026-08-19 拍板拆两个独立能力）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("store_coach.router")

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.gateway.metering import metering_store
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.store_coach.engine import customer_reply, evaluate
from qihuang_platform.agent.store_coach.metering import check_quota, record_call
from qihuang_platform.db.models import StoreCoachSession
from qihuang_platform.db.config import SessionLocal

router = APIRouter()

# 话术场景枚举（对齐 engine._SCENE_PROFILES）
_SCENES = {
    "reception": "进店接待",
    "recommend": "产品推荐",
    "objection": "异议处理",
    "close": "促成下单",
}

# 四维评分权重（对齐 engine._EVALUATE_SYSTEM_PROMPT）
_WEIGHTS = {"completeness": 0.25, "professional": 0.30, "affinity": 0.20, "compliance": 0.25}


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class StoreCoachSessionRequest(BaseModel):
    """创建门店话术对练会话请求"""
    scene: str = Field("reception", description="话术场景: " + "/".join(_SCENES.keys()))
    topic: str = Field(..., description="对练主题，如 '顾客嫌贵怎么接'")
    script_id: Optional[str] = Field(None, description="话术模板ID（DbTemplate kind=script）")
    product_id: Optional[str] = Field(None, description="产品模板ID（DbTemplate kind=product）")
    project_id: Optional[str] = Field(None, description="项目模板ID（DbTemplate kind=project）")
    customer_profile: Optional[str] = Field(None, description="顾客画像（默认内置，如 '50岁阿姨、注重养生'）")


class StoreCoachEvaluateRequest(BaseModel):
    """提交店员话术请求"""
    session_id: str = Field(..., description="话术对练会话ID")
    answer: str = Field(..., description="店员话术内容")


# ═══════════════════════════════════════════════════════════════
# 合规横切（对齐 compliance-guard 护栏）
# ═══════════════════════════════════════════════════════════════

async def _compliance_check(text: str, tenant_id: str) -> Dict[str, Any]:
    """话术输出过 compliance 审核。

    返回 {"ok": bool, "hits": [...]}：
    - state == "已通过" → ok=True；
    - state == "违规拦截" → ok=False（违规标红）；
    - state == "存疑待复核" → ok=False（谨慎拦截，交人工）；
    - 审核不可用时放行（fail-open 兜底 + 告警）。
    """
    try:
        from qihuang_platform.agent.compliance.engine_l2 import compliance_engine
        res = await compliance_engine.analyze(
            text=text,
            material_type="coach_script",
            port="8602",
            institution_id=tenant_id,
            persist=False,
        )
        state = (res or {}).get("state", "")
        hits = (res or {}).get("hits") or []
        if state == "已通过":
            return {"ok": True, "hits": hits}
        if state == "违规拦截":
            return {"ok": False, "hits": hits}
        if state == "存疑待复核":
            return {"ok": False, "hits": hits}
        # 状态未知/异常 → 放行 + 告警
        logger.warning("[store_coach] compliance 返回未知状态 %r，放行", state)
        return {"ok": True, "hits": hits}
    except Exception as e:  # noqa: BLE001
        logger.warning("[store_coach] compliance 审核不可用，放行: %s", e)
        return {"ok": True, "hits": []}


# ═══════════════════════════════════════════════════════════════
# 1. 创建话术对练会话
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/store-coach/sessions",
    summary="创建门店话术对练会话（AI 扮演顾客）",
)
async def create_store_coach_session(
    req: StoreCoachSessionRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("store-coach")),
):
    if req.scene not in _SCENES:
        return error("INVALID_PARAM", f"不支持的 scene: {req.scene}，有效值: {list(_SCENES.keys())}")

    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月话术训练调用配额已用完，请升级套餐或次月恢复。")

    db = SessionLocal()
    try:
        session = StoreCoachSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            scene=req.scene,
            topic=req.topic,
            script_id=req.script_id,
            product_id=req.product_id,
            project_id=req.project_id,
            customer_profile=req.customer_profile,
            messages=[],
            evaluation=None,
            compliance_ok=True,
            compliance_hits=[],
        )
        db.add(session)
        db.commit()

        # 初始化：AI 顾客开场（可选——真实对练由店员先开口；此处生成开场白作为示例引导）
        trace_id = uuid.uuid4().hex
        start = time.monotonic()
        opening, model = await customer_reply(
            scene=req.scene,
            topic=req.topic,
            customer_profile=req.customer_profile or "",
            history=[],
        )
        latency_ms = (time.monotonic() - start) * 1000
        if opening:
            session.messages = [{"role": "assistant", "content": opening}]
            db.commit()
        await record_call(
            tenant_id=tenant_id, user_id=user_id,
            code=0 if opening else -1, latency_ms=latency_ms, trace_id=trace_id,
            action="sessions", scene=req.scene,
        )

        return success(data={
            "session_id": session.id,
            "scene": session.scene,
            "topic": session.topic,
            "customer_profile": session.customer_profile or "（默认内置画像）",
            "opening": opening or "（AI 开场暂不可用，请店员先开口）",
            "model": model,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 2. 提交店员话术 → AI 顾客接话 + 四维评分 + 合规横切
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/store-coach/evaluate",
    summary="提交店员话术（AI 顾客接话 + 四维评分 + 合规横切）",
)
async def store_coach_evaluate(
    req: StoreCoachEvaluateRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("store-coach")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月话术训练调用配额已用完，请升级套餐或次月恢复。")

    trace_id = uuid.uuid4().hex
    start = time.monotonic()

    db = SessionLocal()
    try:
        session = db.query(StoreCoachSession).filter_by(
            id=req.session_id, tenant_id=tenant_id
        ).first()
        if not session:
            return error("NOT_FOUND", f"话术对练会话不存在: {req.session_id}")

        history = session.messages or []
        # 合规横切：店员话术先过审（违规标红，仍继续评分但标记）
        compliance = await _compliance_check(req.answer, tenant_id)

        # AI 顾客接话
        reply, reply_model = await customer_reply(
            scene=session.scene,
            topic=session.topic,
            customer_profile=session.customer_profile or "",
            history=history + [{"role": "user", "content": req.answer}],
        )

        # 四维话术评估
        eval_raw, eval_model = await evaluate(
            scene=session.scene,
            topic=session.topic,
            customer_profile=session.customer_profile or "",
            history=history,
            staff_answer=req.answer,
        )

        # 解析评估 JSON
        parsed: Dict[str, Any] = {}
        if eval_raw:
            text = eval_raw.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"feedback": eval_raw, "evaluation": {}, "score": None}

        evaluation = parsed.get("evaluation") or {}
        score = parsed.get("score")
        if isinstance(score, (int, float)):
            score = round(float(score), 1)
        elif evaluation:
            # 引擎未给总分时按权重折算
            score = round(sum(evaluation.get(k, 0) * w for k, w in _WEIGHTS.items()), 1)
        feedback = parsed.get("feedback") or ""

        # 落库
        history.append({"role": "user", "content": req.answer})
        if reply:
            history.append({"role": "assistant", "content": reply})
        session.messages = history
        session.evaluation = evaluation
        session.score = score
        session.feedback = feedback
        session.compliance_ok = compliance["ok"]
        session.compliance_hits = compliance["hits"]
        db.commit()

        latency_ms = (time.monotonic() - start) * 1000
        await record_call(
            tenant_id=tenant_id, user_id=user_id,
            code=0 if reply else -1, latency_ms=latency_ms, trace_id=trace_id,
            action="evaluate", scene=session.scene, compliance_ok=compliance["ok"],
        )

        return success(data={
            "customer_reply": reply or "（AI 顾客暂不可用）",
            "reply_model": reply_model,
            "evaluation": evaluation,
            "score": score,
            "feedback": feedback,
            "eval_model": eval_model,
            "compliance": {
                "ok": compliance["ok"],
                "hits": compliance["hits"],
            },
        })
    except Exception as e:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        await record_call(
            tenant_id=tenant_id, user_id=user_id,
            code=-1, latency_ms=latency_ms, trace_id=trace_id,
            action="evaluate",
        )
        logger.exception("[store_coach] evaluate 异常: %s", e)
        return error("INTERNAL_ERROR", "话术评估失败，请稍后重试。")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 3. 本店话术训练学情看板
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/store-coach/dashboard",
    summary="本店话术训练学情看板（store-coach）",
)
async def store_coach_dashboard(
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("store-coach")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    db = SessionLocal()
    try:
        sessions = db.query(StoreCoachSession).filter_by(tenant_id=tenant_id).all()
        total = len(sessions)
        scored = [s for s in sessions if s.score is not None]
        avg_score = (sum(s.score for s in scored) / len(scored)) if scored else 0.0
        by_scene: Dict[str, int] = {}
        for s in sessions:
            by_scene[s.scene] = by_scene.get(s.scene, 0) + 1
        compliance_fail = len([s for s in sessions if s.compliance_ok is False])
        recent = [{
            "scene": s.scene,
            "topic": s.topic,
            "score": s.score,
            "compliance_ok": s.compliance_ok,
            "created_at": s.created_at,
        } for s in sessions[:20]]

        return success(data={
            "total_sessions": total,
            "scored_sessions": len(scored),
            "avg_score": round(avg_score, 1),
            "by_scene": by_scene,
            "compliance_fail_count": compliance_fail,
            "recent": recent,
        })
    finally:
        db.close()
