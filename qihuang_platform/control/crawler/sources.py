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

from .classify import classify_entry

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

    def __init__(self, key: str, seed_urls: List[str], min_block_len: int = 30,
                 headers: Optional[Dict[str, str]] = None):
        self.key = key
        self.seed_urls = seed_urls
        self.min_block_len = min_block_len
        self.headers = headers or {"User-Agent": _USER_AGENT}

    @staticmethod
    def _fetch_html(url: str, timeout: int = 15, headers: Optional[Dict[str, str]] = None) -> str:
        # 对非 ASCII 路径/查询做百分号编码（支持中文词条 URL，如百度百科/360百科词条）
        parts = urlsplit(url)
        path = quote(parts.path, safe="/")
        query = quote(parts.query, safe="=&")
        url = urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
        req = urllib.request.Request(url, headers=headers or {"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # 兼容服务端 gzip 压缩响应（客户端声明 Accept-Encoding 时部分站点返回 gzip）
            if "gzip" in (resp.headers.get("Content-Encoding") or ""):
                import gzip as _gzip
                data = _gzip.decompress(data)
            charset = resp.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="ignore")

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

    def _html_to_entries(self, html: str, url: str, hints: Optional[List[str]] = None) -> List[RawEntry]:
        text = self._strip_tags(html)
        blocks = [b.strip() for b in re.split(r"\n+", text) if len(b.strip()) >= self.min_block_len]
        out: List[RawEntry] = []
        for b in blocks:
            lines = [l.strip() for l in b.split("\n") if l.strip()]
            name = lines[0][:40] if lines else b[:40]
            meta = {"source": self.key}
            if hints:
                # 页面级先行分类结果注入块级（classify_entry hints 加权 +2）
                meta["hints"] = hints
            out.append(RawEntry(name=name, text=b, url=url, meta=meta))
        return out

    def fetch(self, limit: Optional[int] = None, allow_network: bool = False) -> List[RawEntry]:
        if not allow_network:
            # 默认不联网，避免误触发外网请求
            return []
        out: List[RawEntry] = []
        for url in self.seed_urls:
            try:
                html = self._fetch_html(url, headers=self.headers)
                # 页面级先行分类：整页全文判一次类（百科页正文中后部才出现
                # 性味/归经/组成等强特征，切块后单块关键词不足 → 用页面类
                # 作 hints 提升块级命中率；页面 unknown 则保持现状）
                page_cls = classify_entry(text=self._strip_tags(html))
                hints = [page_cls.entity_type] if page_cls.entity_type != "unknown" else None
                out.extend(self._html_to_entries(html, url, hints=hints))
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
            # ⚠️ 已知百度硬反爬拦截（生产机实测 bot/浏览器UA/cookie/移动版/同义词 全 403）：
            #   咳嗽 / 高血压 / 脾胃虚弱 / 肝肾阴虚 / 气血两虚 / 感冒灵颗粒 / 板蓝根颗粒 / 复方甘草片
            #   → 需开放第二源出口白名单(如 zysj.com)+合规评审，或付费百科API，方能在 crawler 接入。
            #   已验证可爬同义词：糖尿病 → 2型糖尿病（已替换下方种子）。
            "https://baike.baidu.com/item/感冒",
            "https://baike.baidu.com/item/咳嗽",
            "https://baike.baidu.com/item/高血压",
            "https://baike.baidu.com/item/2型糖尿病",
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
    # ── 360 百科·中医条目（2026-08-21 新增第二源，生产实测修正）──
    # 背景：百度百科主源已被生产机 IP 级反爬封禁(全 403)，zysj/zhongyoo 不可达、
    #   39kf 已变质为手游站、wikipedia 受 GFW 封锁。360 百科为国内站、部署网可达、
    #   含真实中医正文（性味/归经/证候/组成等关键词命中）。
    # ⚠️ 2026-08-21 生产实测：/doc/search?word=...&src=index 搜索入口会被 360 概率性
    #   弹验证码(qcaptcha.so.com)，不稳定；但 /doc/{id}-{id}.html 直连词条页
    #   从不被拦、返回完整正文(人参 35KB 实测)。故种子改为"预解析直连 URL"，
    #   不再依赖 search 跳转。已解析 5 个：人参/当归/高血压/糖尿病/咳嗽。
    # 其余 8 个(脾胃虚弱/肝肾阴虚/气血两虚/感冒灵/板蓝根/复方甘草片/六味地黄丸/桂枝汤)
    #   因 search 验证码无法预解析 ID → 由 baike-com(快懂百科) 源覆盖其中 2 个，
    #   剩余 6 个缺口见"第三源待接入"合规登记。
    "baike-360": HttpPageAdapter(
        "baike-360",
        seed_urls=[
            # herb 中药/药材（直连词条页，生产实测可用）
            "https://baike.so.com/doc/1236301-32377083.html",   # 人参
            "https://baike.so.com/doc/5337371-5572810.html",    # 当归
            # disease 疾病（直连词条页，生产实测可用）
            "https://baike.so.com/doc/1784617-1887217.html",    # 高血压
            "https://baike.so.com/doc/30506585-32302042.html",  # 糖尿病
            "https://baike.so.com/doc/5375990-5612102.html",    # 咳嗽
        ],
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Referer": "https://baike.so.com/",
        },
    ),
    # ── 快懂百科·中医条目（2026-08-21 新增第三源，专补 360 search 缺口）──
    # 奇虎系百科(与 360 同门)，/wiki/{词条} 直连词条路径 → 302 到 /wikiid/{id} 词条页。
    # 生产机实测：200、150-600KB 真实正文、零验证码、robots 未禁通用爬虫。
    # 覆盖 360 无法预解析 ID 的 drug/formula 词条：复方甘草片、六味地黄丸。
    # ⚠️ 无词条的词(桂枝汤/四君子汤等方剂、脾胃虚弱等证候)返回 404/聚合页 → 不列入种子。
    "baike-com": HttpPageAdapter(
        "baike-com",
        seed_urls=[
            # 与 360 双源互备的 herb/disease（快懂正文更全，150-600KB）
            "https://www.baike.com/wiki/人参",
            "https://www.baike.com/wiki/当归",
            "https://www.baike.com/wiki/高血压",
            "https://www.baike.com/wiki/糖尿病",
            # drug 成药（360 search 被验证码拦、快懂可直连 → 关键补位）
            "https://www.baike.com/wiki/复方甘草片",
            # formula 方剂（360 search 被验证码拦、快懂可直连 → 关键补位）
            "https://www.baike.com/wiki/六味地黄丸",
        ],
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.baike.com/",
        },
    ),
    # ── 扩展点（可达但当前正文受限，保留待深链/API 接入）──
    # ctext：可达，但是哲学库 TOC 页、无中医正文 → 低产
    "ctext": HttpPageAdapter("ctext", seed_urls=["https://ctext.org/shang-han-lun/zh"]),
    # jicheng：可达，但 JS 渲染、静态 HTML 无书目链接 → 低产
    "jicheng": HttpPageAdapter("jicheng", seed_urls=["https://jicheng.tw/tcm/"]),
}

# ── 合规登记（2026-08-20 实测，2026-08-21 复核+修正，部署网=沙箱+生产）──
#   ✅ baike-tcm / tcm-encyclopedia：百度百科，可达+真实正文 → 真爬
#      ⚠️ 2026-08-21 复查：百度对生产机 IP 已启用反爬封禁(人参/当归/感冒等全 403)，
#         主源当前不可爬，需冷却期 + 礼貌限速(降频/Retry-After)后恢复。库内 151 条安全。
#   ✅ baike-360（2026-08-21 第二源，生产实测修正）：360 百科，国内站可达+真实正文 → 真爬，
#         ⚠️ 修正：/doc/search 入口概率性弹验证码(qcaptcha.so.com) → 种子已改为 5 个
#           预解析直连词条页(/doc/{id}.html)，直连页实测不被拦(人参 35KB)。robots 未全局禁爬。
#   ✅ baike-com（2026-08-21 第三源）：快懂百科(奇虎系)，/wiki/{词条} 直连 → 真爬，
#         生产实测 200/150-600KB 正文/零验证码，覆盖 drug(formula 复方甘草片)+formula(六味地黄丸)
#         等 360 search 无法解析的补位词条。
#   🔲 第三源待接入：脾胃虚弱/肝肾阴虚/气血两虚(syndrome)、感冒灵颗粒/板蓝根颗粒(drug)、
#         桂枝汤(formula) —— 360 search 验证码 + 快懂无词条(404/聚合页) + dayi 搜索 JS 渲染。
#         候选：dayi.org.cn 精细解析 或 权威方剂库(如 药智数据/中成药处方数据库)。
#   ⚠️ ctext / jicheng：可达但无可用正文 → 扩展点（低产）
#   ❌ shidianguji：robots.txt `Disallow: /` 全站禁爬 → 不接入
#   ❌ cintcm / tcmip：需登录/结构化库 + 出网白名单拦截 → 待人工授权
#   ❌ wikisource：出网白名单拦截（超时）→ 待放开后接入
#   ❌ zysj.com.cn：DNS 通但正文页连接失败(源站/WAF 不稳) + 39kf.com 已变质为手游站
#      → 原定第二源候选均不可用语料，已改投 360 百科 + 快懂百科。


def get_source(key: str) -> Optional[SourceAdapter]:
    return SOURCES.get(key)


def list_sources() -> List[str]:
    return list(SOURCES.keys())
