"""
tests/test_crawler · 爬虫摄入分类管线单测

验证：5 类规则分类正确、摄入落 KgReviewItem(PENDING)、脏数据/未归类被拒。
依赖 conftest 的 client fixture 完成测试库建表（SQLite，FK 不强制）。
"""
import pytest

from qihuang_platform.control.crawler import classify_entry, run_crawl, ingest_entry
from qihuang_platform.control.crawler.sources import RawEntry
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import KgReviewItem


# ───────────────────── 纯分类（不依赖 DB） ─────────────────────
def test_classify_five_types():
    cases = {
        "herb": "性味：甘温。归经：脾肺。功效：大补元气，主治脾虚食少。",
        "formula": "方剂组成：熟地、山茱萸。君药为熟地，水煎服，方解三阴并补。",
        "syndrome": "证候分析：证属脾胃气虚，辨证食欲不振，舌苔薄白，脉象细弱。",
        "disease": "疾病诊断：风寒感冒，病因外感风寒，临床表现恶寒发热、鼻塞。",
        "drug": "国药准字Z4402xxxx，中成药制剂，适应症感冒头痛，不良反应偶见皮疹。",
    }
    for expect, text in cases.items():
        cls = classify_entry(text=text)
        assert cls.entity_type == expect, f"期望 {expect}，实得 {cls.entity_type}（{cls.rationale}）"
        assert cls.confidence > 0, "置信度应 > 0"


def test_classify_unknown():
    cls = classify_entry(text="今天天气晴好，我们去公园散步放松一下。")
    assert cls.entity_type == "unknown"
    assert cls.confidence == 0.0


# ───────────────────── 摄入管线（需测试库） ─────────────────────
def test_run_crawl_static_demo(client):
    session = SessionLocal()
    try:
        rep = run_crawl("static-demo", session=session, commit=False)
        assert rep.total == 5, rep.to_dict()
        assert rep.ingested == 5, rep.to_dict()
        assert rep.skipped == 0, rep.to_dict()
        assert rep.by_type == {"herb": 1, "formula": 1, "disease": 1, "syndrome": 1, "drug": 1}, rep.by_type

        # 落库检查：KgReviewItem 已 flush，5 条，全 PENDING，content 含 entity_name/entity_type
        rows = session.query(KgReviewItem).all()
        assert len(rows) == 5
        for r in rows:
            assert r.status == "PENDING"
            assert r.content.get("entity_name")
            assert r.content.get("entity_type") in ("herb", "syndrome", "formula", "disease", "drug")
            assert "crawler:" in (r.content.get("_src") or "")
    finally:
        session.close()


def test_dirty_rejected(client):
    session = SessionLocal()
    try:
        res = ingest_entry(
            session,
            RawEntry(name="测试药材条目", text="性味：甘，功效：补虚。"),
            source_key="static-demo",
        )
        assert res["ingested"] is False
        assert "脏" in res["reason"], res
    finally:
        session.close()


def test_unknown_rejected(client):
    session = SessionLocal()
    try:
        res = ingest_entry(
            session,
            RawEntry(name="闲聊", text="今天天气晴好，我们去公园散步放松一下。"),
            source_key="static-demo",
        )
        assert res["ingested"] is False
        assert "未归类" in res["reason"] or "低置信" in res["reason"], res
    finally:
        session.close()
