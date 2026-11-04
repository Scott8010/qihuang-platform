"""
内容合规审核 · L2 语义推理引擎（Agent 中台第一个能力的真实内核）

三轨融合（呼应设计文档「L0+L1+L2 分轨」）：
  - L0 硬红线：复用规则引擎精确正则 + 免责语境豁免（deterministic，永远在线，RED 必拦）
  - L1 检索：从合规知识底座（ComplianceClause）按关键词召回相关条款
  - L2 推理：LLM 在 L1 条款语境下做语义判定，产出可解释违规 + 整改建议

融合策略：L0 判定为权威（RED 必拦，不依赖 LLM）；L2 补充 ORANGE/YELLOW 级
语义违规（L0 正则漏判的模糊表述），并给 L0 命中补解释。LLM 不可用 → 自动降级
为仅 L0（数据真实性原则：绝不伪造判定）。

回写：通过 ComplianceStore 钉 material_id（钉业务实体，客观真实）。

本模块不依赖任何外部 HTTP 服务，可本地离线验证（L0 规则从 COMPLIANCE_RULES_PATH 加载）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from qihuang_platform.agent.compliance.kb import ComplianceKB, JsonlBackend
from qihuang_platform.agent.compliance.llm_client import (
    chat as default_llm_chat,
    SYSTEM_PROMPT,
)
from qihuang_platform.agent.compliance.schema import (
    ComplianceClause,
    SEVERITY_RED,
    SEVERITY_ORANGE,
    SEVERITY_YELLOW,
)
from qihuang_platform.agent.clients.vision import vision_analyze
from qihuang_platform.agent.compliance.store import (
    ComplianceStore,
    make_material_id,
    STATE_BLOCKED,
    STATE_REVIEW,
    STATE_PENDING,
    STATE_PASSED,
)

_HERE = os.path.dirname(__file__)
DEFAULT_SEED = os.path.join(_HERE, "seed", "compliance_clauses.jsonl")
DEFAULT_STORE = os.path.join(_HERE, "seed", "materials.jsonl")


def _find_rules_dir() -> str | None:
    """搜索 L0 规则引擎目录，按优先级返回第一个包含 rules.py 的路径。

    搜索顺序：
    1. 环境变量 COMPLIANCE_RULES_PATH（最高优先级）
    2. 本仓库内置 guard/ 目录（随仓库提交，CI 可用）
    3. 项目根目录 hb-compliance-guard/（向后兼容老部署）
    4. 服务器部署路径 /root/qihuang_platform/hb-compliance-guard/
    5. 本地开发路径（兜底）
    """
    env_path = os.getenv("COMPLIANCE_RULES_PATH")
    candidates: list[str] = []
    if env_path:
        candidates.append(env_path)
    candidates.extend([
        os.path.join(_HERE, "guard"),                                          # 仓库内置（CI/新部署）
        os.path.join(_HERE, "..", "..", "..", "hb-compliance-guard"),       # 项目根（旧布局兼容）
        "/root/qihuang_platform/hb-compliance-guard",                           # 服务器旧路径
        r"C:/Users/Administrator/WorkBuddy/HealthBridge/hb-compliance-guard",   # 本地开发
    ])
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "rules.py")):
            return d
    return None


# L0 规则引擎目录（自动搜索；env 覆盖；找不到则 None → 降级模式）
RULES_DIR = _find_rules_dir()

_SEVERITY_RANK = {SEVERITY_RED: 0, SEVERITY_ORANGE: 1, SEVERITY_YELLOW: 2}

# 视觉模型审核提示词：让视觉模型指出图片中与「中医/健康营销合规」相关的可见要素，
# 输出为可读描述（非 JSON），由下游 L0/L1/L2 条款裁决——视觉只负责「看见」。
COMPLIANCE_VISION_PROMPT = (
    "你是内容合规审核助手。请仔细审视这张门店经营图片（海报/朋友圈配图/直播间截图/商品图等），\n"
    "用中文逐条列出图片中与「健康/医疗营销合规」相关的可见要素，重点识别：\n"
    "1) 是否出现夸大疗效、保证治愈、包治百病等绝对化表述；\n"
    "2) 是否出现疑似医疗广告、处方药、诊疗建议、诊断结论；\n"
    "3) 是否展示执业资质/许可证/专利等证照，及其是否清晰；\n"
    "4) 是否出现违禁词、敏感人物/机构、未核实的数据或对比图；\n"
    "5) 图片文字与产品/服务宣传是否一致。\n"
    "仅描述你「在图中看到」的客观要素，不要下合规结论，不要解释，不要 markdown 代码块。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComplianceEngineL2:
    def __init__(
        self,
        kb: Optional[ComplianceKB] = None,
        store: Optional[ComplianceStore] = None,
        llm_call: Optional[Callable] = None,
    ):
        self.kb = kb or ComplianceKB(JsonlBackend(DEFAULT_SEED))
        self.store = store or ComplianceStore(DEFAULT_STORE)
        self.llm_call = llm_call  # 注入式：测试可替换；缺省用生产 chat（降级链）
        self._rules_mod = None

    # ───────── L0 规则引擎（懒加载） ─────────
    def _load_l0(self):
        if self._rules_mod is None:
            if RULES_DIR is None:
                raise FileNotFoundError(
                    "L0 规则引擎未找到（COMPLIANCE_RULES_PATH 未设置且候选路径均无 rules.py）"
                )
            # engine.py 含 scan_text/judge_state，其顶部 `from rules import ...`
            # 自引用 —— 必须先以 "rules" 为名加载并注册 rules.py，再加载 engine.py，
            # 顺序不可颠倒，否则自导入失败导致 L0 静默降级（所有文本都判「已通过」）。
            import sys
            rules_path = os.path.join(RULES_DIR, "rules.py")
            engine_path = os.path.join(RULES_DIR, "engine.py")
            # 1) 先加载 rules.py 并临时注册为 "rules"
            r_spec = importlib.util.spec_from_file_location("rules", rules_path)
            r_mod = importlib.util.module_from_spec(r_spec)
            sys.modules["rules"] = r_mod
            r_spec.loader.exec_module(r_mod)
            # 2) 再加载 engine.py（此时 from rules import ... 可正常解析）
            e_spec = importlib.util.spec_from_file_location("hb_compliance_engine", engine_path)
            e_mod = importlib.util.module_from_spec(e_spec)
            sys.modules["hb_compliance_engine"] = e_mod
            e_spec.loader.exec_module(e_mod)
            # 3) 清理 sys.modules：engine.py 的 from rules import 已在加载时绑定名称，
            #    运行时不再依赖 sys.modules["rules"]；移除避免全局命名空间污染
            sys.modules.pop("rules", None)
            sys.modules.pop("hb_compliance_engine", None)
            self._rules_mod = e_mod
        return self._rules_mod

    # ───────── 主分析 ─────────
    async def analyze(
        self,
        text: str,
        material_type: str,
        port: str,
        institution_id: str,
        image: str | None = None,
        video: str | None = None,
        material_key: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        # 视觉模型（图片审核）：把图片交给视觉端点识别违规要素，作为辅助文本并入审核；
        # 数据真实性原则——视觉只负责「看见」，最终判定仍由 L0/L1/L2 条款裁决。
        analysis_text = text
        vision_result = None
        if image:
            loop = asyncio.get_running_loop()
            vision_result = await loop.run_in_executor(
                None, vision_analyze, image, COMPLIANCE_VISION_PROMPT,
                "COMPLIANCE_VISION", "GEO_VISION",
            )
            if vision_result.get("text"):
                analysis_text = (
                    text + "\n\n[图片视觉要素（视觉模型识别，仅供参考，最终判定以合规条款为准）]\n"
                    + vision_result["text"]
                )
        elif video:
            vision_result = {"provided": True, "mode": "video_unsupported",
                             "note": "视频逐帧解析待接入（当前视觉客户端支持单图），已按文本审核；"
                                     "如需视频审核请先抽帧为图片。"}

        # L0
        l0_ok = True
        try:
            rules = self._load_l0()
            l0_hits = rules.scan_text(analysis_text)
            judge = rules.judge_state
        except Exception:
            l0_hits = []
            judge = self._judge_fallback
            l0_ok = False

        # L1
        clauses = await self.kb.retrieve(analysis_text, top_k=8)
        clause_map = {c.clause_id: c for c in clauses}

        # L2
        l2_violations = await self._reason(analysis_text, clauses)

        # 融合
        hits = self._merge(l0_hits, l2_violations, clause_map)
        state = judge(hits)
        material_id = make_material_id(text, institution_id, material_key)

        body = {
            "material_id": material_id,
            "institution_id": institution_id,
            "text": text,
            "port": port,
            "material_type": material_type,
            "state": state,
            "hit_count": len(hits),
            "hits": hits,
            "scanned_at": _now_iso(),
        }
        if vision_result is not None:
            body["vision"] = vision_result
        if persist:
            self.store.upsert(material_id, body)
        # L1 实体对齐（MVP）：桥接 8601 中医标签
        body["aligned_entities"] = await self.kb.aligned_entities(text)
        # L0 规则缺失时如实标记降级（数据真实性原则：不伪造判定）
        if not l0_ok:
            body["degraded"] = True
            body["degraded_reason"] = "L0 规则引擎未加载（COMPLIANCE_RULES_PATH 缺失）"
        return body

    # ───────── L2 推理 ─────────
    async def _reason(self, text: str, clauses: list[ComplianceClause]) -> list[dict]:
        if not clauses:
            return []
        llm = self.llm_call or default_llm_chat
        ctx = "\n".join(
            f"[{c.clause_id}|{c.severity}|{c.source_ref}] {c.title}" for c in clauses
        )
        prompt = (
            f"【合规条款库】\n{ctx}\n\n"
            f"【待审文本】\n{text}\n\n"
            "请判定文本违反了哪些条款，仅输出与条款库匹配的判定，返回 JSON。"
        )
        try:
            if asyncio.iscoroutinefunction(llm):
                res = await llm(prompt, SYSTEM_PROMPT)
            else:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None, lambda: llm(prompt, SYSTEM_PROMPT)
                )
        except Exception:
            return []
        if not res:
            return []
        return res.get("violations", [])

    # ───────── 三轨融合 ─────────
    def _merge(self, l0_hits: list[dict], l2_violations: list[dict],
               clause_map: dict) -> list[dict]:
        merged: list[dict] = []
        covered: set[str] = set()

        # L0 权威命中
        for h in l0_hits:
            cid = h.get("rule_id") or h.get("clause_id")
            covered.add(cid)
            merged.append({
                "clause_id": cid,
                "severity": h.get("severity"),
                "confidence": h.get("confidence", 0.95),
                "title": h.get("title", ""),
                "source_ref": clause_map.get(cid, ComplianceClause.build(cid, "")).source_ref
                if cid in clause_map else "",
                "suggested_replace": h.get("suggested_replace", ""),
                "layer": "L0",
                "snippet": h.get("snippet", ""),
            })

        # L2 语义命中（补充 L0 未覆盖的 ORANGE/YELLOW）
        for v in l2_violations:
            cid = v.get("clause_id")
            if not cid or cid in covered:
                continue
            c = clause_map.get(cid)
            if c is None:
                continue
            merged.append({
                "clause_id": cid,
                "severity": v.get("severity", c.severity),
                "confidence": float(v.get("confidence", c.confidence)),
                "title": c.title,
                "source_ref": c.source_ref,
                "suggested_replace": v.get("suggested_replace") or c.content or c.title,
                "layer": "L2",
                "explanation": v.get("explanation", ""),
            })
            covered.add(cid)

        merged.sort(key=lambda x: _SEVERITY_RANK.get(x["severity"], 9))
        return merged

    @staticmethod
    def _judge_fallback(hits: list[dict]) -> str:
        if not hits:
            return STATE_PASSED
        sev = {h.get("severity") for h in hits}
        if SEVERITY_RED in sev:
            return STATE_BLOCKED
        if SEVERITY_ORANGE in sev:
            return STATE_REVIEW
        return STATE_PENDING

    # ───────── 回写 / 看板 ─────────
    async def feedback(self, material_id: str, decision: str, action_taken: str,
                       note: str | None, operator: str | None) -> dict | None:
        return self.store.feedback(material_id, decision, action_taken, note, operator)

    async def dashboard(self, institution_id: str | None = None,
                        port: str | None = None) -> dict:
        return self.store.dashboard(institution_id, port)


# 生产单例（router 使用；llm_call 默认走降级链）
compliance_engine = ComplianceEngineL2()
