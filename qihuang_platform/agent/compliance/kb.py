"""
L1 合规知识底座 · 存储与检索抽象

双后端（标准范式：每新建一个横向库都遵循此抽象）：
  - JsonlBackend  本地开发/测试用（无需 Neo4j，落盘 jsonl，可离线验证）
  - Neo4jBackend  生产用：在 8601 图谱中新建独立 label `ComplianceClause`，
                  与中医 Herb/Formula 标签**并列隔离**，通过 kg_id 唯一约束写实。

检索（retrieve）与后端无关：先 load_all 进内存，再做关键词打分召回——
保证 L2 推理在任意后端下都能离线验证。

实体对齐 MVP（item 3）：aligned_entities(text) 按 aligns_to 关键词在文本中桥接
8601 中医/领域标签，返回 [(clause_id, entity)]。全量双向同步（含写回 8601 关系）
留 Phase 3。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from qihuang_platform.agent.compliance.schema import (
    ComplianceClause,
    CATEGORY_LABELS,
    SEVERITY_RED,
    SEVERITY_ORANGE,
    SEVERITY_YELLOW,
)

# 从正则 pattern 中抽取检索触发词（仅取字面短语，跳过含元字符的正则，避免噪声）
_CJK_RE = re.compile(r"[一-鿿]{2,}")
_REGEX_META = re.compile(r"[()\[\]?*+\\{|}.^$]")


def extract_terms(patterns: list[str]) -> list[str]:
    """只取「字面短语」作检索词（正则含元字符则跳过，L0 仍用正则精确判定）。

    避免把正则否定环视里的「时间/阶段/选择」等普通词收成检索噪声。
    """
    terms: list[str] = []
    seen = set()
    for p in patterns:
        if _REGEX_META.search(p):
            continue  # 跳过正则（含元字符），只取字面短语
        if p and p not in seen:
            seen.add(p)
            terms.append(p)
    return terms


def severity_rank(sev: str) -> int:
    return {SEVERITY_RED: 0, SEVERITY_ORANGE: 1, SEVERITY_YELLOW: 2}.get(sev, 9)


class KBBackend:
    """后端接口：load_all / persist。子类实现。"""

    async def load_all(self) -> list[ComplianceClause]:
        raise NotImplementedError

    async def persist(self, clauses: list[ComplianceClause]) -> None:
        raise NotImplementedError


class JsonlBackend(KBBackend):
    def __init__(self, path: str):
        self.path = path

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    async def load_all(self) -> list[ComplianceClause]:
        if not os.path.exists(self.path):
            return []
        out: list[ComplianceClause] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(ComplianceClause(**json.loads(line)))
        return out

    async def persist(self, clauses: list[ComplianceClause]) -> None:
        self._ensure_dir()
        with open(self.path, "w", encoding="utf-8") as f:
            for c in clauses:
                f.write(json.dumps(c.model_dump(), ensure_ascii=False) + "\n")


class Neo4jBackend(KBBackend):
    """生产后端：在 8601 图谱新建 `ComplianceClause` label（与中医标签隔离）。

    懒加载 neo4j 驱动——本机沙箱无 neo4j 时 import 不报错，仅在实际调用时抛出，
    便于 CI/本地测试跳过。
    """

    def __init__(self, uri: str = "bolt://127.0.0.1:7687",
                 user: str = "neo4j", password: str = "qihuang123"):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase  # 懒加载
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    async def ensure_schema(self) -> None:
        """建唯一约束（合规库独立 label）。"""
        driver = self._get_driver()
        with driver.session() as s:
            s.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (n:ComplianceClause) "
                "REQUIRE n.kg_id IS UNIQUE"
            )

    async def load_all(self) -> list[ComplianceClause]:
        driver = self._get_driver()
        out: list[ComplianceClause] = []
        with driver.session() as s:
            recs = s.run(
                "MATCH (n:ComplianceClause) RETURN n LIMIT 10000"
            )
            for r in recs:
                node = r["n"]
                out.append(ComplianceClause(**dict(node)))
        return out

    async def persist(self, clauses: list[ComplianceClause]) -> None:
        driver = self._get_driver()
        await self.ensure_schema()
        with driver.session() as s:
            for c in clauses:
                d = c.model_dump()
                s.run(
                    "MERGE (n:ComplianceClause {kg_id:$kg_id}) "
                    "SET n += $props",
                    kg_id=c.kg_id, props=d,
                )


class ComplianceKB:
    """L1 合规知识底座门面：检索 + 取条 + 对齐。"""

    def __init__(self, backend: KBBackend):
        self.backend = backend
        self._cache: Optional[list[ComplianceClause]] = None

    async def _ensure(self):
        if self._cache is None:
            self._cache = await self.backend.load_all()

    async def reload(self) -> None:
        self._cache = await self.backend.load_all()

    async def all(self) -> list[ComplianceClause]:
        await self._ensure()
        return self._cache or []

    async def count(self) -> int:
        await self._ensure()
        return len(self._cache or [])

    async def get(self, clause_id: str) -> Optional[ComplianceClause]:
        await self._ensure()
        for c in (self._cache or []):
            if c.clause_id == clause_id:
                return c
        return None

    async def seed_from_rules(self, rules: list[dict]) -> int:
        """从规则引擎 RULES 反演权威条款并落库（生成器/再生成用）。"""
        clauses = rules_to_clauses(rules)
        await self.backend.persist(clauses)
        self._cache = clauses
        return len(clauses)

    async def retrieve(self, text: str, top_k: int = 8) -> list[ComplianceClause]:
        """关键词打分召回（与后端无关）。"""
        await self._ensure()
        scored = []
        for c in (self._cache or []):
            s = 0
            for kw in c.keywords:
                if kw and kw in text:
                    s += 2
            if c.category_label and c.category_label in text:
                s += 1
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: (x[0], severity_rank(x[1].severity)), reverse=True)
        return [c for _, c in scored[:top_k]]

    async def aligned_entities(self, text: str) -> list[dict]:
        """实体对齐 MVP：扫描文本命中的 aligns_to 实体，桥接 8601 标签。

        返回 [{clause_id, entity, severity}] —— 上层据此在 8601 中定位中医实体
        （如 何首乌/朱砂 → Herb 节点）做关联展示。全量双向同步留 Phase 3。
        """
        await self._ensure()
        out: list[dict] = []
        for c in (self._cache or []):
            for ent in c.aligns_to:
                if ent and ent in text:
                    out.append({
                        "clause_id": c.clause_id,
                        "entity": ent,
                        "severity": c.severity,
                    })
        return out


# ───────────────────────── 规则 -> 条款 反演 ─────────────────────────
_CATEGORY_DEFAULT_SOURCE = {
    "A": "《广告法》第九条第(三)项（绝对化用语）",
    "B": "《广告法》第十七/二十八条、《医疗广告管理办法》",
    "C": "《医疗机构管理条例》",
    "D": "《广告法》第二十八条（虚假广告）",
    "E": "中医调理类服务安全底线（行业规范）",
    "F": "《广告法》第九条第(八)项（迷信）/ 特殊功效监管",
}

# 实体对齐 MVP：桥接 8601 中医/领域标签的候选实体（子串匹配命中即对齐）
_ALIGN_ENTITIES = (
    "何首乌", "朱砂", "雄黄", "马兜铃", "关木通", "细辛",
    "拔罐", "刮痧", "艾灸", "针灸", "放血",
    "抗癌", "防癌", "治癌", "肿瘤",
    "壮阳", "丰胸", "减肥", "催情", "性功能",
    "排毒", "清宿便", "净化血液",
    "食疗", "药膳", "代茶饮", "膏方",
)


def _extract_source_ref(title: str, category: str) -> str:
    """从标题抽取「《法律》+条款项」完整法条引用（如《广告法》第九条第(三)项）。"""
    m = re.search(r"《[^》]*》[^，。；;（(]*(\([^)]*\))?", title)
    if m:
        return m.group(0).strip()
    return _CATEGORY_DEFAULT_SOURCE.get(category, "")


def rules_to_clauses(rules: list[dict]) -> list[ComplianceClause]:
    """把规则引擎的 RULES 反演为权威合规条款（L1 底座种子）。"""
    clauses: list[ComplianceClause] = []
    for r in rules:
        cat = r.get("category", "A")
        # 从标题剥离「违反《...》」前缀，得到干净要求文案（保留法条溯源到 source_ref）
        title = r.get("title", "")
        content = r.get("suggested_replace", "")
        # 实体对齐 MVP：子串匹配中医/领域实体（桥接 8601 标签）
        aligns = [e for e in _ALIGN_ENTITIES
                  if any(e in p for p in r.get("patterns", []))]
        clauses.append(ComplianceClause.build(
            clause_id=r.get("rule_id", ""),
            title=title,
            content=content,
            source_ref=_extract_source_ref(title, cat),
            category=cat,
            severity=r.get("severity", SEVERITY_ORANGE),
            effective_action=r.get("effective_action", "advise"),
            keywords=extract_terms(r.get("patterns", [])),
            confidence=float(r.get("confidence", 0.9)),
            aligns_to=aligns,
        ))
    return clauses


# 默认种子路径（与代码同目录下的 seed/）
_DEFAULT_SEED = os.path.join(os.path.dirname(__file__), "seed", "compliance_clauses.jsonl")
