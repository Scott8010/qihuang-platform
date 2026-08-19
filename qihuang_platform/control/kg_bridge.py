"""
知识审核回流桥：审核通过的知识条目 → 回写 Neo4j 图谱。

稳定性原则（绝对稳定，洋葱式）：
- 懒加载 neo4j 驱动：无驱动时 import 失败仅告警，不影响审核主流程。
- 所有回写异常被隔离：审核状态更新提交后，回写失败仅记日志，绝不回滚审核。
- 存量迁移数据（content._migrated=True）不触发回写（当年已写入过，防重复/覆盖）。
- 仅对增量项（PENDING→approve 的新知识）按标准 content 结构 MERGE 进图谱。

复用 8601 图谱现有标签（Herb/Syndrome/Formula/Disease/Drug），与 8601 同 Neo4j 实例。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("kg_bridge")

# 实体类型 → Neo4j Label 映射（复用 8601 图谱现有标签）
ENTITY_LABEL_MAP = {
    "herb": "Herb",
    "syndrome": "Syndrome",
    "formula": "Formula",
    "disease": "Disease",
    "drug": "Drug",
}

_NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
_NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "qihuang123")
_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase  # 懒加载：无驱动时只在调用时抛错
        _driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASS))
    return _driver


def is_migrated(content) -> bool:
    """存量迁移数据不回写。"""
    if not isinstance(content, dict):
        return False
    return bool(content.get("_migrated"))


def write_review_to_kg(content, item_type: str = None) -> dict:
    """把审核通过的知识条目 MERGE 进 Neo4j。

    content 标准结构（增量项）：
      {
        "entity_name": "麻黄汤",
        "entity_type": "formula",   # herb/syndrome/formula/disease/drug
        "props": {...其他属性...},
      }
    返回 {"ok": bool, "detail": str}
    """
    try:
        if not isinstance(content, dict):
            return {"ok": False, "detail": "content 非字典，跳过回写"}

        if is_migrated(content):
            return {"ok": True, "detail": "存量迁移项，跳过回写"}

        name = content.get("entity_name") or content.get("name")
        etype = content.get("entity_type") or content.get("type")
        if not name or not etype:
            return {"ok": False, "detail": "缺少 entity_name/entity_type，跳过回写"}

        # 最后一关（P1 加固 2026-08-20）：名称含测试/占位关键词绝不允许写库
        _DIRTY_KW = ("测试", "E2E", "test", "Test", "TEST", "占位", "dummy", "Dummy")
        if any(kw in str(name) for kw in _DIRTY_KW):
            return {"ok": False, "detail": f"名称含测试/占位关键词({name})，拒绝回写"}

        label = ENTITY_LABEL_MAP.get(str(etype).lower())
        if not label:
            return {"ok": False, "detail": f"未知 entity_type={etype}，跳过回写"}

        props = dict(content.get("props") or {})
        props["reviewed"] = True
        props["source"] = "kg_review"
        props["updated_by"] = "kg_bridge"

        driver = _get_driver()
        with driver.session() as s:
            s.run(
                f"MERGE (n:{label} {{name:$name}}) SET n += $props",
                name=name, props=props,
            )
        logger.info("kg_bridge: MERGEd %s %s into Neo4j", label, name)
        return {"ok": True, "detail": f"MERGEd {label}:{name}"}
    except Exception as e:
        logger.error("kg_bridge 回写失败(已隔离，不影响审核): %s", e)
        return {"ok": False, "detail": f"回写异常已隔离: {e}"}
