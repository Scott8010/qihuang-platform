"""
crawler/sources · 可插拔数据源

- RawEntry：单条原始语料（name + text + url + meta）。
- SourceAdapter（抽象）：fetch(limit) -> List[RawEntry]。
- StaticCorpusAdapter：本地/测试语料（确定性、可离线、用于单测与 demo）。
- HttpPageAdapter：真实抓取公开中医典籍/百科（默认 allow_network=False，
  防止误触发外网请求；显式 allow_network=True 才发请求，且带基础限速）。
- SOURCES 注册表：列出可爬的公开来源（URL + 解析器类型），作为扩展点。

⚠️ 真实抓取请遵守目标站点 robots.txt 与 ToS；本适配器仅做基础限速与
  通用正文抽取，站点级精细解析请按需扩展 parser。
"""
import os
import re
import time
import urllib.request
from abc import ABC, abstractmethod
from urllib.parse import urlsplit, urlunsplit, quote
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_USER_AGENT = "QihuangCrawler/0.1 (+https://yshealth.com.cn; educational)"


@dataclass
class RawEntry:
    name: str
    text: str
    url: str = ""
    meta: Dict[str, str] = field(default_factory=dict)


class SourceAdapter(ABC):
    key: str = "abstract"

    @abstractmethod
    def fetch(self, limit: Optional[int] = None, allow_network: bool = False) -> List[RawEntry]:
        ...


class StaticCorpusAdapter(SourceAdapter):
    """本地/测试语料适配器：从预置条目取数，确定性、可离线。"""

    key = "static"

    def __init__(self, key: str, entries: List[RawEntry]):
        self.key = key
        self._entries = entries

    def fetch(self, limit: Optional[int] = None, allow_network: bool = False) -> List[RawEntry]:
        items = self._entries
        if limit is not None:
            items = items[:limit]
        return list(items)


class HttpPageAdapter(SourceAdapter):
    """公开网页抓取适配器（默认关闭，需显式 allow_network=True）。

    通用正文抽取：拉取 HTML → 去标签 → 按段落/列表切分 → 每段作为一个 RawEntry
    （首行作为 name 候选）。站点级精细解析请扩展 parser 后在此分发。
    """

    key = "http"

    def __init__(self, key: str, seed_urls: List[str], min_block_len: int = 30):
        self.key = key
        self.seed_urls = seed_urls
        self.min_block_len = min_block_len

    @staticmethod
    def _fetch_html(url: str, timeout: int = 15) -> str:
        # 对非 ASCII 路径/查询做百分号编码（支持中文词条 URL，如百度百科词条）
        parts = urlsplit(url)
        path = quote(parts.path, safe="/")
        query = quote(parts.query, safe="=&")
        url = urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="ignore")

    @staticmethod
    def _strip_tags(html: str) -> str:
        html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
        html = re.sub(r"<[^>]+>", "\n", html)
        html = re.sub(r"&nbsp;", " ", html)
        html = re.sub(r"&[a-z]+;", " ", html)
        html = re.sub(r"[ \t]+", " ", html)
        html = re.sub(r"\n\s*\n+", "\n", html)
        return html.strip()

    def _html_to_entries(self, html: str, url: str) -> List[RawEntry]:
        text = self._strip_tags(html)
        blocks = [b.strip() for b in re.split(r"\n+", text) if len(b.strip()) >= self.min_block_len]
        out: List[RawEntry] = []
        for b in blocks:
            lines = [l.strip() for l in b.split("\n") if l.strip()]
            name = lines[0][:40] if lines else b[:40]
            out.append(RawEntry(name=name, text=b, url=url, meta={"source": self.key}))
        return out

    def fetch(self, limit: Optional[int] = None, allow_network: bool = False) -> List[RawEntry]:
        if not allow_network:
            # 默认不联网，避免误触发外网请求
            return []
        out: List[RawEntry] = []
        for url in self.seed_urls:
            try:
                html = self._fetch_html(url)
                out.extend(self._html_to_entries(html, url))
            except Exception as e:  # 单源失败不中断其余
                print(f"[crawler] 抓取失败 {url}: {e}")
            time.sleep(1.0)  # 基础限速：1 req/s
        if limit is not None:
            out = out[:limit]
        return out


# ───────────────────────── 数据源注册表 ─────────────────────────
_DEMO_ENTRIES = [
    RawEntry(name="人参", text="性味：甘、微苦，微温。归经：脾、肺、心。功效：大补元气，复脉固脱，补脾益肺，生津养血，安神益智。主治：体虚欲脱，脾虚食少，肺虚喘咳。", url="demo://herb/renshen"),
    RawEntry(name="六味地黄丸", text="方剂组成：熟地黄、山茱萸、山药、泽泻、牡丹皮、茯苓。方解：三阴并补，熟地滋肾阴为君，山茱萸养肝，山药健脾。用法：水煎服或丸服。", url="demo://formula/liuwei"),
    RawEntry(name="风寒感冒", text="疾病诊断：风寒感冒。病因：外感风寒。临床表现：恶寒重、发热轻、无汗、头痛身痛、鼻塞流清涕、舌苔薄白、脉浮紧。", url="demo://disease/ganmao"),
    RawEntry(name="脾胃气虚证", text="证候分析：证属脾胃气虚。辨证：食欲不振，腹胀便溏，神疲乏力，舌质淡、苔薄白，脉象细弱。治法：健脾益气。", url="demo://syndrome/piqi"),
    RawEntry(name="感冒灵颗粒", text="国药准字Z4402xxxx。中成药制剂。规格：每袋10克。适应症：解热镇痛，用于感冒引起的头痛、发热、鼻塞。不良反应：偶见皮疹。", url="demo://drug/ganmaoling"),
]

SOURCES: Dict[str, SourceAdapter] = {
    "static-demo": StaticCorpusAdapter("static-demo", _DEMO_ENTRIES),
    # ── 真实外网源（部署网可达、含真实中医正文；抓取需 allow_network=True）──
    # 百度百科·中医条目：沙箱+生产均可达、静态 HTML 含真实正文（归经/炮制/证候等关键词命中）
    "tcm-encyclopedia": HttpPageAdapter(
        "tcm-encyclopedia",
        seed_urls=["https://baike.baidu.com/item/中药材"],
    ),
    # 百度百科·多条目覆盖 5 类（herb/formula/disease/syndrome/drug）
    "baike-tcm": HttpPageAdapter(
        "baike-tcm",
        seed_urls=[
            # herb 中药/药材
            "https://baike.baidu.com/item/中药材",
            "https://baike.baidu.com/item/人参",
            "https://baike.baidu.com/item/当归",
            "https://baike.baidu.com/item/黄芪",
            "https://baike.baidu.com/item/甘草",
            "https://baike.baidu.com/item/白术",
            # formula 方剂
            "https://baike.baidu.com/item/六味地黄丸",
            "https://baike.baidu.com/item/桂枝汤",
            "https://baike.baidu.com/item/四君子汤",
            "https://baike.baidu.com/item/补中益气汤",
            # disease 疾病
            "https://baike.baidu.com/item/感冒",
            "https://baike.baidu.com/item/咳嗽",
            "https://baike.baidu.com/item/高血压",
            "https://baike.baidu.com/item/糖尿病",
            # syndrome 证候
            "https://baike.baidu.com/item/脾胃虚弱",
            "https://baike.baidu.com/item/肝肾阴虚",
            "https://baike.baidu.com/item/气血两虚",
            # drug 成药
            "https://baike.baidu.com/item/感冒灵颗粒",
            "https://baike.baidu.com/item/板蓝根颗粒",
            "https://baike.baidu.com/item/复方甘草片",
        ],
    ),
    # ── 扩展点（可达但当前正文受限，保留待深链/API 接入）──
    # ctext：可达，但是哲学库 TOC 页、无中医正文 → 低产
    "ctext": HttpPageAdapter("ctext", seed_urls=["https://ctext.org/shang-han-lun/zh"]),
    # jicheng：可达，但 JS 渲染、静态 HTML 无书目链接 → 低产
    "jicheng": HttpPageAdapter("jicheng", seed_urls=["https://jicheng.tw/tcm/"]),
}

# ── 合规登记（2026-08-20 实测，部署网=沙箱+生产）──
#   ✅ baike-tcm / tcm-encyclopedia：百度百科，可达+真实正文 → 真爬
#   ⚠️ ctext / jicheng：可达但无可用正文 → 扩展点（低产）
#   ❌ shidianguji：robots.txt `Disallow: /` 全站禁爬 → 不接入
#   ❌ cintcm / tcmip：需登录/结构化库 + 出网白名单拦截 → 待人工授权
#   ❌ wikisource / zysj：出网白名单拦截（超时）→ 待放开后接入


def get_source(key: str) -> Optional[SourceAdapter]:
    return SOURCES.get(key)


def list_sources() -> List[str]:
    return list(SOURCES.keys())
