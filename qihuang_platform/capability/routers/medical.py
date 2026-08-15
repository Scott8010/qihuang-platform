"""
医疗专业能力路由 — 辅助辨证 / 处方审查 / 方剂推荐 / 医案归档 / 报告生成 / 文献佐证

映射策略：商业化平台路径 → 现有 8601 API
所有端点需 JWT 认证（通过 deps 注入）
路由前缀: /api/v1/med
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from pydantic import BaseModel, Field

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import AuditLog, MedCase, MedReport
from qihuang_platform.capability.proxy import proxy
from qihuang_platform.gateway.deps import get_current_user
from qihuang_platform.gateway.response import error, success

router = APIRouter()

# 免责声明固定文本
DISCLAIMER = "本系统为辅助工具，最终诊疗决策由执业医师作出"


# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════

class DiagnoseAssistRequest(BaseModel):
    """辅助辨证请求"""
    tongue: Optional[str] = Field(None, description="舌象描述")
    face: Optional[str] = Field(None, description="面象描述")
    pulse: Optional[str] = Field(None, description="脉象描述")
    symptoms: Optional[str] = Field(None, description="症状描述")
    patient_alias: Optional[str] = Field(None, description="患者代号")
    medical_record_id: Optional[str] = Field(None, description="病历ID（可选）")


class HerbItem(BaseModel):
    """中药项"""
    herb: str = Field(..., description="中药名称")
    dose: Optional[str] = Field(None, description="剂量")


class PatientInfo(BaseModel):
    """患者信息"""
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    pregnant: Optional[bool] = Field(None, description="是否妊娠")
    child: Optional[bool] = Field(None, description="是否儿童")
    elderly: Optional[bool] = Field(None, description="是否老年")


class PrescriptionReviewRequest(BaseModel):
    """处方安全审查请求"""
    prescription: List[HerbItem] = Field(..., description="处方中药列表")
    patient_info: Optional[PatientInfo] = Field(None, description="患者信息")
    syndrome: Optional[str] = Field(None, description="证候")
    override_reason: Optional[str] = Field(None, description="覆盖高风险警示的理由")


class CaseCreateRequest(BaseModel):
    """医案归档请求"""
    patient_alias: str = Field(..., description="患者代号")
    diagnoses: Optional[Any] = Field(None, description="诊断信息（dict或list）")
    prescriptions: Optional[Any] = Field(None, description="处方信息（dict或list）")
    notes: Optional[str] = Field(None, description="备注")


class ReportCreateRequest(BaseModel):
    """报告生成请求"""
    case_id: str = Field(..., description="医案ID")
    report_type: str = Field(..., description="报告类型: diagnosed/prescription_review/synthesis")


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

# 安全级别权重（数字越小级别越高）
_LEVEL_WEIGHT = {"HIGH": 1, "MEDIUM": 2, "LOW": 3, "WARN": 4}


def _classify_issue(item: dict) -> dict:
    """将8601返回的禁忌条目统一映射为 {type, herb, description, level}"""
    herb = (
        item.get("herb") or item.get("herb1") or item.get("herb_name")
        or item.get("name") or ""
    )
    description = (
        item.get("description") or item.get("detail")
        or item.get("reason") or item.get("note") or ""
    )
    raw_type = (
        item.get("type") or item.get("category")
        or item.get("conflict_type") or ""
    )
    text = f"{raw_type} {description}".lower()

    # 四级分类：十八反/十九畏(HIGH) / 相恶配伍(MEDIUM) / 证候禁忌(LOW) / 特殊人群(WARN)
    if any(k in text for k in ["十八反", "十反", "十九畏", "反", "畏"]):
        level = "HIGH"
    elif any(k in text for k in ["相恶", "恶"]):
        level = "MEDIUM"
    elif any(k in text for k in ["证候", "禁忌", "证忌"]):
        level = "LOW"
    elif any(k in text for k in [
        "妊娠", "孕妇", "怀孕", "儿童", "小儿", "老年", "老人", "特殊人群", "孕"
    ]):
        level = "WARN"
    else:
        level = item.get("level") or "LOW"

    return {
        "type": raw_type or "未知",
        "herb": herb,
        "description": description or raw_type,
        "level": level,
    }


def _top_level(issues: List[dict]) -> str:
    """取 issues 中最高级别"""
    if not issues:
        return "LOW"
    return min(issues, key=lambda i: _LEVEL_WEIGHT.get(i["level"], 3))["level"]


def _write_audit_log(
    db, tenant_id: str, user_id: str, action: str,
    target_type: str, target_id: str, detail: dict,
    success_flag: bool = True,
):
    """写入审计日志"""
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        success=success_flag,
    )
    db.add(log)
    db.flush()


def _generate_report(report_id: str, case_id: str, report_type: str):
    """后台异步生成报告内容（占位实现，实际应调用8601生成结构化报告）"""
    db = SessionLocal()
    try:
        report = db.query(MedReport).filter_by(id=report_id).first()
        if not report:
            return
        # 占位内容
        report.content = {
            "report_type": report_type,
            "case_id": case_id,
            "summary": "报告内容生成完成（占位）",
            "sections": [],
        }
        report.status = "completed"
        report.pdf_path = f"/reports/{report_id}.pdf"
        # 签名URL（15分钟有效，暂用占位）
        expire = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        report.signature_url = (
            f"https://platform.qihuang.example/sign/{report_id}?expires={expire}"
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[MedReport] 报告生成失败 {report_id}: {e}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 1. 辅助辨证
# ═══════════════════════════════════════════════════════════════

@router.post("/diagnose/assist", summary="辅助辨证")
async def diagnose_assist(
    req: DiagnoseAssistRequest,
    user: dict = Depends(get_current_user),
):
    """
    辅助辨证：四诊合参 + 多体系共识
    并行透传 POST /reasoning/api/sizhen 和 POST /reasoning/api/consensus
    合并返回辨证结果、推理链与共识
    """
    body = {}
    if req.tongue:
        body["tongue"] = req.tongue
    if req.face:
        body["face"] = req.face
    if req.pulse:
        body["pulse"] = req.pulse
    if req.symptoms:
        body["symptoms"] = req.symptoms

    # 并行调用四诊合参与多体系共识
    sizhen_res, consensus_res = await asyncio.gather(
        proxy.forward("POST", "/reasoning/api/sizhen", json_body=body),
        proxy.forward("POST", "/reasoning/api/consensus", json_body=body),
    )

    # 四诊合参失败直接返回错误
    if sizhen_res.get("code") != 0:
        return error(
            code_key="SERVICE_UNAVAILABLE",
            message="辨证服务不可用",
            data=sizhen_res.get("data"),
        )

    sizhen_data = sizhen_res.get("data") or {}
    consensus_data = (
        consensus_res.get("data") if consensus_res.get("code") == 0 else None
    )

    # 提取辨证结果与推理链（兼容多种返回字段名）
    syndromes = (
        sizhen_data.get("syndromes")
        or sizhen_data.get("diagnosis")
        or sizhen_data.get("result")
        or sizhen_data
    )
    reasoning_chain = (
        sizhen_data.get("reasoning_chain")
        or sizhen_data.get("reasoning")
        or []
    )

    return success({
        "syndromes": syndromes,
        "reasoning_chain": reasoning_chain,
        "consensus": consensus_data,
        "disclaimer": DISCLAIMER,
    })


# ═══════════════════════════════════════════════════════════════
# 2. 处方安全四级审查
# ═══════════════════════════════════════════════════════════════

@router.post("/prescription/review", summary="处方安全四级审查")
async def prescription_review(
    req: PrescriptionReviewRequest,
    user: dict = Depends(get_current_user),
):
    """
    处方安全四级审查：
    - HIGH: 十八反/十九畏
    - MEDIUM: 相恶配伍
    - LOW: 证候禁忌
    - WARN: 特殊人群
    HIGH级命中仅警示不拦截，医师可携带 override_reason 覆盖
    孕妇/儿童/老年自动追加特殊人群禁忌检查
    全程写 audit_log
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("sub")

    # 提取中药名称列表
    herbs = [h.herb for h in req.prescription if h.herb]
    if not herbs:
        return error(code_key="MISSING_PARAM", message="处方缺少中药")

    # 构造透传参数
    params = {"herbs": ",".join(herbs)}
    patient_conditions = []
    info = req.patient_info
    if info:
        if info.pregnant:
            patient_conditions.append("妊娠")
        if info.child:
            patient_conditions.append("儿童")
        if info.elderly:
            patient_conditions.append("老年")
    if req.syndrome:
        params["syndrome"] = req.syndrome
    if patient_conditions:
        params["patient_condition"] = ",".join(patient_conditions)

    # 透传安全审查
    res = await proxy.forward("GET", "/reasoning/api/check_safety", params=params)
    if res.get("code") != 0:
        # 审查服务不可达，写失败审计日志
        db = SessionLocal()
        try:
            _write_audit_log(
                db, tenant_id, user_id,
                action="PRESCRIPTION_REVIEW",
                target_type="PRESCRIPTION",
                target_id="",
                detail={
                    "herbs": herbs,
                    "error": "safety service unavailable",
                    "override_reason": req.override_reason,
                },
                success_flag=False,
            )
            db.commit()
        finally:
            db.close()
        return error(
            code_key="SERVICE_UNAVAILABLE",
            message="安全审查服务不可用",
            data=res.get("data"),
        )

    # 收集禁忌条目并分级
    issues = []
    data = res.get("data") or {}
    # 8601可能返回多种列表字段，统一收集
    list_keys = [
        "conflicts", "interactions", "contraindications",
        "warnings", "issues", "results", "items",
    ]
    if isinstance(data, dict):
        for key in list_keys:
            items = data.get(key)
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        issues.append(_classify_issue(it))

    # 孕妇/儿童/老年自动追加特殊人群禁忌警示
    if info and (info.pregnant or info.child or info.elderly):
        special = []
        if info.pregnant:
            special.append("妊娠期")
        if info.child:
            special.append("儿童")
        if info.elderly:
            special.append("老年")
        issues.append({
            "type": "特殊人群",
            "herb": "",
            "description": f"患者属{'/'.join(special)}，需注意特殊人群用药禁忌",
            "level": "WARN",
        })

    has_high_risk = any(i["level"] == "HIGH" for i in issues)
    overridden = bool(req.override_reason) and has_high_risk
    top = _top_level(issues)

    # 写审计日志
    db = SessionLocal()
    try:
        _write_audit_log(
            db, tenant_id, user_id,
            action="PRESCRIPTION_REVIEW",
            target_type="PRESCRIPTION",
            target_id="",
            detail={
                "herbs": herbs,
                "issues_count": len(issues),
                "has_high_risk": has_high_risk,
                "overridden": overridden,
                "override_reason": req.override_reason,
                "level": top,
            },
        )
        db.commit()
    finally:
        db.close()

    return success({
        "level": top,
        "issues": issues,
        "has_high_risk": has_high_risk,
        "overridden": overridden,
        "disclaimer": DISCLAIMER,
    })


# ═══════════════════════════════════════════════════════════════
# 3. 方剂推荐
# ═══════════════════════════════════════════════════════════════



# 方剂名有效性判定（需求6 P1(a) 推荐过滤：排除爬虫杂文噪声）
import re as _re
_FORMULA_MARKERS = ("汤", "散", "丸", "饮", "膏", "丹", "合剂", "汤剂")
_NOISE_HINTS = ("氯化钠", "注射液", "输液", "受体", "提取物", "混合物", "乙醇", "中医药", "中药", "丸药")


def _is_valid_formula(f: dict) -> bool:
    """有效方剂 = 含中文名 + (含方剂名特征 或 herbs_count>0)，且非西药/泛化噪声。"""
    if not isinstance(f, dict):
        return False
    name = (f.get("name") or "")
    if not name or not _re.search(r"[\u4e00-\u9fff]", name):
        return False  # 纯英文/数字缩写 (BYP/CPT/0.9%...) 排除
    if any(h in name for h in _NOISE_HINTS):
        return False  # 西药/泛化非方剂 (氯化钠/受体/中药/丸药...) 排除
    if any(m in name for m in _FORMULA_MARKERS):
        return True
    if (f.get("herbs_count") or 0) > 0:
        return True
    return False


@router.get("/formula/recommend", summary="方剂推荐")
async def formula_recommend(
    syndrome: str = Query(..., description="证候"),
    category: Optional[str] = Query(None, description="方剂类别"),
    user: dict = Depends(get_current_user),
):
    """根据证候推荐方剂，透传 GET /api/v1/formulas?syndrome=xxx，并过滤非方剂噪声"""
    params = {"syndrome": syndrome}
    if category:
        params["category"] = category
    result = await proxy.forward("GET", "/api/v1/formulas", params=params)
    _data = result.get("data") if isinstance(result, dict) else None
    if isinstance(_data, dict):
        _raw = _data.get("formulas") or []
        if isinstance(_raw, list):
            _kept = [f for f in _raw if _is_valid_formula(f)]
            _data["formulas"] = _kept
            _data["total"] = len(_kept)
            _data["filtered_noise"] = len(_raw) - len(_kept)
    return result


# ═══════════════════════════════════════════════════════════════
# 4. 医案归档（含幂等）
# ═══════════════════════════════════════════════════════════════

@router.post("/cases", summary="医案归档")
async def create_case(
    req: CaseCreateRequest,
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    医案归档：保存诊断与处方信息
    幂等：检查 Idempotency-Key header（24h内去重）
    写 audit_log
    """
    tenant_id = user.get("tenant_id")
    user_id = user.get("sub")

    db = SessionLocal()
    try:
        # 幂等检查：24h内相同 key 视为重复
        if idempotency_key:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            existing = (
                db.query(MedCase)
                .filter(
                    MedCase.idempotency_key == idempotency_key,
                    MedCase.created_at >= cutoff,
                )
                .first()
            )
            if existing:
                # 命中幂等，返回已有记录
                _write_audit_log(
                    db, tenant_id, user_id,
                    action="MED_CASE_CREATE",
                    target_type="MED_CASE",
                    target_id=existing.id,
                    detail={
                        "idempotent_hit": True,
                        "original_case_id": existing.id,
                    },
                )
                db.commit()
                return success({"case_id": existing.id, "created": False})

        # 创建医案
        case = MedCase(
            tenant_id=tenant_id,
            doctor_id=user_id,
            patient_alias=req.patient_alias,
            diagnoses=req.diagnoses,
            prescriptions=req.prescriptions,
            notes=req.notes,
            idempotency_key=idempotency_key,
        )
        db.add(case)
        db.flush()

        _write_audit_log(
            db, tenant_id, user_id,
            action="MED_CASE_CREATE",
            target_type="MED_CASE",
            target_id=case.id,
            detail={
                "patient_alias": req.patient_alias,
                "idempotency_key": idempotency_key,
            },
        )
        db.commit()

        return success({"case_id": case.id, "created": True})
    except Exception as e:
        db.rollback()
        return error(code_key="INTERNAL_ERROR", message=f"医案归档失败: {e}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 5. 报告生成（异步）
# ═══════════════════════════════════════════════════════════════

@router.post("/reports", summary="报告生成")
async def create_report(
    req: ReportCreateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """
    报告生成：创建 MedReport 记录，状态 draft
    异步生成内容（占位），返回 generating 状态供前端轮询
    """
    tenant_id = user.get("tenant_id")

    # 校验报告类型
    valid_types = {"diagnosed", "prescription_review", "synthesis"}
    if req.report_type not in valid_types:
        return error(
            code_key="INVALID_PARAM",
            message=f"报告类型无效，有效值: {valid_types}",
        )

    db = SessionLocal()
    try:
        # 校验医案存在
        case = db.query(MedCase).filter_by(
            id=req.case_id, tenant_id=tenant_id
        ).first()
        if not case:
            return error(code_key="NOT_FOUND", message="医案不存在")

        report = MedReport(
            tenant_id=tenant_id,
            case_id=req.case_id,
            report_type=req.report_type,
            disclaimer=DISCLAIMER,
            status="draft",
        )
        db.add(report)
        db.flush()
        db.commit()
        report_id = report.id
    except Exception as e:
        db.rollback()
        return error(code_key="INTERNAL_ERROR", message=f"报告创建失败: {e}")
    finally:
        db.close()

    # 后台异步生成报告内容
    background_tasks.add_task(
        _generate_report, report_id, req.case_id, req.report_type
    )

    return success({
        "report_id": report_id,
        "status": "generating",
        "disclaimer": DISCLAIMER,
    })


# ═══════════════════════════════════════════════════════════════
# 6. 查询报告状态
# ═══════════════════════════════════════════════════════════════

@router.get("/reports/{report_id}", summary="查询报告状态")
async def get_report(
    report_id: str,
    user: dict = Depends(get_current_user),
):
    """
    查询报告状态：
    - 生成中：返回 generating
    - 已完成：返回报告详情与 PDF 下载URL（签名URL 15分钟有效，暂用占位）
    """
    tenant_id = user.get("tenant_id")

    db = SessionLocal()
    try:
        report = db.query(MedReport).filter_by(
            id=report_id, tenant_id=tenant_id
        ).first()
        if not report:
            return error(code_key="NOT_FOUND", message="报告不存在")

        if report.status == "completed":
            return success({
                "report_id": report.id,
                "case_id": report.case_id,
                "report_type": report.report_type,
                "status": "completed",
                "content": report.content,
                "pdf_url": report.signature_url,
                "expires_in": 900,  # 签名URL 15分钟有效
                "disclaimer": report.disclaimer,
            })
        else:
            return success({
                "report_id": report.id,
                "status": "generating",
                "disclaimer": report.disclaimer,
            })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 7. 文献佐证
# ═══════════════════════════════════════════════════════════════

@router.get("/evidence/{syndrome_id}", summary="文献佐证")
async def get_evidence(
    syndrome_id: str,
    user: dict = Depends(get_current_user),
):
    """根据证候ID检索相关文献，透传 GET /library/api/list?keyword=syndrome_id"""
    return await proxy.forward(
        "GET", "/library/api/list", params={"keyword": syndrome_id}
    )
