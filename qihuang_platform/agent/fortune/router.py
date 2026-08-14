"""
命理运程 Agent（business_embedded，功能业务型，与 compliance 同构）

端点（全部需 JWT，tenant_id 由网关注入 request.state）：
  POST /api/v1/agent/fortune/archive  四柱建档 → 八字排盘 + 喜用神（钉 user_id）
  POST /api/v1/agent/fortune/cast     六爻起卦（铜钱/时间）→ 本卦/变卦/动爻/解析
  GET  /api/v1/agent/fortune/daily    每日运程日签（五行穿衣/茶/宜忌/吉时方位…）
  POST /api/v1/agent/fortune/report   年运报告（八字 + 流年）
  POST /api/v1/agent/fortune/geo      风水堪舆（看空间）：坐向+GPS → 宅卦/八宅/九宫
  GET  /api/v1/agent/fortune/dashboard 运营看板（按 user 聚合）

隔离红线：数据落独立 JSONL（不入 Neo4j / 不污染中医库）；受 require_agent_in_plan 门控。
"""
from __future__ import annotations

import os
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from qihuang_platform.gateway.deps import get_current_user, get_current_admin
from qihuang_platform.gateway.response import success, error
from qihuang_platform.agent.deps import require_agent_in_plan
from qihuang_platform.db.config import get_db
from qihuang_platform.agent.fortune.schema import (
    ArchiveRequest, CastRequest, DailyRequest, ReportRequest, GeoRequest,
)
from qihuang_platform.agent.fortune import engine
from qihuang_platform.agent.fortune.store import FortuneStore, make_material_id
from qihuang_platform.agent.fortune.audit import AuditStore

router = APIRouter()

_HERE = os.path.dirname(__file__)
_seed = os.path.join(_HERE, "seed")
os.makedirs(_seed, exist_ok=True)
_store = FortuneStore(os.path.join(_seed, "fortune.jsonl"))
_audit = AuditStore(os.path.join(_seed, "audit.jsonl"))


@router.post("/fortune/archive")
async def fortune_archive(
    req: ArchiveRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """四柱建档：排盘 + 喜用神，钉在 user_id 上（幂等覆盖）。四柱或公历生日二选一。"""
    try:
        if req.birth:
            b = req.birth
            prof = engine.bazi_profile_from_birth(
                b["date"], int(b.get("hour", 0)),
                int(b.get("minute", 0)), float(b.get("lng", 116.40)),
            )
            if req.gender in ("男", "女"):
                engine.attach_destiny(prof, req.gender, b["date"])
        else:
            prof = engine.bazi_profile(req.pillars)
    except (ValueError, KeyError, TypeError) as e:
        return error(code_key="BAD_PILLARS", message=str(e))
    prof["birth"] = req.birth
    material_key = f"fortune:archive:{req.user_id}"
    material_id = make_material_id(material_key)
    prof["kind"] = "archive"
    prof["user_id"] = req.user_id
    prof["material_key"] = material_key
    prof["name"] = req.name
    if req.persist:
        _store.upsert(material_id, prof)
        _audit.append("archive", operator=getattr(request.state, "user_id", "unknown"),
                      user_id=req.user_id, material_id=material_id)
    return success(data={"material_id": material_id, **prof})


@router.post("/fortune/cast")
async def fortune_cast(
    req: CastRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """六爻起卦：铜钱/时间，返回本卦/变卦/动爻/趣味解析（ai=true 时附 LLM 象义层详批）。"""
    result = engine.liuyao(method=req.method, question=req.question or "", ai=req.ai)
    result["kind"] = "cast"
    result["user_id"] = req.user_id
    material_key = f"fortune:cast:{req.user_id or 'anon'}:{result['ben_gua']}"
    material_id = make_material_id(material_key)
    _store.upsert(material_id, result)
    _audit.append("cast", operator=getattr(request.state, "user_id", "unknown"),
                  user_id=req.user_id, ben_gua=result["ben_gua"])
    return success(data={"material_id": material_id, **result})


@router.get("/fortune/daily")
async def fortune_daily(
    user_id: str = None,
    pillars: str = None,
    ai: bool = False,
    request: Request = None,
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """每日运程日签：默认通用；带 user_id/四柱则做个性化喜用；ai=true 附 AI 散文详批。"""
    fav = unfav = dm = None
    if user_id:
        recs = _store.all(kind="archive", user_id=user_id)
        if recs:
            fav = recs[-1].get("favorable")
            unfav = recs[-1].get("unfavorable")
            dm = recs[-1].get("day_master")
    elif pillars:
        try:
            prof = engine.bazi_profile(pillars)
            fav, unfav = prof.get("favorable"), prof.get("unfavorable")
            dm = prof.get("day_master")
        except ValueError:
            fav = unfav = dm = None
    data = engine.daily_sign(date=date.today(), favorable=fav, unfavorable=unfav,
                             day_master=dm, ai=ai)
    _audit.append("daily", operator=getattr(request.state, "user_id", "unknown"),
                  user_id=user_id)
    return success(data=data)


@router.post("/fortune/report")
async def fortune_report(
    req: ReportRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """年运报告：优先用已建档 user_id，否则四柱直输；ai=true 附 AI 散文详批。"""
    pillars = None
    cur_dayun = None
    if req.user_id:
        recs = _store.all(kind="archive", user_id=req.user_id)
        if recs:
            pillars = " ".join(recs[-1]["pillars"])
            # 建档时已排大运，取当前所处大运步（年运×大运交互所需）
            cur_dayun = recs[-1].get("liunian", {}).get("active_dayun")
    if not pillars and req.pillars:
        pillars = req.pillars
    if not pillars:
        return error(code_key="NO_PROFILE", message="需提供 user_id（已建档）或四柱 pillars")
    try:
        data = engine.year_report(pillars, year=req.year, cur_dayun=cur_dayun, ai=req.ai)
    except ValueError as e:
        return error(code_key="BAD_PILLARS", message=str(e))
    _audit.append("report", operator=getattr(request.state, "user_id", "unknown"),
                  user_id=req.user_id)
    return success(data=data)


@router.post("/fortune/geo")
async def fortune_geo(
    req: GeoRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """向后兼容端点：委托 geo Agent 处理，数据统一落独立 geo 库（隔离红线）。"""
    from qihuang_platform.agent.geo.router import geo_analysis
    return geo_analysis(req, request, operator=getattr(request.state, "user_id", "unknown"))


@router.get("/fortune/dashboard")
async def fortune_dashboard(
    user_id: str = None,
    request: Request = None,
    user: dict = Depends(get_current_admin),
    _agent=Depends(require_agent_in_plan("fortune")),
):
    """运营看板：按 user 聚合调用量与类型分布。"""
    return success(data=_store.dashboard(user_id=user_id))
