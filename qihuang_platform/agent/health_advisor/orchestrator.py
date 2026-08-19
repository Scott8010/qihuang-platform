"""
health-advisor · 编排器（S1-S7 固定专业辨证链 + partial 降级 + 免责必带）

方案B（已拍板）：
  - S3/S4/S5 主用 8601 `/reasoning/api/sizhen` 一次拿全（省 2 次 LLM 往返、降延迟、字段更齐）
  - syndrome 提取用 LLM 解析（决策2，骨架先用 parser.extract_syndrome_rule 兜底，预留 LLM 接入）
  - 缺脉象→辨证空/置信度低（探查实证）→ S2 追问为刚需，非可选项

会话（S? 多轮）：本骨架用内存 dict 占位；P0-3 确认后换 Redis/DB（不阻塞开工）。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from .l1_client import L1Client
from .metering import record_call
from .parser import extract_syndrome_rule, parse_sizhen
from .reports import generate_report
from .session import SessionStore
from .prompts import (
    CHITCHAT_REPLY,
    build_ask_more,
    classify_intent,
    detect_missing,
)
from .schema import (
    ConsultRequest,
    ConsultResponse,
    Constitution,
    Formula,
    Syndrome,
)

logger = logging.getLogger("health_advisor.orchestrator")

DISCLAIMER = (
    "以上仅为基于中医理论的辅助参考，不构成诊断或处方；"
    "具体用药与调理请务必咨询执业中医师。个体体质有异，切勿自行配药。"
)


class HealthAdvisor:
    def __init__(self) -> None:
        # 会话持久化：优先 Redis（平台 db.redis.get_redis），不可用降级内存
        self._sessions = SessionStore()

    async def consult(self, req: ConsultRequest, tenant_id: Optional[str]) -> ConsultResponse:
        trace_id = uuid.uuid4().hex[:8]
        _t0 = time.monotonic()
        session_id = req.session_id or uuid.uuid4().hex[:12]
        symptoms = (req.question or "").strip()
        profile = req.profile
        tongue = profile.tongue if profile else None
        pulse = profile.pulse if profile else None

        # ── S1 意图理解：闲聊(C3)引导回健康咨询，不触发专业链 ──
        if classify_intent(req.question) == "chitchat":
            resp = ConsultResponse(
                reply=CHITCHAT_REPLY,
                ask_more=None,
                partial=True,
                disclaimer=DISCLAIMER,
                trace_id=trace_id,
                session_id=session_id,
            )
            await self._emit_metering(tenant_id, req, _t0, trace_id, resp, code=0)
            return resp

        # ── S2 信息补齐：缺失项检测 + 追问上限 2 次 ──
        sess = self._sessions.get(session_id)
        missing = detect_missing(
            question=req.question,
            tongue=tongue, pulse=pulse,
            age=profile.age if profile else None,
            sex=profile.sex if profile else None,
        )
        ask_more: Optional[str] = None
        if missing and sess["ask_count"] < 2:
            ask_more = build_ask_more(missing, sess["ask_count"] + 1)
            self._sessions.touch_ask(session_id)

        # ── S3/S4/S5 主用 sizhen 一次拿全（方案B，已知信息即可 partial）──
        sizhen = await L1Client.sizhen(symptoms=symptoms, tongue=tongue, pulse=pulse)
        constitution, formulas, suggestions = parse_sizhen(sizhen)

        # ── syndrome 提取（规则兜底，预留 LLM）──
        chat = await L1Client.chat(message=req.question)
        syndrome = extract_syndrome_rule(sizhen, chat)

        # ── S5 方剂策略：sizhen.medication.formulas 已是主力来源（真实数据实测常非空，
        #    如「气虚质」返回四君子汤/补中益气汤）。formulas 静态库覆盖极薄
        #    （心脾两虚/气血两虚/肝郁气滞/肾阳虚 实测 total=0），不再降级调用，
        #    避免无效 LLM 往返；sizhen 无方剂时由 S6 提示「以生活调理为主」。 ──

        partial = bool(ask_more) or bool(missing) or (len(formulas) == 0)

        # ── S6 人话组装（骨架：结构化拼接；预留 LLM 润色）──
        reply = self._assemble(constitution, syndrome, formulas, suggestions, partial)

        # ── S? 会话留存（Redis 持久化，ask_count 已在 S2 阶段维护）──
        self._sessions.append(session_id, {
            "symptoms": symptoms, "syndrome": syndrome.name, "trace_id": trace_id,
        })

        resp = ConsultResponse(
            reply=reply,
            ask_more=ask_more,
            constitution=constitution,
            syndrome=syndrome,
            formulas=formulas,
            suggestions=suggestions,
            partial=partial,
            disclaimer=DISCLAIMER,
            trace_id=trace_id,
            session_id=session_id,
        )
        # ── S7 full 模式：生成辨证报告（T5，内部实现，平台无现成端点）──
        if req.mode == "full":
            try:
                resp.report_id = await generate_report(resp, trace_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("[orchestrator] generate_report failed: %s", e)
        await self._emit_metering(tenant_id, req, _t0, trace_id, resp, code=0)

        # ── 活态化 B · 回路三（业务实证加权）归因钩子 ──
        # 把 consult 返回实体（方剂/证候）经 kg_client.resolve 解析成 kg_id，
        # 落 consult_attribution 表，作为「业务实证使用信号」数据源。
        # 背景任务触发，零侵入、best-effort，绝不阻断主响应。
        try:
            import asyncio
            asyncio.create_task(self._record_attribution(tenant_id, req, resp, trace_id))
        except RuntimeError:
            pass
        return resp

    async def _record_attribution(self, tenant_id, req, resp, trace_id):
        """回路三归因：consult 成功返回实体落 consult_attribution 表（best-effort）。

        非 partial 视为弱采纳（adopted=True）。解析失败/8601 不可达则跳过该行，
        任何异常都不上抛（不污染主链路）。
        """
        try:
            from qihuang_platform.db.config import SessionLocal
            from qihuang_platform.db.models import ConsultAttribution
            from qihuang_platform.living.kg_write_client import kg_client

            names: list = []
            for f in (resp.formulas or []):
                nm = getattr(f, "name", None)
                if nm:
                    names.append(("formula", nm))
            syn = getattr(resp, "syndrome", None)
            syn_name = getattr(syn, "name", None) if syn else None
            if syn_name and syn_name not in ("辨证资料不足", None):
                names.append(("syndrome", syn_name))
            if not names:
                return

            db = SessionLocal()
            try:
                for etype, ename in names:
                    res = await kg_client.resolve(ename)
                    matches = (res or {}).get("matches") or []
                    label = "Formula" if etype == "formula" else "Syndrome"
                    exact = [m for m in matches if label in (m.get("labels") or [])]
                    chosen = exact[0] if exact else (matches[0] if matches else None)
                    kg_id = chosen.get("kg_id") if chosen else None
                    if not kg_id:
                        continue
                    db.add(ConsultAttribution(
                        tenant_id=tenant_id,
                        store_id=getattr(req, "store_id", None),
                        kg_id=str(kg_id),
                        entity_name=ename,
                        entity_type=etype,
                        adopted=not resp.partial,
                        trace_id=trace_id,
                        session_id=getattr(resp, "session_id", None),
                    ))
                db.commit()
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("[orchestrator] attribution record failed: %s", e)

    async def _emit_metering(self, tenant_id, req, t0, trace_id, resp, code):
        """计费埋点（T6）：业务成功执行后记录一次调用；异常不阻断主流程。"""
        try:
            latency_ms = (time.monotonic() - t0) * 1000
            await record_call(
                tenant_id=tenant_id,
                store_id=req.store_id,
                code=code,
                partial=resp.partial,
                latency_ms=latency_ms,
                trace_id=trace_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[orchestrator] metering emit failed: %s", e)

    @staticmethod
    def _assemble(
        constitution: Optional[Constitution],
        syndrome: Optional[Syndrome],
        formulas: list,
        suggestions: list,
        partial: bool,
    ) -> str:
        parts: list[str] = []
        if constitution and constitution.type:
            parts.append(f"【体质辨识】{constitution.type}：{constitution.desc or ''}".strip())
        if syndrome and syndrome.name:
            parts.append(f"【辨证倾向】{syndrome.name}（置信度：{syndrome.confidence or '未知'}）")
        if formulas:
            fl = "；".join(
                f"{f.name}（组成：{','.join(f.items)}）" + (f" 注：{f.note}" if f.note else "")
                for f in formulas
                if f.name
            )
            parts.append(f"【推荐方剂】{fl}")
        else:
            parts.append("【推荐方剂】暂未匹配到对应方剂库条目，建议以生活调理为主。")
        if suggestions:
            sl = "；".join(suggestions)
            parts.append(f"【调理建议】{sl}")
        if partial:
            parts.append("（当前信息有限，结果为辅助参考，补充舌脉后可获得更精准辨证。）")
        return "\n".join(parts)
