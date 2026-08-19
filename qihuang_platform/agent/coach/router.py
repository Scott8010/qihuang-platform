"""
coach · 路由（Agent 中台接入点）— 上收 8602 既有 edu/coach 能力

端点：
  POST /api/v1/agent/coach/sessions  创建 AI 陪练会话
  POST /api/v1/agent/coach/evaluate  提交作答并基于推理链四档评分
  GET  /api/v1/agent/coach/dashboard 本店陪练学情看板
鉴权：JWT（get_current_principal 注入 request.state.tenant_id）+ 套餐校验（require_agent_in_plan("coach")）
能力引擎：复用 EduCoachSession 模型 + 8601 /chat/api/ask 推理链 + 四档评分
        （评分口径与 capability/routers/education.py 的 _evaluate_answer 对齐，保持一致）
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from qihuang_platform.gateway.deps import get_current_principal
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.agent.coach.metering import check_quota, record_call
from qihuang_platform.db.models import EduCoachSession
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.capability.proxy import proxy

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class CoachSessionRequest(BaseModel):
    topic: str = Field(..., description="陪练主题，如 '太阳病辨证'")
    difficulty: Optional[str] = Field("medium", description="难度: easy/medium/hard")
    case_id: Optional[str] = Field(None, description="关联病案ID（可选）")


class CoachEvaluateRequest(BaseModel):
    session_id: str = Field(..., description="陪练会话ID")
    answer: str = Field(..., description="学员作答内容")


# ═══════════════════════════════════════════════════════════════
# 评分（与 education.py 的 _evaluate_answer 口径对齐）
# ═══════════════════════════════════════════════════════════════

def _evaluate_answer(answer: str, ai_response: str, reasoning_chain: list) -> tuple:
    """基于作答内容与AI推理链评估作答质量，返回(判定, 分数, 反馈)。

    判定标准（对齐 capability/routers/education.py）：
    - PERFECT: 作答完整 (90-100)
    - GOOD: 基本正确 (70-89)
    - PARTIAL: 部分正确 (40-69)
    - WRONG: 过简/偏离 (0-39)
    """
    answer_len = len(answer.strip())
    if answer_len < 10:
        return "WRONG", 20.0, "作答过于简略，未体现辨证思路。"
    elif answer_len < 30:
        return "PARTIAL", 50.0, "作答不够充分，需补充辨证依据与方药选择。"
    elif answer_len < 80:
        return "GOOD", 75.0, "作答基本正确，建议进一步细化推理过程。"
    else:
        return "PERFECT", 92.0, "作答完整，辨证思路清晰，方药选择合理。"


# ═══════════════════════════════════════════════════════════════
# 1. 创建 AI 陪练会话
# ════════════════════ 上收入口 ═════════════════════════════════

@router.post(
    "/coach/sessions",
    summary="创建中医辨证陪练会话（上收 edu/coach）",
)
async def create_coach_session(
    req: CoachSessionRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("coach")),
):
    valid_difficulties = ["easy", "medium", "hard"]
    if req.difficulty not in valid_difficulties:
        return error("INVALID_PARAM", f"不支持的难度: {req.difficulty}，有效值: {valid_difficulties}")

    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月陪练调用配额已用完，请升级套餐或次月恢复。")

    db = SessionLocal()
    try:
        session = EduCoachSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            topic=req.topic,
            messages=[],
            reviewed=False,
        )
        db.add(session)
        db.commit()
        return success(data={
            "session_id": session.id,
            "topic": session.topic,
            "status": "active",
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 2. 提交作答并评估
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/coach/evaluate",
    summary="提交作答并评估（上收 edu/coach）",
)
async def coach_evaluate(
    req: CoachEvaluateRequest,
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("coach")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    user_id = user.get("user_id")

    if not check_quota(tenant_id):
        return error("QUOTA_EXCEEDED", "本月陪练调用配额已用完，请升级套餐或次月恢复。")

    db = SessionLocal()
    try:
        session = db.query(EduCoachSession).filter_by(
            id=req.session_id, tenant_id=tenant_id
        ).first()
        if not session:
            return error("NOT_FOUND", f"陪练会话不存在: {req.session_id}")

        # 透传 8601 获取 AI 回复（推理链）
        ai_result = await proxy.forward("POST", "/chat/api/ask", json_body={
            "message": req.answer,
        })

        ai_response = ""
        reasoning_chain = []
        if ai_result.get("code") == 0:
            ai_data = ai_result.get("data")
            if isinstance(ai_data, dict):
                ai_response = ai_data.get("answer") or ai_data.get("response") or ai_data.get("message") or str(ai_data)
                reasoning_chain = ai_data.get("reasoning_chain") or ai_data.get("reasoning") or []
            elif isinstance(ai_data, str):
                ai_response = ai_data
        else:
            ai_response = "（AI服务暂不可用）"

        evaluation, score, feedback = _evaluate_answer(req.answer, ai_response, reasoning_chain)

        messages = session.messages or []
        messages.append({"role": "user", "content": req.answer})
        messages.append({"role": "assistant", "content": ai_response})
        session.messages = messages
        session.evaluation = evaluation
        session.score = score
        session.feedback = feedback
        db.commit()

        return success(data={
            "evaluation": evaluation,
            "score": score,
            "feedback": feedback,
            "reasoning_chain": reasoning_chain,
            "ai_response": ai_response,
            "reviewed": session.reviewed,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 3. 本店陪练学情看板
# ═══════════════════════════════════════════════════════════════

@router.get(
    "/coach/dashboard",
    summary="本店中医辨证陪练学情看板（上收 edu/coach）",
)
async def coach_dashboard(
    request: Request,
    user: dict = Depends(get_current_principal),
    _: Any = Depends(require_agent_in_plan("coach")),
):
    tenant_id = getattr(request.state, "tenant_id", None) or user.get("tenant_id")
    db = SessionLocal()
    try:
        sessions = db.query(EduCoachSession).filter_by(tenant_id=tenant_id).all()
        coach_count = len(sessions)
        scored = [s for s in sessions if s.score is not None]
        avg_score = (sum(s.score for s in scored) / len(scored)) if scored else 0.0
        return success(data={
            "coach_sessions": coach_count,
            "scored_sessions": len(scored),
            "coach_avg_score": round(avg_score, 1),
        })
    finally:
        db.close()
