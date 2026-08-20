"""
crawler/pipeline · 摄入管线（分类 → 落 KgReviewItem 审核队列）

与 control/router.py POST /kg/review/ingest 同款落库逻辑（status=PENDING），
但由后端模块直接同进程写入，不走 HTTP 内部密钥。
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import KgReviewItem

from .classify import Classification, classify_entry
from .sources import RawEntry, get_source

_DEFAULT_TENANT = os.environ.get("QH_DEFAULT_TENANT", "tenant_default")

# 脏词：与 control/router.py _is_dirty_kg_content 同款拦截
_DIRTY = ("测试", "E2E", "test", "Test", "TEST", "占位", "dummy", "Dummy")


def _is_dirty(text: str) -> bool:
    return any(kw in str(text) for kw in _DIRTY)


def ingest_entry(
    session,
    raw: RawEntry,
    source_key: str,
    reviewer_role: str = "XZ",
    min_confidence: float = 0.2,
) -> Dict[str, Any]:
    """单条语料：分类 → 落 KgReviewItem。返回摄入结果字典。"""
    cls: Classification = classify_entry(raw.name, raw.text)
    if cls.entity_type == "unknown" or cls.confidence < min_confidence:
        return {
            "ingested": False,
            "reason": f"低置信/未归类(conf={cls.confidence}, type={cls.entity_type})",
            "classification": cls,
        }

    name = (raw.name or (raw.text or "")[:40]).strip()
    src_tag = f"crawler:{source_key}"
    if _is_dirty(name) or _is_dirty(src_tag):
        return {"ingested": False, "reason": "脏数据(测试/占位关键词)", "classification": cls}

    content = {
        "entity_name": name,
        "entity_type": cls.entity_type,
        "source": source_key,
        "url": raw.url,
        "raw_text": raw.text,
        "classify_rationale": cls.rationale,
        "_src": src_tag,
    }
    item = KgReviewItem(
        tenant_id=_DEFAULT_TENANT,
        item_type=cls.entity_type,
        content=content,
        confidence=cls.confidence,
        status="PENDING",
        reviewer_role=reviewer_role,
    )
    session.add(item)
    session.flush()
    return {
        "ingested": True,
        "item_id": item.id,
        "classification": cls,
    }


@dataclass
class CrawlReport:
    source_key: str
    total: int = 0
    ingested: int = 0
    skipped: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_key": self.source_key,
            "total": self.total,
            "ingested": self.ingested,
            "skipped": self.skipped,
            "by_type": self.by_type,
            "ids": self.ids,
        }


def run_crawl(
    source_key: str,
    limit: Optional[int] = None,
    allow_network: bool = False,
    session=None,
    reviewer_role: str = "XZ",
    min_confidence: float = 0.2,
    commit: bool = True,
) -> CrawlReport:
    """跑一次爬虫摄入。

    source_key：SOURCES 注册表键（如 static-demo / tcm-encyclopedia）。
    allow_network：真实抓取需 True（默认 False，HttpPageAdapter 不联网）。
    返回 CrawlReport（按类统计 + 摄入 id 列表）。
    """
    src = get_source(source_key)
    if src is None:
        raise ValueError(f"未知数据源: {source_key}（可用: {', '.join(__import__('qihuang_platform.control.crawler.sources', fromlist=['list_sources']).list_sources())}）")

    raws = src.fetch(limit=limit, allow_network=allow_network)
    own = session is None
    if own:
        session = SessionLocal()
    try:
        rep = CrawlReport(source_key=source_key, total=len(raws))
        for raw in raws:
            res = ingest_entry(session, raw, source_key, reviewer_role, min_confidence)
            if res["ingested"]:
                rep.ingested += 1
                rep.ids.append(res["item_id"])
                t = res["classification"].entity_type
                rep.by_type[t] = rep.by_type.get(t, 0) + 1
            else:
                rep.skipped += 1
        if commit:
            session.commit()
        return rep
    finally:
        if own:
            session.close()
