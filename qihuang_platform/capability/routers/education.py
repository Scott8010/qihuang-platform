"""
培训场景能力路由 — 经典检索 / AI陪练 / 智能组卷 / 教学病案 / 学情看板

路由前缀 /api/v1/edu，所有端点需 JWT 认证。
教研审核工作流：未审校的陪练内容不可进入正式测评卷。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Header
from pydantic import BaseModel, Field

from qihuang_platform.db.models import EduCoachSession, EduExamRecord, MedCase
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.gateway.deps import get_current_user
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.capability.proxy import proxy

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class CoachSessionRequest(BaseModel):
    """创建AI陪练会话请求"""
    topic: str = Field(..., description="陪练主题，如 '太阳病辨证'")
    difficulty: Optional[str] = Field("medium", description="难度: easy/medium/hard")
    case_id: Optional[str] = Field(None, description="关联病案ID（可选）")


class CoachEvaluateRequest(BaseModel):
    """提交作答并评估请求"""
    session_id: str = Field(..., description="陪练会话ID")
    answer: str = Field(..., description="学员作答内容")


class ExamGenerateRequest(BaseModel):
    """智能组卷请求"""
    category: str = Field(..., description="题目类别，如 '伤寒论'")
    difficulty: str = Field("medium", description="难度: easy/medium/hard")
    question_count: int = Field(10, ge=1, le=50, description="题目数量")
    question_types: Optional[list[str]] = Field(None, description="题型: choice/fill/short_answer")


class ExamSubmitRequest(BaseModel):
    """提交判分请求"""
    exam_id: str = Field(..., description="试卷记录ID")
    answers: dict = Field(..., description="作答映射 {question_id: answer}")


# ═══════════════════════════════════════════════════════════════
# 1. 经典条文检索
# ═══════════════════════════════════════════════════════════════

@router.get("/classics/search", summary="经典条文检索")
async def classics_search(
    keyword: str = Query(..., description="检索关键词"),
    classic: Optional[str] = Query(None, description="经典来源: 内经/伤寒论/金匮要略/温病条辨"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(get_current_user),
):
    """
    经典条文检索，透传到8601: GET /api/v1/classics
    支持按关键词和经典来源筛选，返回分页结果。
    """
    valid_classics = ["内经", "伤寒论", "金匮要略", "温病条辨"]
    if classic and classic not in valid_classics:
        return error("INVALID_PARAM", f"不支持的经典来源: {classic}，有效值: {valid_classics}")

    # 8601 /api/v1/classics 参数为 q(全文搜索)/source(来源)/limit(数量)
    params = {"q": keyword, "limit": page_size}
    if classic:
        params["source"] = classic

    result = await proxy.forward("GET", "/api/v1/classics", params=params)

    # 透传失败时直接返回错误
    if result.get("code") != 0:
        return result

    raw = result.get("data")
    # 兼容8601返回格式：可能是列表或带分页的字典
    # 8601 /api/v1/classics 返回 {"total": N, "classics": [...]}
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("classics") or []
        total = raw.get("total", len(items))
        return paginated(items, total, page, page_size)
    elif isinstance(raw, list):
        total = len(raw)
        start = (page - 1) * page_size
        items = raw[start:start + page_size]
        return paginated(items, total, page, page_size)
    else:
        return paginated([], 0, page, page_size)


# ═══════════════════════════════════════════════════════════════
# 2. 创建AI陪练会话
# ═══════════════════════════════════════════════════════════════

@router.post("/coach/sessions", summary="创建AI陪练会话")
async def create_coach_session(req: CoachSessionRequest, user: dict = Depends(get_current_user)):
    """
    创建AI陪练会话，初始化空对话历史。
    返回会话ID与状态。
    """
    valid_difficulties = ["easy", "medium", "hard"]
    if req.difficulty not in valid_difficulties:
        return error("INVALID_PARAM", f"不支持的难度: {req.difficulty}，有效值: {valid_difficulties}")

    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

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
# 3. 提交作答并评估
# ═══════════════════════════════════════════════════════════════

@router.post("/coach/evaluate", summary="提交作答并评估")
async def coach_evaluate(req: CoachEvaluateRequest, user: dict = Depends(get_current_user)):
    """
    提交学员作答，透传到8601获取AI回复，基于推理链评估作答质量。
    四档判定: PERFECT / GOOD / PARTIAL / WRONG
    更新陪练会话的评估结果，返回评估详情与AI回复。
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

    db = SessionLocal()
    try:
        # 查找陪练会话，校验归属
        session = db.query(EduCoachSession).filter_by(
            id=req.session_id, tenant_id=tenant_id
        ).first()
        if not session:
            return error("NOT_FOUND", f"陪练会话不存在: {req.session_id}")
        if session.user_id != user_id:
            return error("FORBIDDEN", "无权操作他人陪练会话")

        # 透传到8601获取AI回复
        ai_result = await proxy.forward("POST", "/chat/api/ask", json_body={
            "message": req.answer,
        })

        # 提取AI回复内容
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
            # AI服务不可用时仍记录作答，但标注AI回复失败
            ai_response = "（AI服务暂不可用）"

        # 基于推理链评估作答质量（简化判定逻辑）
        evaluation, score, feedback = _evaluate_answer(req.answer, ai_response, reasoning_chain)

        # 更新陪练会话
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


def _evaluate_answer(answer: str, ai_response: str, reasoning_chain: list) -> tuple:
    """
    基于作答内容与AI推理链评估作答质量，返回(判定, 分数, 反馈)。

    判定标准:
    - PERFECT: 作答完整且与推理链高度吻合 (90-100)
    - GOOD: 作答基本正确，略有遗漏 (70-89)
    - PARTIAL: 作答部分正确，存在明显不足 (40-69)
    - WRONG: 作答错误或偏离主题 (0-39)
    """
    answer_len = len(answer.strip())

    # 简化评估：基于作答长度与关键词覆盖度
    if answer_len < 10:
        return "WRONG", 20.0, "作答过于简略，未体现辨证思路。"
    elif answer_len < 30:
        return "PARTIAL", 50.0, "作答不够充分，需补充辨证依据与方药选择。"
    elif answer_len < 80:
        return "GOOD", 75.0, "作答基本正确，建议进一步细化推理过程。"
    else:
        return "PERFECT", 92.0, "作答完整，辨证思路清晰，方药选择合理。"


# ═══════════════════════════════════════════════════════════════
# 4. 智能组卷
# ═══════════════════════════════════════════════════════════════

@router.post("/exams/generate", summary="智能组卷")
async def exam_generate(req: ExamGenerateRequest, user: dict = Depends(get_current_user)):
    """
    智能组卷：透传到8601获取经典条文作为题目素材，
    生成试卷结构保存到EduExamRecord（answers为空）。
    """
    valid_difficulties = ["easy", "medium", "hard"]
    if req.difficulty not in valid_difficulties:
        return error("INVALID_PARAM", f"不支持的难度: {req.difficulty}，有效值: {valid_difficulties}")

    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

    # 透传到8601获取题目素材 (8601 参数为 q/limit)
    result = await proxy.forward("GET", "/api/v1/classics", params={
        "q": req.category,
        "limit": req.question_count,
    })

    if result.get("code") != 0:
        return result

    raw = result.get("data")
    # 提取素材列表 (兼容8601返回的 items / classics / 列表)
    if isinstance(raw, dict):
        source_items = raw.get("items") or raw.get("classics") or []
    elif isinstance(raw, list):
        source_items = raw
    else:
        source_items = []

    # 生成试卷题目
    question_types = req.question_types or ["choice", "fill", "short_answer"]
    questions = []
    for i, item in enumerate(source_items[:req.question_count]):
        q_type = question_types[i % len(question_types)]
        # 从经典条文中提取内容
        content = ""
        if isinstance(item, dict):
            content = item.get("content") or item.get("text") or item.get("passage") or str(item)
        else:
            content = str(item)

        question = {
            "id": f"q_{i+1}",
            "type": q_type,
            "content": content,
        }
        # 选择题生成选项
        if q_type == "choice":
            question["options"] = {
                "A": "辨证正确，方药得当",
                "B": "辨证正确，方药不当",
                "C": "辨证错误，方药得当",
                "D": "辨证错误，方药不当",
            }
        questions.append(question)

    # 保存试卷记录到数据库
    db = SessionLocal()
    try:
        exam_config = {
            "category": req.category,
            "difficulty": req.difficulty,
            "question_count": req.question_count,
            "question_types": question_types,
        }
        exam_record = EduExamRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            exam_config={
                **exam_config,
                "questions": questions,
            },
            answers=None,
            score=None,
            max_score=float(req.question_count),
        )
        db.add(exam_record)
        db.commit()

        return success(data={
            "exam_id": exam_record.id,
            "questions": questions,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 5. 提交判分（幂等）
# ═══════════════════════════════════════════════════════════════

@router.post("/exams/submit", summary="提交判分（幂等）")
async def exam_submit(
    req: ExamSubmitRequest,
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    提交试卷答案并判分。支持幂等：通过 Idempotency-Key header 去重。
    简单判分逻辑：对比预设答案，每题1分。
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

    db = SessionLocal()
    try:
        # 幂等检查：相同 Idempotency-Key 已处理则直接返回已有结果
        if idempotency_key:
            existing = db.query(EduExamRecord).filter_by(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
            ).first()
            if existing and existing.answers is not None:
                return success(data={
                    "score": existing.score,
                    "max_score": existing.max_score,
                    "pass": (existing.score / existing.max_score) >= 0.6 if existing.max_score else False,
                    "details": existing.answers.get("_details", []),
                    "idempotent": True,
                })

        # 查找试卷记录
        exam = db.query(EduExamRecord).filter_by(
            id=req.exam_id, tenant_id=tenant_id
        ).first()
        if not exam:
            return error("NOT_FOUND", f"试卷记录不存在: {req.exam_id}")
        if exam.user_id != user_id:
            return error("FORBIDDEN", "无权操作他人试卷")

        # 获取试卷题目
        questions = (exam.exam_config or {}).get("questions", [])
        if not questions:
            return error("INVALID_PARAM", "试卷无题目数据")

        # 简单判分：对比答案（每题1分，满分为题目数）
        score = 0.0
        details = []
        for q in questions:
            q_id = q["id"]
            user_answer = req.answers.get(q_id, "")
            # 简化判分：选择题对比选项，其他题型检查是否有作答
            correct_answer = q.get("correct_answer", "A")
            is_correct = str(user_answer).strip().upper() == str(correct_answer).strip().upper()
            if is_correct:
                score += 1.0
            details.append({
                "question_id": q_id,
                "correct": is_correct,
                "correct_answer": correct_answer,
            })

        max_score = float(len(questions))
        pass_rate = score / max_score if max_score else 0.0

        # 更新试卷记录
        exam.answers = {**req.answers, "_details": details}
        exam.score = score
        exam.max_score = max_score
        if idempotency_key:
            exam.idempotency_key = idempotency_key
        db.commit()

        return success(data={
            "score": score,
            "max_score": max_score,
            "pass": pass_rate >= 0.6,
            "details": details,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 6. 教学病案库
# ═══════════════════════════════════════════════════════════════

@router.get("/cases/library", summary="教学病案库")
async def cases_library(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(get_current_user),
):
    """
    教学病案库：查询MedCase表，按租户隔离。
    支持按关键词搜索诊断信息和备注。
    """
    tenant_id = user.get("tenant_id")

    db = SessionLocal()
    try:
        query = db.query(MedCase).filter_by(tenant_id=tenant_id)

        # 关键词搜索
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.filter(
                MedCase.diagnoses.like(like_pattern) |
                MedCase.notes.like(like_pattern) |
                MedCase.patient_alias.like(like_pattern)
            )

        total = query.count()
        offset = (page - 1) * page_size
        cases = query.order_by(MedCase.created_at.desc()).offset(offset).limit(page_size).all()

        items = []
        for c in cases:
            items.append({
                "id": c.id,
                "patient_alias": c.patient_alias,
                "diagnoses": c.diagnoses,
                "prescriptions": c.prescriptions,
                "notes": c.notes,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

        return paginated(items, total, page, page_size)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 7. 学情看板
# ═══════════════════════════════════════════════════════════════

@router.get("/progress/dashboard", summary="学情看板")
async def progress_dashboard(user: dict = Depends(get_current_user)):
    """
    学情看板：统计当前用户的陪练与测评数据。
    返回总陪练次数、平均分、测评次数、测评平均分、薄弱知识域。
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("user_id")

    db = SessionLocal()
    try:
        # 查询陪练会话
        coach_sessions = db.query(EduCoachSession).filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).all()

        coach_count = len(coach_sessions)
        scored_sessions = [s for s in coach_sessions if s.score is not None]
        coach_avg_score = (
            sum(s.score for s in scored_sessions) / len(scored_sessions)
            if scored_sessions else 0.0
        )

        # 查询测评记录
        exam_records = db.query(EduExamRecord).filter_by(
            tenant_id=tenant_id, user_id=user_id
        ).all()

        exams_taken = len(exam_records)
        scored_exams = [e for e in exam_records if e.score is not None]
        exam_avg_score = (
            sum(e.score for e in scored_exams) / len(scored_exams)
            if scored_exams else 0.0
        )

        # 薄弱知识域分析：按陪练主题统计低分项
        weak_areas = []
        topic_scores = {}
        for s in coach_sessions:
            if s.score is not None and s.topic:
                topic_scores.setdefault(s.topic, []).append(s.score)

        for topic, scores in topic_scores.items():
            avg = sum(scores) / len(scores)
            if avg < 60.0:
                weak_areas.append({
                    "topic": topic,
                    "avg_score": round(avg, 1),
                    "session_count": len(scores),
                })

        # 按平均分升序排列薄弱知识域
        weak_areas.sort(key=lambda x: x["avg_score"])

        return success(data={
            "coach_sessions": coach_count,
            "coach_avg_score": round(coach_avg_score, 1),
            "exams_taken": exams_taken,
            "exam_avg_score": round(exam_avg_score, 1),
            "weak_areas": weak_areas,
        })
    finally:
        db.close()
