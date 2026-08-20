"""
crawler · 知识图谱摄入爬虫（需求7 图谱治理 Stage B）

职责：把外部语料（公开中医典籍/百科等）抓取、解析、归类到固定实体类型，
再摄入 KgReviewItem 审核队列（与 /kg/review/ingest 同款落库逻辑）。

设计要点（对齐既有框架）：
  - 分类标签固化 5 类：herb / syndrome / formula / disease / drug
    （与 control/kg_bridge.py ENTITY_LABEL_MAP、KgReviewItem 审核回流桥一致）。
  - 摄入通道复用 KgReviewItem（status=PENDING），不走 HTTP 内部密钥，
    直接同进程落库，最稳。
  - 脏数据防线：content 必含 entity_name 且不含 测试/test/占位/dummy
    （control/router.py _is_dirty_kg_content 同款校验），否则拒收。
  - 数据源可插拔：StaticCorpusAdapter（测试/本地语料）＋ HttpPageAdapter（真实抓取，
    默认 allow_network=False 防止误触发外网请求）。

典型用法：
  from qihuang_platform.control.crawler.pipeline import run_crawl
  report = run_crawl("static-demo", limit=10)   # 本地语料
  report = run_crawl("tcm-encyclopedia", allow_network=True)  # 真实抓取
"""
from .classify import CANONICAL_TYPES, classify_entry, Classification
from .sources import (
    RawEntry,
    SourceAdapter,
    StaticCorpusAdapter,
    HttpPageAdapter,
    get_source,
    list_sources,
)
from .pipeline import ingest_entry, run_crawl, CrawlReport

__all__ = [
    "CANONICAL_TYPES",
    "classify_entry",
    "Classification",
    "RawEntry",
    "SourceAdapter",
    "StaticCorpusAdapter",
    "HttpPageAdapter",
    "get_source",
    "list_sources",
    "ingest_entry",
    "run_crawl",
    "CrawlReport",
]
