"""
命理运程 Agent · 内核引擎（fortune Agent 的真实能力）

设计原则（对齐 Agent 中台控制面第二面 + 与 compliance 同构）：
  - 纯规则引擎，不依赖任何外部 HTTP 服务，可离线验证；
  - 不碰 Neo4j / 中医知识库（隔离红线），结果经 store 落盘到独立 JSONL；
  - 数据回写钉业务实体（material_key→FOR-XXXX 幂等），客观真实可追溯。

能力构成（玄学大类之「看人」fortune，与 geo_fengshui「看空间」并列）：
  - bazi：四柱排盘 → 五行 / 十神 / 身强身弱 / 喜用神（接受四柱直输，v1 不依赖公历→干支换算）
  - liuyao：六爻起卦（铜钱 / 时间）→ 本卦 / 变卦 / 动爻 / 趣味解析
  - daily：每日运程日签（五行穿衣 / 五行茶 / 宜忌 / 吉时方位 / 生肖冲合 / 幸运色数）
  - report：年运报告（八字 + 流年）
  - geo_fengshui：风水堪舆（看空间）· 坐向(罗盘/24山) + GPS → 宅卦/八宅吉凶方/九宫/峦头

免责：所有输出均为传统文化娱乐参考，不作医疗 / 投资 / 人生决策依据。
"""
from __future__ import annotations

import datetime
import math
import os
import random
import re
import urllib.request
from typing import Dict, List, Optional

# ═══════════════════════════════════════════════════════════════
# 基础数据
# ═══════════════════════════════════════════════════════════════
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
GAN_WX = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土",
          "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
GAN_YIN = {"甲": True, "丙": True, "戊": True, "庚": True, "壬": True,   # 阳干
           "乙": False, "丁": False, "己": False, "辛": False, "癸": False}  # 阴干
ZHI_WX = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
          "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}
# 地支本气（用于五行统计 / 取根）
ZHI_BEN = ZHI_WX
ZHI_HIDDEN = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"], "卯": ["乙"],
    "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"], "午": ["丁", "己"],
    "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"], "酉": ["辛"],
    "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"],
}
# 地支本气天干（用于地支十神推算）
ZHI_BEN_GAN = {"子": "癸", "丑": "己", "寅": "甲", "卯": "乙", "辰": "戊", "巳": "丙",
               "午": "丁", "未": "己", "申": "庚", "酉": "辛", "戌": "戊", "亥": "壬"}
WX = ["木", "火", "土", "金", "水"]
# 生：a 生 b
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
# 克：a 克 b
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

WX_COLOR = {
    "金": ["白", "银", "金"], "水": ["黑", "蓝", "藏青"], "木": ["绿", "青"],
    "火": ["红", "紫", "橙"], "土": ["黄", "棕", "米"],
}
WX_TEA = {
    "金": "白茶", "水": "黑茶 / 普洱", "木": "绿茶", "火": "红茶", "土": "黄茶",
}
WX_NUMBER = {"水": [1, 6], "火": [2, 7], "木": [3, 8], "金": [4, 9], "土": [5, 0]}

# ── 排盘辅助数据 ───────────────────────────────────────────────
# 六十甲子纳音（干支 → 纳音名，末字即纳音五行）
_NAYIN_PAIRS = [
    ("甲子", "乙丑", "海中金"), ("丙寅", "丁卯", "炉中火"), ("戊辰", "己巳", "大林木"),
    ("庚午", "辛未", "路旁土"), ("壬申", "癸酉", "剑锋金"), ("甲戌", "乙亥", "山头火"),
    ("丙子", "丁丑", "涧下水"), ("戊寅", "己卯", "城头土"), ("庚辰", "辛巳", "白蜡金"),
    ("壬午", "癸未", "杨柳木"), ("甲申", "乙酉", "泉中水"), ("丙戌", "丁亥", "屋上土"),
    ("戊子", "己丑", "霹雳火"), ("庚寅", "辛卯", "松柏木"), ("壬辰", "癸巳", "长流水"),
    ("甲午", "乙未", "沙中金"), ("丙申", "丁酉", "山下火"), ("戊戌", "己亥", "平地木"),
    ("庚子", "辛丑", "壁上土"), ("壬寅", "癸卯", "金箔金"), ("甲辰", "乙巳", "覆灯火"),
    ("丙午", "丁未", "天河水"), ("戊申", "己酉", "大驿土"), ("庚戌", "辛亥", "钗钏金"),
    ("壬子", "癸丑", "桑柘木"), ("甲寅", "乙卯", "大溪水"), ("丙辰", "丁巳", "沙中土"),
    ("戊午", "己未", "天上火"), ("庚申", "辛酉", "石榴木"), ("壬戌", "癸亥", "大海水"),
]
NAYIN = {g: name for a, b, name in _NAYIN_PAIRS for g in (a, b)}

# 十二长生：五行长生起步地支（土随水，长生在申）
_STAGES = ["长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养"]
_CHANGSHENG_START = {"木": "亥", "火": "寅", "金": "巳", "水": "申", "土": "申"}
CHANGSHENG = {}
for _wx, _start in _CHANGSHENG_START.items():
    _s = ZHI.index(_start)
    CHANGSHENG[_wx] = {ZHI[(_s + i) % 12]: _STAGES[i] for i in range(12)}

# 旬空：60 甲子按旬首定空亡两支
_60 = [GAN[i % 10] + ZHI[i % 12] for i in range(60)]
_XUN_KONG = {
    "甲子": ["戌", "亥"], "甲戌": ["申", "酉"], "甲申": ["午", "未"],
    "甲午": ["辰", "巳"], "甲辰": ["寅", "卯"], "甲寅": ["子", "丑"],
}
XUNKONG = {_60[i]: _XUN_KONG[_60[(i // 10) * 10]] for i in range(60)}

# 八卦（上/下卦三爻，阳=1 阴=0；bit 顺序：初爻..上爻）
TRI_BITS = {"111": "乾", "110": "兑", "101": "离", "100": "震",
            "011": "巽", "010": "坎", "001": "艮", "000": "坤"}
TRI_WX = {"乾": "金", "兑": "金", "离": "火", "震": "木",
          "巽": "木", "坎": "水", "艮": "土", "坤": "土"}
TRI_IDX = {"乾": 0, "兑": 1, "离": 2, "震": 3, "巽": 4, "坎": 5, "艮": 6, "坤": 7}
# King Wen 64 卦名（行=下卦，列=上卦）
HEX_NAMES = [
    ["乾", "夬", "大有", "大壮", "小畜", "需", "大畜", "泰"],
    ["履", "兑", "睽", "归妹", "中孚", "节", "损", "临"],
    ["同人", "革", "离", "丰", "家人", "既济", "贲", "明夷"],
    ["无妄", "随", "噬嗑", "震", "益", "屯", "颐", "复"],
    ["姤", "大过", "鼎", "恒", "巽", "井", "蛊", "升"],
    ["讼", "困", "未济", "解", "涣", "坎", "蒙", "师"],
    ["遁", "咸", "旅", "小过", "渐", "蹇", "艮", "谦"],
    ["否", "萃", "晋", "豫", "观", "比", "剥", "坤"],
]


# 64 卦象义（精简，据《周易》大象/卦义；传统民俗娱乐参考）
_GUA_YIXIANG = {
    "乾": "刚健中正，自强不息，万事开端，宜进取。",
    "夬": "决而能和，果决去小人，防过刚生悔。",
    "大有": "柔得尊位，大有收获，富而守礼为吉。",
    "大壮": "阳刚壮盛，势当大为，忌逞强用壮。",
    "小畜": "小有积蓄，蓄而待发，宜渐进有成。",
    "需": "云上于天，等待时机，守正待时。",
    "大畜": "厚积德学，止而后行，蓄势可成大业。",
    "泰": "天地交泰，通顺安和，诸事顺遂。",
    "履": "履虎尾而慎行，礼以践危，守正无咎。",
    "兑": "喜悦相见，口舌和悦，宜沟通欢聚。",
    "睽": "乖离求同，异中求合，忌固执己见。",
    "归妹": "婚嫁之象，行必有归，守礼为吉。",
    "中孚": "中心诚信，可信及豚鱼，能化险为夷。",
    "节": "节制有度，适可而止，过则生悔。",
    "损": "损下益上，与时偕损，先难而后易。",
    "临": "临下观民，教思无穷，阳气渐长。",
    "同人": "与人和同，会同之道，忌结私党。",
    "革": "顺天应人，破旧立新，变革之时。",
    "离": "光明附丽，日月丽天，宜守正得助。",
    "丰": "丰大光明，盛极当忧，宜修德防满。",
    "家人": "正家之道，女正位内，家和业兴。",
    "既济": "事已成济，守成防变，慎终如始。",
    "贲": "文饰之美，质文相济，尚朴实为本。",
    "明夷": "光明受伤，韬光养晦，忌冒进。",
    "无妄": "不妄为，顺天合道，妄动有灾。",
    "随": "随时而动，从宜适变，择善而从。",
    "噬嗑": "咬合去梗，刑罚除碍，刚柔决之。",
    "震": "震动惊惧，恐惧修省，奋起有为。",
    "益": "损上益下，与时偕益，兴利除弊。",
    "屯": "万物始生，艰难初创，利建侯。",
    "颐": "颐养之道，慎言节食，养正为吉。",
    "复": "一阳来复，生机回复，反复其道。",
    "姤": "不期而遇，阴遇阳，防微杜渐。",
    "大过": "栋桡过甚，非常之事，独立不惧。",
    "鼎": "调和鼎鼐，去故取新，养贤致用。",
    "恒": "恒久之道，立不易方，久于其道。",
    "巽": "顺而入，随风申命，谦逊得行。",
    "井": "养而不穷，井渫可食，养民有常。",
    "蛊": "蛊坏待治，拨乱反正，整饬前愆。",
    "升": "积小成高，地中生木，循序渐进。",
    "讼": "争讼之象，慎争止忿，忌纠缠。",
    "困": "穷困自守，处困求通，忌妄动。",
    "未济": "事未成济，慎终如始，防功亏一篑。",
    "解": "险难消散，舒解宽松，宜赦过宥罪。",
    "涣": "风行水上，涣散而聚，宜涣群聚。",
    "坎": "重险陷中，习坎行险，唯心力可亨。",
    "蒙": "蒙昧启蒙，山下出泉，养正圣功。",
    "师": "兵众之象，容民畜众，用师以正。",
    "遁": "退避保身，天下有山，宜退勿进。",
    "咸": "感应相通，柔上刚下，男女相与。",
    "旅": "行旅在外，明慎用刑，宜安分。",
    "小过": "小者过越，宜下不宜上，守小亨。",
    "渐": "循序渐进，女归吉，稳步登高。",
    "蹇": "蹇难在途，反身修德，利西南。",
    "艮": "止其所止，时止则止，动静不失其时。",
    "谦": "谦尊而光，地中有山，谦亨有终。",
    "否": "天地不交，闭塞不通，宜俭德避难。",
    "萃": "荟萃汇聚，聚以正，戒不虞。",
    "晋": "进长之象，明出地上，柔进上行。",
    "豫": "逸豫和乐，先顺后动，乐极生忧。",
    "观": "观风察俗，省方观民，设教天下。",
    "比": "亲比辅佐，水在地上，择善亲附。",
    "剥": "剥落侵蚀，不利有攸往，顺而止之。",
    "坤": "厚德载物，顺承天，包容安贞。",
}

# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════
def parse_pillars(pillars) -> List[str]:
    """接受 '庚申 丙戌 丁巳 辛丑' 或 ['庚申','丙戌','丁巳','辛丑'] → 四柱字符串列表。"""
    if isinstance(pillars, str):
        pillars = pillars.split()
    if len(pillars) != 4:
        raise ValueError("四柱须为 年柱 月柱 日柱 时柱 共 4 组")
    for p in pillars:
        if len(p) != 2 or p[0] not in GAN or p[1] not in ZHI:
            raise ValueError(f"非法干支：{p}")
    return list(pillars)


def _sheng_wo(wx: str) -> str:
    for k, v in SHENG.items():
        if v == wx:
            return k
    return ""


def _ke_wo(wx: str) -> str:
    for k, v in KE.items():
        if v == wx:
            return k
    return ""


def _tiaohou(month_zhi: str) -> List[str]:
    """调候：依月支寒暖燥湿给喜用五行（传统调候简法，供参考）。"""
    if month_zhi in ("亥", "子", "丑"):
        return ["火"]                       # 寒水局，调候用暖
    if month_zhi in ("巳", "午", "未"):
        return ["水"]                       # 燥热局，调候用润
    if month_zhi in ("寅", "卯", "辰"):
        return ["火"]                       # 春木，调候用火泄秀暖局
    if month_zhi in ("申", "酉", "戌"):
        return ["水"]                       # 秋金，调候用水泄秀润局
    return []


def shishen(day_gan: str, target_gan: str) -> str:
    """十神：以日干为「我」，推 target 天干的关系。"""
    dw, dy = GAN_WX[day_gan], GAN_YIN[day_gan]
    tw, ty = GAN_WX[target_gan], GAN_YIN[target_gan]
    if tw == dw:
        return "比肩" if ty == dy else "劫财"
    if tw == _sheng_wo(dw):
        return "正印" if ty != dy else "偏印"
    if tw == SHENG[dw]:
        return "食神" if ty == dy else "伤官"
    if tw == KE[dw]:
        return "正财" if ty != dy else "偏财"
    if tw == _ke_wo(dw):
        return "正官" if ty != dy else "七杀"
    return "未知"


# ═══════════════════════════════════════════════════════════════
# 干支历换算（公历生日 → 四柱）
# ═══════════════════════════════════════════════════════════════
def _zhi_num(zhi: str) -> int:
    """地支序号 子1…亥12。"""
    return ZHI.index(zhi) + 1


# 寿星公式：12 节（月令起点）在 2000-2099 的世纪常数 C
# 顺序：小寒 / 立春 / 惊蛰 / 清明 / 立夏 / 芒种 / 小暑 / 立秋 / 白露 / 寒露 / 立冬 / 大雪
_SOLAR_C = [5.4055, 3.87, 5.63, 4.81, 5.52, 5.678,
            7.108, 7.5, 7.646, 8.318, 7.438, 7.18]
# 12 节对应的月支（起点）：小寒起丑月 … 大雪起子月
_SOLAR_BRANCH = ["丑", "寅", "卯", "辰", "巳", "午",
                 "未", "申", "酉", "戌", "亥", "子"]


def _solar_jie(year: int, idx: int) -> datetime.date:
    """第 idx 个节（0=小寒, 1=立春 …）在 year 的日期（寿星公式，2000-2099 近似）。"""
    y = year % 100
    day = int(y * 0.2422 + _SOLAR_C[idx]) - (y - 1) // 4
    month = idx + 1                      # 小寒1月、立春2月 …
    return datetime.date(year, month, max(1, min(day, 31)))


def _month_branch(d: datetime.date) -> str:
    """按 12 节 定月支：取「不晚于 d 的最后一个节」所起的月。"""
    anchors = []
    for yy in (d.year - 1, d.year, d.year + 1):
        for i, br in enumerate(_SOLAR_BRANCH):
            anchors.append((_solar_jie(yy, i), br))
    anchors.sort()
    br = "子"
    for dt, b in anchors:
        if dt <= d:
            br = b
        else:
            break
    return br


def _solar_month_seq(d: datetime.date) -> int:
    """节气月序号 寅=1 … 丑=12（梅花易数用）。"""
    return ((_zhi_num(_month_branch(d)) - 3) % 12) + 1


def _wuhu_dun(year_gan: str) -> int:
    """五虎遁：年干 → 寅月（月支序1）天干序号。甲己=丙(2) 乙庚=戊(4) 丙辛=庚(6) 丁壬=壬(8) 戊癸=甲(0)。"""
    return {"甲": 2, "己": 2, "乙": 4, "庚": 4, "丙": 6, "辛": 6,
            "丁": 8, "壬": 8, "戊": 0, "癸": 0}[year_gan]


def _wushu_dun(day_gan: str) -> int:
    """五鼠遁：日干 → 子时（时支序1）天干序号。甲己=甲(0) 乙庚=丙(2) 丙辛=戊(4) 丁壬=庚(6) 戊癸=壬(8)。"""
    return {"甲": 0, "己": 0, "乙": 2, "庚": 2, "丙": 4, "辛": 4,
            "丁": 6, "壬": 6, "戊": 8, "癸": 8}[day_gan]


def _hour_zhi(hour: int) -> str:
    """时辰地支（传统）：子(23-1) 丑(1-3) 寅(3-5) 卯(5-7) 辰(7-9) 巳(9-11)
    午(11-13) 未(13-15) 申(15-17) 酉(17-19) 戌(19-21) 亥(21-23)。"""
    return ZHI[((int(hour) + 1) // 2) % 12]


def year_pillar(d: datetime.date) -> str:
    """年柱：以立春为界切换。"""
    lichun = _solar_jie(d.year, 1)              # 立春 idx=1
    y = d.year if d >= lichun else d.year - 1
    return year_ganzhi(y)


def month_pillar(d: datetime.date) -> str:
    """月柱：节气月支 + 五虎遁定月干。"""
    br = _month_branch(d)
    seq = _solar_month_seq(d)                    # 寅1…丑12（月序）
    stem_idx = (_wuhu_dun(year_pillar(d)[0]) + (seq - 1)) % 10
    return GAN[stem_idx] + br


def hour_pillar(d: datetime.date, hour: int) -> str:
    """时柱：时辰地支 + 五鼠遁定时干。"""
    hz = _hour_zhi(hour)
    seq = _zhi_num(hz)                           # 子1…亥12
    stem_idx = (_wushu_dun(day_ganzhi(d)[0]) + (seq - 1)) % 10
    return GAN[stem_idx] + hz


def _true_solar_datetime(date_str, hour, minute=0, lng: float = 116.40):
    """
    北京时间（UTC+8，标准时对应东经120°）生日 → 真太阳时 datetime。
    真太阳时 = 平太阳时 + 经度时差 + 时差方程(EoT)。
      · 经度时差 = (lng - 120) × 4 分钟（东经为正，越往东越早见到太阳 → 真太阳时越晚）
      · EoT（时差方程，近似）：9.87·sin2B − 7.53·cosB − 1.5·sinB，B=360(N−81)/365（度）
    排盘以真太阳时所定时辰为准（传统命理以当地真太阳时定盘）。
    """
    d = datetime.date.fromisoformat(date_str) if isinstance(date_str, str) else date_str
    dt = datetime.datetime(d.year, d.month, d.day, int(hour), int(minute or 0))
    N = dt.timetuple().tm_yday
    B = math.radians(360.0 * (N - 81) / 365.0)
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)   # 分钟
    delta = (lng - 120.0) * 4.0 + eot
    ts = dt + datetime.timedelta(minutes=delta)
    return ts, round(delta, 1)


def bazi_from_birth(date_str, hour: int = 0, minute: int = 0, lng: float = 116.40) -> str:
    """公历生日（'YYYY-MM-DD' 或 date）→ 四柱 '年 月 日 时'。
    可选 minute / lng：按出生地经度换算真太阳时后再定盘。"""
    ts, _ = _true_solar_datetime(date_str, hour, minute, lng)
    d = ts.date()
    h = ts.hour
    return " ".join([year_pillar(d), month_pillar(d), day_ganzhi(d), hour_pillar(d, h)])


def bazi_profile_from_birth(date_str, hour: int = 0, minute: int = 0, lng: float = 116.40) -> Dict:
    """公历生日直接出命盘（便捷封装），并附真太阳时校正信息。"""
    ts, delta = _true_solar_datetime(date_str, hour, minute, lng)
    prof = bazi_profile(bazi_from_birth(date_str, hour, minute, lng))
    prof["true_solar"] = {
        "input_time": f"{int(hour):02d}:{int(minute or 0):02d}",
        "true_time": f"{ts.hour:02d}:{ts.minute:02d}",
        "delta_min": delta,
        "lng": lng,
        "note": ("已按出生地经度将北京时间换算为真太阳时（传统排盘以真太阳时定盘）。"
                 if abs(delta) >= 1 else
                 "出生地接近东经120°，真太阳时与北京时间基本一致。"),
    }
    return prof


# ═══════════════════════════════════════════════════════════════
# 大运 / 流年（八字延伸，传统民俗娱乐参考）
# ═══════════════════════════════════════════════════════════════
_JIAZI = [GAN[k % 10] + ZHI[k % 12] for k in range(60)]


def _jiazi_index(g: str, z: str) -> int:
    a, b = GAN.index(g), ZHI.index(z)
    for k in range(60):
        if k % 10 == a and k % 12 == b:
            return k
    return 0


def bazi_dayun(pillars, gender: str, birth_date) -> Dict:
    """排大运：阳年男 / 阴年女顺排，阴年男 / 阳年女逆排；起运 = 距最近节气天数 ÷ 3（三日为一岁）。"""
    if gender not in ("男", "女"):
        return {}
    year_gan = pillars[0][0]
    yang = GAN_YIN[year_gan]
    forward = (yang and gender == "男") or ((not yang) and gender == "女")
    mp = pillars[1]
    bd = birth_date if isinstance(birth_date, datetime.date) else datetime.date.fromisoformat(str(birth_date))
    # 12 节锚点（寿星公式），取出生前后最近的一个
    anchors = []
    for yy in (bd.year - 1, bd.year, bd.year + 1):
        for i in range(12):
            anchors.append(_solar_jie(yy, i))
    anchors.sort()
    if forward:
        nxt = min(a for a in anchors if a > bd)
        days = (nxt - bd).days
    else:
        prv = max(a for a in anchors if a < bd)
        days = (bd - prv).days
    start_age = days / 3.0
    months = int(round((days % 3) * 4))        # 一日 ≈ 四个月
    mi = _jiazi_index(mp[0], mp[1])
    dm = pillars[2][0] if len(pillars) > 2 else None   # 日主（我）
    dayun = []
    for n in range(1, 9):
        k = (mi + n) % 60 if forward else (mi - n) % 60
        gz = _JIAZI[k]
        step = {
            "seq": n,
            "ganzhi": gz,
            "start_age": round(start_age + (n - 1) * 10, 1),
        }
        if dm:   # 每步大运对日主的十神（干 + 支本气）
            step["tenshen"] = shishen(dm, gz[0])
            step["zhi_tenshen"] = shishen(dm, ZHI_BEN_GAN[gz[1]])
        dayun.append(step)
    return {
        "forward": forward,
        "direction": "顺排" if forward else "逆排",
        "start_age": round(start_age, 1),
        "start_months": months,
        "days_to_jie": days,
        "dayun": dayun,
    }


def bazi_liunian(birth_date, ref_year: int = None) -> Dict:
    """流年：当前(或指定)年份干支 + 实岁。"""
    now = datetime.date.today()
    ry = ref_year or now.year
    bd = birth_date if isinstance(birth_date, datetime.date) else datetime.date.fromisoformat(str(birth_date))
    age = ry - bd.year
    if ry == now.year and (bd.month, bd.day) > (now.month, now.day):
        age -= 1
    return {"year": ry, "year_ganzhi": year_ganzhi(ry), "age": age}


def attach_destiny(prof: Dict, gender: str, birth_date) -> Dict:
    """把大运 / 流年挂到八字命盘（娱乐参考）；同时标注当前所处大运。"""
    if not prof or gender not in ("男", "女"):
        return prof
    prof["dayun"] = bazi_dayun(prof["pillars"], gender, birth_date)
    prof["liunian"] = bazi_liunian(birth_date)
    du = prof.get("dayun")
    if du and du.get("dayun"):
        a = prof["liunian"]["age"]
        active = None
        for d in du["dayun"]:
            if d["start_age"] <= a < d["start_age"] + 10:
                active = d["ganzhi"]
                break
        prof["liunian"]["active_dayun"] = active
    return prof


# ═══════════════════════════════════════════════════════════════
# 八字排盘
# ═══════════════════════════════════════════════════════════════
# 十神含义 / 五行应用 / 性格解读（派生文案，传统民俗娱乐参考）
_TENSHEN_MEAN = {
    "比肩": "同我者，主独立、朋侪、自我意识强。",
    "劫财": "助我而分，主竞争、破耗、仗义疏财。",
    "食神": "我生且柔，主才华、口福、温和表达。",
    "伤官": "我生且刚，主聪明、叛逆、才艺外露。",
    "正财": "我克且正，主稳定收入、务实、勤俭。",
    "偏财": "我克且偏，主横财、交际、灵活机动。",
    "正官": "克我且正，主规矩、名望、责任感。",
    "七杀": "克我且偏，主压力、魄力、挑战机遇。",
    "正印": "生我且正，主学识、慈护、贵人。",
    "偏印": "生我且偏，主冷智、专研、孤诣。",
}
_WX_USE = {
    "木": {"行业": "文化教育、园林木业、文创", "方位": "东方", "颜色": "青绿", "人际": "仁和包容"},
    "火": {"行业": "传媒餐饮、能源照明、礼艺", "方位": "南方", "颜色": "红紫", "人际": "礼敬明快"},
    "土": {"行业": "地产仓储、中介信托、稳定业", "方位": "中宫/西南东北", "颜色": "黄棕", "人际": "诚信敦厚"},
    "金": {"行业": "金融机械、法律精密、器械", "方位": "西方/西北", "颜色": "白金", "人际": "义气果决"},
    "水": {"行业": "贸易物流、咨询智慧、流动业", "方位": "北方", "颜色": "黑蓝", "人际": "智慧通达"},
}
_NATURE = {
    "木": "仁厚、向上、有条理",
    "火": "热情、明快、喜表达",
    "土": "敦厚、稳重、重信实",
    "金": "果决、讲义、有锋芒",
    "水": "聪慧、灵活、善变通",
}


def _interpret_bazi(dwx, favorable, tenshen, score, strength, wuxing_count):
    """八字解读层：把骨架字段派生为可读文案（娱乐参考）。"""
    ten_mean = {k: _TENSHEN_MEAN.get(v, "") for k, v in (tenshen or {}).items()}
    use = []
    for w in (favorable or []):
        u = _WX_USE.get(w)
        if u:
            use.append({"wx": w, **u})
    base = _NATURE.get(dwx, "")
    if strength == "身强":
        char = f"日主{dwx}（{base}），身强精力足、有主见，须防固执自负。"
    elif strength == "身弱":
        char = f"日主{dwx}（{base}），身弱心性柔、善随和，须防优柔少断。"
    else:
        char = f"日主{dwx}（{base}），中和得体，刚柔可调。"
    ts = list((tenshen or {}).values())
    if "伤官" in ts or "七杀" in ts:
        char += "局中带伤官/七杀，富才略与魄力。"
    if "正印" in ts or "正官" in ts:
        char += "带正印/正官，重名誉与规矩。"
    if wuxing_count:
        mx = max(wuxing_count, key=wuxing_count.get)
        mn = min(wuxing_count, key=wuxing_count.get)
        wx_read = f"五行中{mx}较旺、{mn}偏弱；{strength}之命，宜以{'、'.join(favorable or [])}调和补益。"
    else:
        wx_read = ""
    return {"tenshen_mean": ten_mean, "favorable_use": use,
            "nature": char, "wuxing_read": wx_read}


def bazi_profile(pillars) -> Dict:
    ps = parse_pillars(pillars)
    year, month, day, hour = ps
    day_gan = day[0]
    dwx = GAN_WX[day_gan]

    # 五行统计（天干 + 地支本气，保持原口径供象义复用）
    count = {w: 0 for w in WX}
    for p in ps:
        count[GAN_WX[p[0]]] += 1
        count[ZHI_BEN[p[1]]] += 1
    # 五行加权（天干1.0 + 地支藏干加权：本气1.0 / 中气0.5 / 余气0.3）
    weight = {w: 0.0 for w in WX}
    _HIDE_W = [1.0, 0.5, 0.3]
    for p in ps:
        weight[GAN_WX[p[0]]] += 1.0
        for k, hg in enumerate(ZHI_HIDDEN[p[1]]):
            weight[GAN_WX[hg]] += _HIDE_W[min(k, 2)]

    # 十神（年干、月干、时干相对日干；日支本气亦列）
    tenshen = {
        "年干": shishen(day_gan, year[0]),
        "月干": shishen(day_gan, month[0]),
        "时干": shishen(day_gan, hour[0]),
        "日支": shishen(day_gan, ZHI_BEN_GAN[day[1]]),
    }
    # 完整四柱十神（干 + 支本气 + 纳音）
    tenshen_full = {
        "年柱": {"干": shishen(day_gan, year[0]), "支": shishen(day_gan, ZHI_BEN_GAN[year[1]]), "纳音": NAYIN.get(year)},
        "月柱": {"干": shishen(day_gan, month[0]), "支": shishen(day_gan, ZHI_BEN_GAN[month[1]]), "纳音": NAYIN.get(month)},
        "日柱": {"干": "日主", "支": shishen(day_gan, ZHI_BEN_GAN[day[1]]), "纳音": NAYIN.get(day)},
        "时柱": {"干": shishen(day_gan, hour[0]), "支": shishen(day_gan, ZHI_BEN_GAN[hour[1]]), "纳音": NAYIN.get(hour)},
    }

    # 身强身弱：得令 / 得地 / 得势 三项加权（传统旺衰法）
    score = 0.0
    mwx = ZHI_BEN[month[1]]
    if mwx == dwx:
        score += 2.5                       # 比劫月令（旺）
    elif mwx == _sheng_wo(dwx):
        score += 2.0                       # 印月令（相）
    elif mwx in (SHENG[dwx], KE[dwx]):
        score -= 0.5                       # 食伤/财月令（休囚）
    elif mwx == _ke_wo(dwx):
        score -= 1.5                       # 官杀月令（死）
    # 得地：地支藏干中有日主之根；本气根最重，日支(自坐)再加权
    for i, p in enumerate(ps):
        hidden = ZHI_HIDDEN[p[1]]
        w = 0.0
        if GAN_WX[hidden[0]] == dwx:
            w = 2.0                        # 本气根
        elif dwx in [GAN_WX[x] for x in hidden[1:]]:
            w = 1.0                        # 中气/余气根
        if w > 0:
            score += w * (1.5 if i == 2 else 1.0)
    # 得势：天干比劫 / 印 透出
    for g in (year[0], month[0], hour[0]):
        if GAN_WX[g] == dwx:
            score += 1.0                   # 比劫透干
        elif GAN_WX[g] == _sheng_wo(dwx):
            score += 0.5                   # 印透干
    strength = "身强" if score >= 3.5 else ("身弱" if score <= 1.5 else "中和")

    # 喜用神
    if strength == "身强":
        xi = [_ke_wo(dwx), SHENG[dwx], KE[dwx]]   # 官杀 / 食伤 / 财
        ji = [_sheng_wo(dwx), dwx]               # 印 / 比劫
    else:
        xi = [_sheng_wo(dwx), dwx]               # 印 / 比劫
        ji = [_ke_wo(dwx), SHENG[dwx], KE[dwx]]
    xi = list(dict.fromkeys(xi))
    ji = list(dict.fromkeys(ji))

    # 纳音（四柱）
    nayin = {nm: NAYIN.get(p) for nm, p in
             zip(["年柱", "月柱", "日柱", "时柱"], ps)}
    # 十二长生：以日主五行查四支所落阶段
    changsheng = {nm: CHANGSHENG[dwx].get(p[1]) for nm, p in
                  zip(["年支", "月支", "日支", "时支"], ps)}
    # 旬空：以日柱定空亡
    xunkong = XUNKONG.get(day)
    # 调候：依月令寒暖燥湿
    tiaohou = _tiaohou(month[1])
    # 从格判定（极旺 / 极弱）
    special = "从强格（专旺，顺其势）" if score >= 6.0 else (
        "从弱格（弃命从他）" if score <= 0.0 else None)

    interp = _interpret_bazi(dwx, xi, tenshen, score, strength, count)
    return {
        "pillars": ps,
        "day_master": day_gan,
        "day_master_wx": dwx,
        "wuxing_count": count,
        "tenshen": tenshen,
        "strength": strength,
        "score": round(score, 1),
        "favorable": xi,     # 喜用五行
        "unfavorable": ji,   # 忌五行
        "bazi_interp": interp,
        "wuxing_weight": {w: round(v, 1) for w, v in weight.items()},  # 藏干加权五行
        "tenshen_full": tenshen_full,        # 完整四柱十神
        "nayin": nayin,                      # 四柱纳音
        "changsheng": changsheng,            # 四支十二长生
        "xunkong": xunkong,                  # 旬空两支
        "tiaohou": tiaohou,                  # 调候喜用
        "special": special,                  # 从格（None/从强/从弱）
        "strength_level": special or strength,
    }


# ═══════════════════════════════════════════════════════════════
# 六爻
# ═══════════════════════════════════════════════════════════════
def _coin() -> int:
    """三枚铜钱：阳(3)数 0~3 → 6/7/8/9。"""
    y = sum(random.choice([0, 1]) for _ in range(3))  # 阳面数
    return [6, 7, 8, 9][y]


def _lines_to_hex(lines: List[int]):
    """lines[0..5] 自下而上 → (本卦名, 变卦名, 动爻列表)。"""
    def name_of(bin6):
        lo = TRI_IDX[TRI_BITS["".join(str(b) for b in bin6[0:3])]]
        up = TRI_IDX[TRI_BITS["".join(str(b) for b in bin6[3:6])]]
        return HEX_NAMES[lo][up]
    ben = [1 if v in (7, 9) else 0 for v in lines]
    bian = [0 if v == 9 else (1 if v == 6 else ben[i]) for i, v in enumerate(lines)]
    dyn = [i + 1 for i, v in enumerate(lines) if v in (6, 9)]
    return name_of(ben), name_of(bian), dyn


# 先天八卦数（梅花易数）：1乾 2兑 3离 4震 5巽 6坎 7艮 8坤
_NUM_TRI = {1: "乾", 2: "兑", 3: "离", 4: "震", 5: "巽", 6: "坎", 7: "艮", 8: "坤"}
# 卦名 → 三爻位（初..上，阳1阴0），配合 TRI_IDX 使用
_TRI_BITS = {"乾": "111", "兑": "110", "离": "101", "震": "100",
             "巽": "011", "坎": "010", "艮": "001", "坤": "000"}


def _meihua_time(when: datetime.datetime) -> List[int]:
    """梅花易数时间起卦：年支序 + 节气月序 + 日数 → 上/下卦；+ 时数 → 动爻。
    以真实时辰干支推演，确定性（同刻同卦），非随机。
    """
    ynum = _zhi_num(year_pillar(when.date())[1])
    mseq = _solar_month_seq(when.date())
    dnum = when.day
    hnum = _zhi_num(_hour_zhi(when.hour))
    s = ynum + mseq + dnum
    up = (s % 8) or 8
    down = ((s + hnum) % 8) or 8
    dong = (s + hnum) % 6 or 6
    lo = [int(c) for c in _TRI_BITS[_NUM_TRI[down]]]   # 下卦（内）初..上
    up_bits = [int(c) for c in _TRI_BITS[_NUM_TRI[up]]]  # 上卦（外）初..上
    ben = lo + up_bits                                  # 自下而上 6 位
    lines = []
    for i in range(6):
        old = (i + 1) == dong
        lines.append(9 if (ben[i] == 1 and old) else
                     6 if (ben[i] == 0 and old) else
                     7 if ben[i] == 1 else 8)
    return lines


# ═══════════════════════════════════════════════════════════════
# 六爻 · 京房纳甲装卦（世应 / 六亲 / 六神）
# 纯规则派生，传统民俗娱乐参考，不涉占断结论。
# ═══════════════════════════════════════════════════════════════
# 八宫（每宫 8 卦，顺序：本宫/一世/二世/三世/四世/五世/游魂/归魂 → 世爻位 6/1/2/3/4/5/4/3）
_PALACE_ORDER = [
    ("乾", ["乾", "姤", "遁", "否", "观", "剥", "晋", "大有"]),
    ("兑", ["兑", "困", "萃", "咸", "蹇", "谦", "小过", "归妹"]),
    ("离", ["离", "旅", "鼎", "未济", "蒙", "涣", "讼", "同人"]),
    ("震", ["震", "豫", "解", "恒", "升", "井", "大过", "随"]),
    ("巽", ["巽", "小畜", "家人", "益", "无妄", "噬嗑", "颐", "蛊"]),
    ("坎", ["坎", "节", "屯", "既济", "革", "丰", "明夷", "师"]),
    ("艮", ["艮", "贲", "大畜", "损", "睽", "履", "中孚", "渐"]),
    ("坤", ["坤", "复", "临", "泰", "大壮", "夬", "需", "比"]),
]
_SHI_BY_ORDER = [6, 1, 2, 3, 4, 5, 4, 3]
HEX_PALACE = {}
for _pt, _names in _PALACE_ORDER:
    for _j, _nm in enumerate(_names):
        HEX_PALACE[_nm] = (_pt, _SHI_BY_ORDER[_j])

# 纳甲：每卦（八纯）内卦(初/二/三爻)与外卦(四/五/上爻)的干支
_NAJIA = {
    "乾": (["甲子", "甲寅", "甲辰"], ["壬午", "壬申", "壬戌"]),
    "坤": (["乙未", "乙巳", "乙卯"], ["癸丑", "癸亥", "癸酉"]),
    "震": (["庚子", "庚寅", "庚辰"], ["庚午", "庚申", "庚戌"]),
    "巽": (["辛丑", "辛亥", "辛酉"], ["辛未", "辛巳", "辛卯"]),
    "坎": (["戊寅", "戊辰", "戊午"], ["戊申", "戊戌", "戊子"]),
    "离": (["己卯", "己丑", "己亥"], ["己酉", "己未", "己巳"]),
    "艮": (["丙辰", "丙午", "丙申"], ["丙戌", "丙子", "丙寅"]),
    "兑": (["丁巳", "丁卯", "丁丑"], ["丁亥", "丁酉", "丁未"]),
}

# 六神（六兽）：青龙/朱雀/勾陈/螣蛇/白虎/玄武，由占卦日干定初爻起神
_LIUSHEN = ["青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武"]

# 六亲象义（供规则断语取用）
_LIUQIN_MEAN = {
    "兄弟": "同辈、朋友、同僚、竞争者，亦主耗财分利。",
    "子孙": "福德、子孙、享乐、医药，克官鬼、利脱难解忧。",
    "妻财": "财货、妻室、饮食、物资，谋财求利之所归。",
    "官鬼": "功名、职位、官非、疾病、约束，亦主压力。",
    "父母": "文书、长辈、学业、房屋、舟车，生我护我之源。",
}
# 六神象义（附爻之象）
_LIUSHEN_MEAN = {
    "青龙": "吉庆、喜庆、文书、佳音，临吉爻更吉。",
    "朱雀": "口舌、文书、信息、争讼，主言谈消息。",
    "勾陈": "迟滞、牵连、田土、牢狱，主阻留不前。",
    "螣蛇": "虚惊、怪异、缠绕、变幻，主疑心反复。",
    "白虎": "凶伤、血光、丧病、威权，主险急之象。",
    "玄武": "暧昧、盗失、情私、暗昧，主隐伏不明。",
}


def _liushen_start(day_gan: str) -> int:
    if day_gan in ("甲", "乙"):
        return 0          # 青龙起
    if day_gan in ("丙", "丁"):
        return 1          # 朱雀起
    if day_gan == "戊":
        return 2          # 勾陈起
    if day_gan == "己":
        return 3          # 螣蛇起
    if day_gan in ("庚", "辛"):
        return 4          # 白虎起
    return 5              # 壬癸 → 玄武起


# 问事 → 用神六亲（简表，娱乐参考；命中首关键词即定）
_YONG_MAP = [
    ("财", "妻财"), ("钱", "妻财"), ("生意", "妻财"), ("工资", "妻财"), ("薪", "妻财"),
    ("事业", "官鬼"), ("工作", "官鬼"), ("职位", "官鬼"), ("官", "官鬼"), ("升", "官鬼"),
    ("感情", "妻财"), ("婚", "妻财"), ("恋", "妻财"), ("对象", "妻财"),
    ("学", "父母"), ("考试", "父母"), ("文书", "父母"), ("名", "父母"), ("证", "父母"),
    ("病", "官鬼"), ("健康", "官鬼"), ("身体", "官鬼"),
    ("出行", "父母"), (" travel", "父母"), ("迁", "父母"),
    ("友", "兄弟"), ("朋", "兄弟"), ("竞", "兄弟"), ("合伙", "兄弟"),
    ("子", "子孙"), ("孩", "子孙"), ("孕", "子孙"), ("脱", "子孙"), ("讼", "官鬼"),
    ("车", "父母"), ("房", "父母"), ("宅", "父母"), ("信", "朱雀"),
]


def _yongshen_hint(q: str, palace_wx: str):
    if not q:
        return None
    for k, v in _YONG_MAP:
        if k in q:
            return v
    return None


def _liuyao_yongshen(question: str, zhuang: Dict) -> Dict:
    """取用神定位：依问事定用神六亲，并在本卦中定位其实爻（自下而上）。

    返回 {type, primary(主用神爻位), lines(全部匹配爻), note}。无问事或不上卦均安全返回。
    """
    yq = _yongshen_hint(question, zhuang.get("palace_wx", "")) if question else None
    if not yq:
        return {"type": None, "primary": None, "lines": [],
                "note": "未提供问事，无法定位用神；可暂以世爻（自身）为用参看。"}
    lines = [l for l in zhuang.get("lines", []) if l.get("liuqin") == yq]
    primary = next((l for l in lines if l.get("shi")), None) or (lines[0] if lines else None)
    out = [{
        "pos": l["pos"], "name": l["name"], "gz": l["gz"],
        "wx": l["wx"], "liushen": l["liushen"],
        "old": l["old"], "shi": l.get("shi"), "ying": l.get("ying"),
    } for l in lines]
    if lines:
        note = "用神「%s」上卦，共 %d 处" % (yq, len(lines))
        if primary and primary.get("shi"):
            note += "；持世最切，事与己身相连。"
    else:
        note = "用神「%s」不上卦（伏藏），须查伏神或借世应参看；事象隐伏，宜缓不宜急。" % yq
    return {"type": yq, "primary": primary["pos"] if primary else None,
            "lines": out, "note": note}


def _liuyao_duanyu(zhuang: Dict, zhuang_bian: Dict, question: str) -> Dict:
    """六爻规则断语（保底，不依赖 LLM）：基于世应 / 用神 / 动爻 / 六神做结构化研判。

    以本宫五行为「我」，论各爻旺相休囚死，给出可读中文断语。仅供传统民俗娱乐参考。
    """
    lines = zhuang.get("lines", [])
    pw = zhuang.get("palace_wx", "")
    shi = next((l for l in lines if l["shi"]), None)
    ying = next((l for l in lines if l["ying"]), None)

    def strength(l):
        w = l["wx"]
        if w == pw:
            return "旺"
        if SHENG.get(pw) == w:
            return "相"      # 我生
        if KE.get(pw) == w:
            return "休"      # 我克
        if KE.get(w) == pw:
            return "囚"      # 克我
        if SHENG.get(w) == pw:
            return "死"      # 生我
        return "休"

    body = []
    # 世爻（求问者自身）
    if shi:
        s_w, s_mv = strength(shi), ("发动（主变）" if shi["old"] else "安静")
        body.append("世爻：%s（%s·%s），%s、%s。世爻为求问者自身，%s"
                    % (shi["name"], shi["liuqin"], shi["liushen"], s_w, s_mv,
                       _LIUQIN_MEAN.get(shi["liuqin"], "")))
    # 应爻（所问之事 / 对方）
    if ying:
        body.append("应爻：%s（%s·%s），%s。应爻为所问之事或对方。"
                    % (ying["name"], ying["liuqin"], ying["liushen"], strength(ying)))
    # 用神（依问事）
    yq = _yongshen_hint(question, pw) if question else None
    yl = [l for l in lines if yq and l["liuqin"] == yq]
    if yq:
        if yl:
            l0 = yl[0]
            yst, ymv = strength(l0), ("发动有变" if l0["old"] else "安静")
            verdict = ("用神得%s，事多可成" % yst if yst in ("旺", "相")
                       else "用神%s，事多迟滞" % yst if yst in ("囚", "死")
                       else "用神休，进退须斟酌")
            body.append("用神（%s）：在 %s 位（%s·%s），%s、%s；%s。"
                        % (yq, l0["name"], l0["liuqin"], l0["liushen"], yst, ymv, verdict))
        else:
            body.append("用神（%s）：卦中不上卦（伏藏），须查伏神；事象隐伏，宜缓不宜急。" % yq)
    # 动爻（变机）
    dongs = [l for l in lines if l["old"]]
    if dongs:
        blk = ["动爻："]
        for l in dongs:
            bl = next((x for x in zhuang_bian.get("lines", []) if x["pos"] == l["pos"]), None) if zhuang_bian else None
            binfo = ("变出 %s（%s）" % (bl["liuqin"], bl["wx"])) if bl else "发动"
            blk.append("  · 第%s爻发动：%s（%s）临%s，%s。"
                       % (l["pos"], l["liuqin"], l["wx"], l["liushen"], binfo))
        blk.append("  动者机之将显，所临六亲六神即其象。")
        body.append("\n".join(blk))
    # 六神附世 / 用
    seen = [shi] + yl
    shen = []
    for l in seen:
        if l and l.get("liushen"):
            shen.append("  · %s 临%s：%s" % (l["liuqin"], l["liushen"], _LIUSHEN_MEAN.get(l["liushen"], "")))
    if shen:
        body.append("六神之象：\n" + "\n".join(shen))
    # 综合
    sumup = ("六爻俱静，世应分明，宜守不宜妄动；依世应旺衰与用神定进退。"
             if not dongs else
             "卦有动爻，事在演变：以世爻为体、用神为用，观动爻所之可推吉凶趋向。")
    body.append("断语：" + sumup + "（传统规则参考，仅供娱乐）")
    return {"lines": body, "summary": sumup}


def _zhuanggua(lines: List[int], when: datetime.datetime = None) -> Dict:
    """京房纳甲装卦：为本卦/变卦六爻配 干支 / 六亲 / 六神 / 世应。"""
    when = when or datetime.datetime.now()
    ben_bits = [1 if v in (7, 9) else 0 for v in lines]
    lower = TRI_BITS["".join(map(str, ben_bits[0:3]))]
    upper = TRI_BITS["".join(map(str, ben_bits[3:6]))]
    ben_name = HEX_NAMES[TRI_IDX[lower]][TRI_IDX[upper]]
    palace_tri, shi = HEX_PALACE.get(ben_name, ("乾", 6))
    palace_wx = TRI_WX[palace_tri]
    ying = ((shi + 2) % 6) + 1
    day_gan = day_ganzhi(when.date())[0]
    ls_start = _liushen_start(day_gan)
    pos_name = ["初", "二", "三", "四", "五", "上"]
    out = []
    for i in range(6):
        tri = lower if i < 3 else upper
        gz = _NAJIA[tri][0 if i < 3 else 1][i % 3]
        zhi = gz[1]
        wx = ZHI_WX[zhi]
        if wx == palace_wx:
            lq = "兄弟"
        elif SHENG[palace_wx] == wx:
            lq = "子孙"
        elif KE[palace_wx] == wx:
            lq = "妻财"
        elif KE[wx] == palace_wx:
            lq = "官鬼"
        else:
            lq = "父母"
        yang = lines[i] in (7, 9)
        old = lines[i] in (6, 9)
        # 爻名：初/上居前（初九/上六），二三四五则九/六居前（九二/六五…）
        yw = "九" if yang else "六"
        pn = pos_name[i]
        yname = pn + yw if pn in ("初", "上") else yw + pn
        out.append({
            "pos": i + 1,
            "name": yname,
            "gz": gz,
            "wx": wx,
            "liuqin": lq,
            "liushen": _LIUSHEN[(ls_start + i) % 6],
            "shi": (i + 1) == shi,
            "ying": (i + 1) == ying,
            "yang": yang,
            "old": old,
        })
    return {
        "ben_gua": ben_name,
        "lower": lower,
        "upper": upper,
        "palace": palace_tri,
        "palace_wx": palace_wx,
        "shi_pos": shi,
        "ying_pos": ying,
        "lines": out,
    }


# ───────────────────────────────────────────────────────────
# LLM 象义层（六爻解读散文）—— 规则引擎保底 + LLM 增厚
# 配置读取环境变量 FORTUNE_LLM_API_BASE / FORTUNE_LLM_API_KEY / FORTUNE_LLM_MODEL
# 未配置或调用失败均安全回退，绝不阻断主流程。
# ───────────────────────────────────────────────────────────
def _llm_chat_text(base: str, key: str, model: str, prompt: str) -> str:
    """调用 OpenAI 兼容文本对话端点，返回模型文本（复用视觉通道的 urllib 模式）。"""
    import json
    url = f"{base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


def _liuyao_zhuang_text(z: Dict) -> str:
    """把装卦 dict 转成给 LLM 看的结构化中文文本（自下而上，标注世/应/动）。"""
    lines = z.get("lines", [])
    rows = []
    for ln in reversed(lines):  # 初爻在下，上爻在上
        tags = []
        if ln.get("shi"):
            tags.append("世")
        if ln.get("ying"):
            tags.append("应")
        if ln.get("old"):
            tags.append("动" if ln.get("yang") else "变")
        t = "（" + "/".join(tags) + "）" if tags else ""
        rows.append("  · 第%s爻（%d位）: %s %s %s %s%s"
                    % (ln["name"], ln["pos"], ln["gz"], ln["wx"],
                       ln["liuqin"], ln["liushen"], t))
    head = ("卦名：%s　宫：%s宫（五行属%s）　世爻在%d位　应爻在%d位"
            % (z.get("ben_gua"), z.get("palace"), z.get("palace_wx"),
               z.get("shi_pos"), z.get("ying_pos")))
    if z.get("yongshen"):
        head += "　用神提示：%s" % z.get("yongshen")
    return head + "\n" + "\n".join(rows)


def _build_liuyao_prompt(zhuang: Dict, zhuang_bian: Dict,
                         question: str, is_static: bool) -> str:
    """构造六爻解读散文的 prompt：装卦数据 + 结构约束。"""
    ben_txt = _liuyao_zhuang_text(zhuang)
    if not is_static and zhuang_bian:
        change_desc = ("本卦（现状）装卦如下：\n" + ben_txt +
                       "\n\n变卦（演变后）装卦如下：\n" + _liuyao_zhuang_text(zhuang_bian))
        sections = [
            "一、卦局总断（一句话点出本卦与变卦的核心意象，以及总体吉凶/趋势）",
            "二、本卦解析（现状处境，结合世应、用神、六亲六神）",
            "三、动爻拆解（逐一说明发动之爻的变化与含义）",
            "四、变卦解析（事态演变后的走向）",
            "五、针对所求之事的具体研判（近期大概率会怎样）",
            "六、实操建议（为求问者提供 2-4 条可落地的建议或心态提醒）",
            "七、简短总结（收束语，强调一切仅供参考、娱乐向）",
        ]
    else:
        change_desc = "本卦（六爻俱静，无变卦）装卦如下：\n" + ben_txt
        sections = [
            "一、卦局总断（一句话点出本卦的核心意象，以及总体吉凶/趋势）",
            "二、本卦解析（现状处境，结合世应、用神、六亲六神）",
            "三、针对所求之事的具体研判（近期大概率会怎样）",
            "四、实操建议（为求问者提供 2-4 条可落地的建议或心态提醒）",
            "五、简短总结（收束语，强调一切仅供参考、娱乐向）",
        ]
    section_block = "\n".join("   " + s for s in sections)
    q = (question or "求问近期运势").strip()
    return (
        "你是一位深谙《周易》京房纳甲六爻的命理解读师。下面是一卦的装卦结果"
        "（纳甲、世应、六亲、六神已排定），请用传统卦象义理为求问者撰写一篇"
        "通俗而专业的中文解读散文。\n\n"
        "【求问之事】\n" + q + "\n\n"
        "【装卦数据】\n" + change_desc + "\n\n"
        "【撰写要求】\n"
        "1. 语言：简体中文，通俗流畅、有温度，避免生硬堆砌术语；可适当引经据典。\n"
        "2. 结构（用小标题分段，序号连贯）：\n" + section_block + "\n"
        "3. 必须基于上方装卦数据推演，不得凭空捏造干支/世应；保持理性、正向、娱乐向。\n"
        "4. 总篇幅约 500-900 字。直接输出正文，不要外层 JSON、不要代码块。"
    )


def _liuyao_narrative(zhuang: Dict, zhuang_bian: Dict,
                      question: str, is_static: bool) -> Dict:
    """LLM 象义层：基于装卦数据生成中文解读散文。未配置或失败则优雅回退。

    返回 {mode: 'llm'|'pending'|'error', model, text}。
    """
    base = os.environ.get("FORTUNE_LLM_API_BASE", "").rstrip("/")
    key = os.environ.get("FORTUNE_LLM_API_KEY", "")
    model = os.environ.get("FORTUNE_LLM_MODEL", "gpt-4o-mini")
    if not (base and key):
        return {"mode": "pending", "model": None,
                "text": "未配置 LLM 象义层（FORTUNE_LLM_API_BASE/KEY），"
                        "当前仅展示规则引擎装卦与卦象参考。开启 AI 详批需平台配置文本模型。"}
    try:
        prompt = _build_liuyao_prompt(zhuang, zhuang_bian, question, is_static)
        text = _llm_chat_text(base, key, model, prompt)
        if not text or not text.strip():
            return {"mode": "error", "model": model,
                    "text": "LLM 象义层返回为空，请稍后重试或查看规则引擎装卦与卦象参考。"}
        return {"mode": "llm", "model": model, "text": text.strip()}
    except Exception as e:  # 任意异常均安全回退
        return {"mode": "error", "model": model,
                "text": f"LLM 象义层调用失败（{e}），已回退为规则引擎装卦与卦象参考。"}


def liuyao(method: str = "coin", question: str = "", seed_key: str = None,
           when: datetime.datetime = None, ai: bool = False) -> Dict:
    if method == "time":
        # 时间卦：以真实时辰干支起卦（确定性），非随机
        when = when or datetime.datetime.now()
        lines = _meihua_time(when)
    else:
        lines = [_coin() for _ in range(6)]
    ben, bian, dyn = _lines_to_hex(lines)
    yang_line = [v in (7, 9) for v in lines]
    zhuang = _zhuanggua(lines, when)
    zhuang["yongshen"] = _yongshen_hint(question, zhuang["palace_wx"])
    # 变卦装卦：动爻阴阳反转后的六爻
    bian_bits = [0 if v == 9 else (1 if v == 6 else (1 if v in (7, 9) else 0)) for v in lines]
    zhuang_bian = _zhuanggua([7 if b else 8 for b in bian_bits], when)
    result = {
        "method": method,
        "question": question,
        "lines": [{"value": v, "yang": yang_line[i], "old": v in (6, 9)} for i, v in enumerate(lines)],
        "ben_gua": ben,
        "bian_gua": bian,
        "changing_lines": dyn,
        "is_static": len(dyn) == 0,
        "zhuanggua": zhuang,
        "zhuanggua_bian": zhuang_bian,
        "yongshen_detail": _liuyao_yongshen(question, zhuang),
        "duanyu": _liuyao_duanyu(zhuang, zhuang_bian, question),
    }
    # 卦象象义 + 解析（传统卦象参考，娱乐为主）
    by = _GUA_YIXIANG.get(ben, "")
    yy = _GUA_YIXIANG.get(bian, "") if bian else ""
    if dyn:
        result["reading"] = (
            f"本卦【{ben}】，第{'、'.join(map(str, dyn))}爻发动，事态演变趋于【{bian}】。"
        )
        detail = (f"本卦《{ben}》：{by}"
                  f"　动爻既发，由《{ben}》之《{bian}》，事有转折——{yy}")
    else:
        result["reading"] = f"本卦【{ben}】，六爻俱静，事象稳定，宜守不宜攻。"
        detail = f"本卦《{ben}》：{by}"
    result["ben_yixiang"] = by
    result["bian_yixiang"] = yy
    result["reading_detail"] = detail + "（传统卦象参考，仅供娱乐）"
    # LLM 象义层（可选增厚）：规则引擎保底，ai=True 时挂 narrative
    if ai:
        result["narrative"] = _liuyao_narrative(
            zhuang, zhuang_bian, question, result["is_static"],
        )
    return result


# ═══════════════════════════════════════════════════════════════
# 日柱（公历 → 干支）
# ═══════════════════════════════════════════════════════════════
def day_ganzhi(d: datetime.date) -> str:
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jdn = day + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    gz = (jdn + 49) % 60
    return GAN[gz % 10] + ZHI[gz % 12]


def year_ganzhi(y: int) -> str:
    return GAN[(y - 4) % 10] + ZHI[(y - 4) % 12]


# ═══════════════════════════════════════════════════════════════
# 每日日签
# ═══════════════════════════════════════════════════════════════
# 日干 → 财神位 / 喜神位（简表）
SHEN_POS = {
    "甲": ("东北", "东北"), "乙": ("东北", "西北"), "丙": ("西南", "西南"),
    "丁": ("西南", "正南"), "戊": ("正北", "东南"), "己": ("正北", "东北"),
    "庚": ("正东", "西北"), "辛": ("正东", "西南"), "壬": ("正南", "正南"),
    "癸": ("正南", "东南"),
}
# 日支 → 冲 / 合 / 三合
ZHI_CHONG = {"子": "午", "丑": "未", "寅": "申", "卯": "酉", "辰": "戌",
             "巳": "亥", "午": "子", "未": "丑", "申": "寅", "酉": "卯",
             "戌": "辰", "亥": "巳"}
ZHI_HE = {"子": "申辰", "丑": "巳酉", "寅": "午戌", "卯": "亥未", "辰": "申子",
          "巳": "酉丑", "午": "寅戌", "未": "亥卯", "申": "子辰", "酉": "巳丑",
          "戌": "寅午", "亥": "卯未"}


_RANK_ORDER = {"大吉": 0, "次吉": 1, "平": 2, "忌": 3}


def _personal_advice(dwx: str, fav: List[str], unfav: List[str], rank) -> Dict:
    """穿衣/茶表走市面通行口径（以当日日干为我），这里按本人喜用再收一刀。

    只有建过档（有喜用神）才给，否则返回 None，前端不渲染这一行。
    """
    if not fav:
        return None

    # 本人喜用里，挑今日通行评级最好的作首选、次好的作备选
    ordered = sorted(fav, key=lambda w: (_RANK_ORDER[rank(w)], WX.index(w)))
    first = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None

    parts = ["你的喜用是" + "、".join(fav) + "。"]
    parts.append("今日首选%s（%s）" % (first, "/".join(WX_COLOR[first])))
    if second:
        parts.append("，退一步%s（%s）也行" % (second, "/".join(WX_COLOR[second])))
    parts.append("。")

    # 通行口径的「大吉」若正撞本人忌神，明说，别让用户自己去发现矛盾
    top = _sheng_wo(dwx)
    if top in unfav:
        parts.append("上表通行大吉是%s（%s），但%s是你的忌神——今天少碰。"
                     % (top, "/".join(WX_COLOR[top]), top))

    return {
        "favorable": fav,
        "first": {"wx": first, "color": WX_COLOR[first], "tea": WX_TEA[first]},
        "second": ({"wx": second, "color": WX_COLOR[second], "tea": WX_TEA[second]}
                   if second else None),
        "conflict_with_common": top if top in unfav else None,
        "text": "".join(parts),
    }


# 当日日干 / 日支 对本人日主的十神 → 日签个人化提示（传统民俗娱乐参考）
_DAY_TENSHEN_NOTE = {
    "比肩": "同辈协作之日，利社交、团队、并肩推进；忌与人争利、单打独斗。",
    "劫财": "人际互动之日，利帮扶、沟通；忌破耗、与人争财。",
    "食神": "表达创意之日，利写作、沟通、展现才华；忌口舌任性、过度表现。",
    "伤官": "才艺显露之日，利创意、突破；忌傲气、口舌、违逆上级。",
    "正财": "务实求财之日，利理财、交易、稳定进账；忌冲动消费、投机。",
    "偏财": "灵活机变之日，利交际、偏财机遇；忌贪心、冒险冒进。",
    "正官": "规矩名望之日，利推进正事、尽责、立信；忌违规、顶撞上司。",
    "七杀": "压力机遇之日，利攻坚、决断；忌畏缩、硬碰硬。",
    "正印": "学习沉淀之日，利读书、规划、受教、得贵人；忌懒散荒废。",
    "偏印": "钻研独思之日，利专研、冷门深耕；忌钻牛角尖、孤僻。",
}


def daily_sign(date: datetime.date = None, favorable: List[str] = None,
               unfavorable: List[str] = None, day_master: str = None) -> Dict:
    """每日日签。带 day_master（本人日主天干）时，额外给出「当日日干/日支对本人的十神」个人化解读。"""
    date = date or datetime.date.today()
    dg = day_ganzhi(date)
    dgan, dzhi = dg[0], dg[1]
    dwx = GAN_WX[dgan]
    fav = favorable or []
    unfav = unfavorable or []
    day_tenshen = shishen(day_master, dgan) if day_master else None
    day_zhi_tenshen = shishen(day_master, ZHI_BEN_GAN[dzhi]) if day_master else None
    day_tenshen_note = _DAY_TENSHEN_NOTE.get(day_tenshen, "") if day_master else ""

    # 五行穿衣 / 茶（以日干为「我」）
    def rank(wx):
        if wx == _sheng_wo(dwx):
            return "大吉"
        if wx == dwx:
            return "次吉"
        if wx in (SHENG[dwx], KE[dwx]):
            return "平"
        return "忌"
    clothes, tea = {}, {}
    for w in WX:
        clothes[w] = {"color": WX_COLOR[w], "rank": rank(w)}
        tea[w] = {"tea": WX_TEA[w], "rank": rank(w)}
    # 幸运色 / 数（取大吉+次吉五行；若有个人喜用则优先交集）
    lucky_wx = [w for w in WX if clothes[w]["rank"] in ("大吉", "次吉")]
    if fav:
        inter = [w for w in lucky_wx if w in fav]
        if inter:
            lucky_wx = inter
    lucky_colors = []
    for w in lucky_wx:
        lucky_colors += WX_COLOR[w]
    lucky_numbers = []
    for w in lucky_wx:
        lucky_numbers += WX_NUMBER[w]

    cai, xi = SHEN_POS.get(dgan, ("", ""))
    chong = ZHI_CHONG.get(dzhi, "")
    he = ZHI_HE.get(dzhi, "")

    # 运势评分（基于日干五行与喜用匹配度，加轻微随机）
    base = 7.0
    if fav and dwx in fav:
        base += 0.6
    score = round(min(9.5, max(5.0, base + random.uniform(-0.6, 0.6))), 1)

    # 宜忌：看「当日日干五行」是否落在本人喜用内（无命盘时按中性处理）
    day_favor = (not fav) or (dwx in fav)

    # 个人化补充：穿衣/茶表维持通行口径（以当日日干为我），此处按本人喜用再收一刀
    personal = _personal_advice(dwx, fav, unfav, rank)

    return {
        "date": date.isoformat(),
        "day_ganzhi": dg,
        # 注意：这是「当日日干五行」，不是本人日主五行（本人日主见 bazi_profile.day_master_wx）
        "day_wx": dwx,
        "day_master": day_master,
        "day_tenshen": day_tenshen,
        "day_zhi_tenshen": day_zhi_tenshen,
        "day_tenshen_note": day_tenshen_note,
        "favorable": fav or [],
        "scores": {"综合": score, "事业": round(score + random.uniform(-0.5, 0.5), 1),
                   "财运": round(score + random.uniform(-0.8, 0.6), 1),
                   "感情": round(score + random.uniform(-0.5, 0.5), 1)},
        "yi": ["合作", "学习", "整理", "储蓄"] if day_favor else ["守成", "内省", "复盘"],
        "ji": ["冲动消费", "借贷", "口舌争辩"],
        "shen": {"财神位": cai, "喜神位": xi},
        "zodiac": {"冲": chong, "合": he},
        "clothes": clothes,
        "tea": tea,
        "personal_advice": personal,
        "lucky_colors": lucky_colors,
        "lucky_numbers": lucky_numbers,
        "disclaimer": "传统文化娱乐参考，不作为医疗/投资/人生决策依据。",
    }


# ═══════════════════════════════════════════════════════════════
# 年运报告
# ═══════════════════════════════════════════════════════════════
def _year_advice_text(fav, unfav, rel):
    """年运宜忌：按本人喜用神五行动态生成（替代原来的写死文案）。"""
    yi_parts, ji_parts = [], []
    for w in (fav or []):
        u = _WX_USE.get(w)
        if u:
            yi_parts.append(f"{w}（{u['方位']}·{u['颜色']}：{u['行业']}）")
    for w in (unfav or []):
        u = _WX_USE.get(w)
        if u:
            ji_parts.append(f"{w}（{u['方位']}·{u['行业']}）")
    yi = ("宜：顺势借流年之便，多用「" + "；".join(yi_parts) + "」相关行业、人际与方位进取。"
          ) if yi_parts else "宜：守成蓄势，按部就班，沉淀内功。"
    ji = ("忌：少碰「" + "；".join(ji_parts) + "」相关事象，防耗散与无谓压力。"
          ) if ji_parts else "忌：冒进与冲动决策。"
    return yi, ji


def year_report(pillars, year: int = None) -> Dict:
    prof = bazi_profile(pillars)
    year = year or datetime.date.today().year
    yg = year_ganzhi(year)
    y_gan_wx = GAN_WX[yg[0]]
    dwx = prof["day_master_wx"]
    fav = prof["favorable"]

    # 流年与日主关系
    if y_gan_wx == dwx:
        rel = "比劫年（竞争多、开销大、财易分散）"
    elif y_gan_wx == _sheng_wo(dwx):
        rel = "印星年（贵人/学习/沉淀之象）"
    elif y_gan_wx == SHENG[dwx]:
        rel = "食伤年（表达/创意/输出之象）"
    elif y_gan_wx == KE[dwx]:
        rel = "财星年（求财/务实之象）"
    else:
        rel = "官杀年（压力/机遇并存）"

    advice_wx = [w for w in fav if w not in (y_gan_wx,)]
    yt = shishen(prof["day_master"], yg[0])
    yz = shishen(prof["day_master"], ZHI_BEN_GAN[yg[1]])
    yi_text, ji_text = _year_advice_text(fav, prof["unfavorable"], rel)
    return {
        "year": year,
        "year_ganzhi": yg,
        "day_master": prof["day_master"],
        "strength": prof["strength"],
        "favorable": fav,
        "unfavorable": prof["unfavorable"],
        "bazi_base": {
            "wuxing_weight": prof["wuxing_weight"],
            "tenshen_full": prof["tenshen_full"],
            "nayin": prof["nayin"],
            "changsheng": prof["changsheng"],
            "xunkong": prof["xunkong"],
            "tiaohou": prof["tiaohou"],
            "special": prof["special"],
            "strength_level": prof["strength_level"],
        },
        "liunian_relation": rel,
        "advice": {
            "重点五行": advice_wx or fav,
            "宜": yi_text,
            "忌": ji_text,
            "流年天干十神": yt,
            "流年地支十神": yz,
        },
        "disclaimer": "传统文化娱乐参考，不作为医疗/投资/人生决策依据。",
    }


# ═══════════════════════════════════════════════════════════════
# 风水堪舆（看空间）· 坐向 + GPS
# ═══════════════════════════════════════════════════════════════
# 24 山（罗盘 0°=正北子，顺时针每 15° 一山）
_MOUNTAINS_24 = ["子", "癸", "丑", "艮", "寅", "甲", "卯", "乙", "辰", "巽", "巳", "丙",
                 "午", "丁", "未", "坤", "申", "庚", "酉", "辛", "戌", "乾", "亥", "壬"]
# 山 → 后天八卦（定宅卦用）
_MT_TO_TRIGRAM = {
    "戌": "乾", "乾": "乾", "亥": "乾",
    "壬": "坎", "子": "坎", "癸": "坎",
    "丑": "艮", "艮": "艮", "寅": "艮",
    "甲": "震", "卯": "震", "乙": "震",
    "辰": "巽", "巽": "巽", "巳": "巽",
    "丙": "离", "午": "离", "丁": "离",
    "未": "坤", "坤": "坤", "申": "坤",
    "庚": "兑", "酉": "兑", "辛": "兑",
}
# 八宅：各宅卦（坐山后天卦）→ 八方吉凶星。吉=伏位/生气/延年/天医；凶=绝命/五鬼/六煞/祸害
_BAZHAI = {
    "坎": {"北": "伏位", "东": "天医", "东南": "生气", "南": "延年",
           "东北": "五鬼", "西南": "绝命", "西": "祸害", "西北": "六煞"},
    "离": {"南": "伏位", "北": "延年", "东": "生气", "东南": "天医",
           "西南": "六煞", "西": "五鬼", "西北": "绝命", "东北": "祸害"},
    "震": {"东": "伏位", "南": "生气", "北": "天医", "东南": "延年",
           "西": "绝命", "西北": "五鬼", "东北": "六煞", "西南": "祸害"},
    "巽": {"东南": "伏位", "北": "生气", "南": "天医", "东": "延年",
           "西": "六煞", "西北": "祸害", "东北": "绝命", "西南": "五鬼"},
    "乾": {"西北": "伏位", "西": "延年", "东北": "生气", "西南": "天医",
           "北": "绝命", "东": "五鬼", "东南": "祸害", "南": "六煞"},
    "坤": {"西南": "伏位", "西": "天医", "西北": "延年", "东北": "生气",
           "北": "祸害", "东": "六煞", "东南": "五鬼", "南": "绝命"},
    "艮": {"东北": "伏位", "西南": "延年", "西": "生气", "西北": "天医",
           "南": "祸害", "北": "五鬼", "东南": "绝命", "东": "六煞"},
    "兑": {"西": "伏位", "西北": "生气", "西南": "延年", "东北": "天医",
           "东": "绝命", "东南": "五鬼", "南": "祸害", "北": "六煞"},
}
_BAZHAI_JI = {"伏位", "生气", "延年", "天医"}
# 绝对罗盘方位 → 后天八卦（九宫八卦，固定）
_DIR_TO_TRIGRAM = {"北": "坎", "东北": "艮", "东": "震", "东南": "巽",
                   "南": "离", "西南": "坤", "西": "兑", "西北": "乾"}
# 九宫（绝对罗盘方位）通用功能提示，与坐向无关，作峦头/布局参考
_JIUGONG_NOTE = {
    "坎": "北·水·宜静不宜动，忌污湿",
    "艮": "东北·土·聚气守财，宜玄关",
    "震": "东·木·生发，宜餐厅/书房",
    "巽": "东南·木·文昌，宜书房/通风",
    "离": "南·火·明堂纳气，宜客厅",
    "坤": "西南·土·安稳，宜次卧",
    "兑": "西·金·口才，宜书房/会客",
    "乾": "西北·金·男主位，忌污压",
    "中": "太极·宜空净",
}
# 中文方位 ↔ 罗盘度数（用于 '坐北朝南' 等）
_CN_DIR = {"北": 0, "东北": 45, "东": 90, "东南": 135,
           "南": 180, "西南": 225, "西": 270, "西北": 315}


def _bearing_to_mountain(deg: float) -> str:
    """罗盘度数（0=正北，顺时针）→ 24 山。"""
    deg = (deg % 360 + 360) % 360
    idx = round(deg / 15.0) % 24
    return _MOUNTAINS_24[idx]


def _parse_orientation(orientation) -> Dict:
    """坐向入参 → 结构化。支持：
      - 罗盘度数(浮点/int)：视为「朝向」bearing（磁北）
      - '子山午向' / '坐子向午' / '坐北朝南' 等字符串
      - dict：{'facing_deg': 178.3, 'source': 'device'} 或 {'sitting':'子','facing':'午'}
    返回 {sitting, facing, sitting_mountain, facing_mountain, bearing_mag, sitting_facing, source}
    """
    source = "manual"
    facing_deg = None
    sitting_mt = facing_mt = None

    if isinstance(orientation, (int, float)):
        facing_deg = float(orientation)
    elif isinstance(orientation, dict):
        source = orientation.get("source", "manual")
        if "facing_deg" in orientation:
            facing_deg = float(orientation["facing_deg"])
        if orientation.get("sitting") and orientation.get("facing"):
            sitting_mt = orientation["sitting"]
            facing_mt = orientation["facing"]
    elif isinstance(orientation, str):
        s = (orientation.replace("坐", "").replace("向", "")
             .replace("朝", "").replace("山", ""))
        if len(s) >= 2 and s[0] in _MOUNTAINS_24 and s[1] in _MOUNTAINS_24:
            sitting_mt, facing_mt = s[0], s[1]
        elif len(s) >= 2 and s[0] in _CN_DIR and s[1] in _CN_DIR:
            facing_deg = float(_CN_DIR[s[1]])
            facing_mt = _bearing_to_mountain(facing_deg)

    if facing_deg is None and facing_mt is None:
        raise ValueError("坐向无法解析：请给罗盘度数、'子山午向' 或 '坐北朝南'")

    if facing_mt is None:
        facing_mt = _bearing_to_mountain(facing_deg)
    if sitting_mt is None:
        if facing_deg is not None:
            sitting_mt = _bearing_to_mountain((facing_deg + 180) % 360)
        else:
            sitting_mt = _bearing_to_mountain((_CN_DIR.get(facing_mt, 0) + 180) % 360)

    return {
        "sitting": sitting_mt,
        "facing": facing_mt,
        "sitting_mountain": sitting_mt,
        "facing_mountain": facing_mt,
        "bearing_mag": facing_deg,
        "sitting_facing": f"{sitting_mt}山{facing_mt}向",
        "source": source,
    }


def _magnetic_declination(lat: float, lon: float, year: int) -> float:
    """近似磁偏角（度，真北 − 磁北）。中国大致 −2°~−8°，此处用粗线性模型，仅演示。

    生产环境应调用 WMM/IGRF 或在线磁偏角服务求得精确值。
    """
    decl = -5.0 + (105.0 - lon) * 0.06 + (lat - 35.0) * 0.04
    return round(decl, 2)


# 八卦 ↔ 家庭成员/人事含义（缺角、压凶时研判用）
_BAGUA_MEANING = {
    "坎": "中男·事业·肾", "离": "中女·名声·心",
    "震": "长男·进取·肝", "巽": "长女·文昌·胆",
    "乾": "男主·权威·头", "坤": "女主·包容·腹",
    "艮": "少男·稳定·脾胃", "兑": "少女·口才·肺",
}


def _dir_trigram(d):
    """方位 → 八卦；'中'(房屋中心/中宫) 特判，避免 None 跳过关键 finding。"""
    return _DIR_TO_TRIGRAM.get(d) or (d if d == "中" else None)


def _analyze_floor_plan(fp, ji: List[str], xiong: List[str]) -> Dict:
    """户型图/实景结构化峦头（形法）分析。

    入参 fp：
      - None                      → 未提供，仅给坐向理气通用建议
      - dict（结构化户型要素）      → 真正分析
    注：图片字符串由 _vision_analyze_floor_plan 处理（视觉模型或占位）。
        字段（中文键，前后端对齐）：
          '门向'/'door_dir'      大门开向方位
          '主卧方'/'master_dir'  主卧方位
          '厨房方'/'kitchen_dir' 厨房/灶台方位
          '卫生间方'/'toilet_dir'卫生间方位
          '缺角'/'missing'       缺角方位列表
          '横梁'/'beam'          是否横梁压顶
          '穿堂'/'through'       是否门对窗穿堂煞
    返回 {provided, mode, findings[], summary}
    """
    if fp is None:
        return {"provided": False,
                "note": "未提供户型图或实地信息，仅按坐向理气给通用建议。"}
    if isinstance(fp, str):
        return {"provided": True, "mode": "image_pending",
                "note": "图片/链接已接收，等待视觉模型解析为结构化户型；"
                        "当前仅按坐向理气叠加结论。",
                "raw_hint": fp[:120]}
    if not isinstance(fp, dict):
        return {"provided": True, "mode": "unknown",
                "note": "户型信息格式无法识别，请传结构化 dict 或图片引用字符串。"}

    def _grade(d):
        if d in ji:
            return "吉"
        if d in xiong:
            return "凶"
        return "中"

    findings = []

    # 大门 —— 纳气之口
    dd = fp.get("门向") or fp.get("door_dir")
    if dd:
        tri = _dir_trigram(dd)
        if tri:
            g = _grade(dd)
            findings.append({
                "项": "大门", "方位": dd, "卦": tri, "评级": f"{g}方",
                "建议": ("大门纳吉气，利纳财进气，保持明亮整洁即可。"
                         if g == "吉" else
                         "大门落凶方，宜设玄关/屏风缓冲，门内挂天然葫芦化煞。"
                         if g == "凶" else
                         "大门落中平方位，正常使用、保持通畅明亮即可。"),
            })

    # 主卧 —— 人休养之所，宜吉
    md = fp.get("主卧方") or fp.get("master_dir")
    if md:
        tri = _dir_trigram(md)
        if tri:
            g = _grade(md)
            findings.append({
                "项": "主卧", "方位": md, "卦": tri, "评级": f"{g}方",
                "建议": ("主卧在吉方，利于休养与夫妻感情。"
                         if g == "吉" else
                         "主卧落凶方，宜用柔和灯光/浅色化解，床头避开凶位尖角。"
                         if g == "凶" else
                         "主卧落中平方位，注意安静与通风即可。"),
            })

    # 厨房（火）—— 宜在凶方以火压凶，忌在吉方泄吉
    kd = fp.get("厨房方") or fp.get("kitchen_dir")
    if kd:
        tri = _dir_trigram(kd)
        if tri:
            g = _grade(kd)
            findings.append({
                "项": "厨房/灶台", "方位": kd, "卦": tri,
                "评级": ("宜·凶方镇火" if g == "凶" else
                         "忌·泄吉气" if g == "吉" else "中"),
                "建议": ("厨房在凶方可火压凶，尚可；注意灶台远离水龙头，以黄/棕调和水火。"
                         if g == "凶" else
                         "厨房在吉方易火克泄吉位，建议多用土色(黄/棕)中和并保持通风。"
                         if g == "吉" else
                         "厨房落中平方位，正常使用，注意水火分隔。"),
            })

    # 卫生间（污）—— 宜在凶方镇凶，忌在吉方/中宫
    td = fp.get("卫生间方") or fp.get("toilet_dir")
    if td:
        tri = _dir_trigram(td)
        if tri:
            g = _grade(td)
            extra = "尤忌压中宫(房屋中心)，主全家气场紊乱。" if td == "中" else ""
            findings.append({
                "项": "卫生间", "方位": td, "卦": tri,
                "评级": ("宜·镇凶" if g == "凶" else
                         "忌·污泄吉" if g == "吉" else
                         "忌·压中宫" if td == "中" else "中"),
                "建议": ("卫生间在凶方以污镇凶，尚可；保持干燥、常关马桶盖。"
                         if g == "凶" else
                         "卫生间在吉方易污秽泄吉气，宜加强排风、挂天然葫芦/盐灯净化。"
                         if g == "吉" else
                         "卫生间落中平方位，保持洁净即可。") + extra,
            })

    # 缺角 —— 对应卦位成员/人事偏弱
    mc = fp.get("缺角") or fp.get("missing") or []
    if isinstance(mc, str):
        mc = [mc]
    for c in (mc or []):
        tri = _dir_trigram(c)
        who = _BAGUA_MEANING.get(tri, "") if tri else ""
        findings.append({
            "项": "缺角", "方位": c, "卦": tri or "?", "评级": "缺失",
            "建议": f"缺{c}角，对应{who}偏弱；宜在该方位补角（摆放对应五行物品/绿植/灯具引气）。",
        })

    # 横梁压顶
    if fp.get("横梁") or fp.get("beam"):
        findings.append({"项": "横梁压顶", "方位": "—", "卦": "—", "评级": "煞",
                         "建议": "避免床/沙发/餐桌正对横梁，可用吊顶包覆或挂葫芦化解。"})
    # 穿堂煞
    if fp.get("穿堂") or fp.get("through"):
        findings.append({"项": "穿堂煞", "方位": "—", "卦": "—", "评级": "煞",
                         "建议": "大门直对窗/阳台泄气，宜设玄关、屏风或绿植缓冲以聚气。"})

    return {
        "provided": True,
        "mode": "structured",
        "findings": findings,
        "summary": (f"共识别 {len(findings)} 项户型要素。"
                    + ("大门/功能房方位与坐向理气大体协调。"
                       if findings else "仅收到基础信息，建议补全户型要素以获得完整分析。")),
    }


# ─────────────────────────────────────────────────────────────
# 户型图视觉解析（多模态）：把图片解析为结构化 floor_plan dict
#   通过 OpenAI 兼容的视觉端点（chat/completions + vision）实现。
#   环境变量（均未配置时回退为 image_pending 占位）：
#     GEO_VISION_API_BASE  e.g. https://api.openai.com/v1
#     GEO_VISION_API_KEY
#     GEO_VISION_MODEL     e.g. gpt-4o-mini / qwen-vl / deepseek-vl 等
# ─────────────────────────────────────────────────────────────
_VISION_PROMPT = (
    "你是风水堪舆助手。请分析这张户型图/室内实景图，识别房屋要素，"
    "仅以 JSON 返回（不要解释、不要 markdown 代码块）：\n"
    '{\n'
    '  "门向": 大门开向(东/南/西/北/东南/西南/东北/西北/中 或 null),\n'
    '  "主卧方": 主卧所在方位或 null,\n'
    '  "厨房方": 厨房/灶台方位或 null,\n'
    '  "卫生间方": 卫生间方位或 null,\n'
    '  "缺角": [缺角方位列表],\n'
    '  "横梁": 是否有横梁压顶(bool),\n'
    '  "穿堂": 是否门对窗穿堂(bool)\n'
    "}"
)

_DIR_ALIAS = {
    "east": "东", "south": "南", "west": "西", "north": "北",
    "southeast": "东南", "southwest": "西南", "northeast": "东北",
    "northwest": "西北", "center": "中", "middle": "中", "中": "中",
}

_FP_KEY_ALIAS = {
    "门向": "门向", "door_dir": "门向", "door": "门向", "大门": "门向",
    "主卧方": "主卧方", "master_dir": "主卧方", "master": "主卧方", "主卧": "主卧方",
    "厨房方": "厨房方", "kitchen_dir": "厨房方", "kitchen": "厨房方", "厨房": "厨房方",
    "卫生间方": "卫生间方", "toilet_dir": "卫生间方", "toilet": "卫生间方",
    "卫生间": "卫生间方", "卫生间方位": "卫生间方",
    "缺角": "缺角", "missing": "缺角",
    "横梁": "横梁", "beam": "横梁",
    "穿堂": "穿堂", "through": "穿堂",
}


def _norm_dir(v):
    if not v:
        return None
    return _DIR_ALIAS.get(str(v).strip().lower(), str(v).strip())


def _to_image_url(ref: str) -> str:
    """把图片引用转成视觉端点可用的 image_url。

    - data URI：直用（已内联，最快、不依赖视觉端点跨网抓取）
    - http(s) URL：服务端先下载转 base64 data URI，避免视觉端点（如 dashscope）
      服务端去抓外链时因出网白名单/慢链路导致整体超时；下载失败则回退原样。
    - 本地路径：读文件转 base64
    - 其它：原样返回（可能失败，由上层捕获回退 image_pending）
    """
    if ref.startswith("data:"):
        return ref
    if ref.startswith(("http://", "https://")):
        try:
            import base64
            req = urllib.request.Request(ref, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                ctype = resp.headers.get_content_type() or "image/jpeg"
                b64 = base64.b64encode(resp.read()).decode("ascii")
            return f"data:{ctype};base64,{b64}"
        except Exception:
            return ref  # 下载失败回退原样（交由视觉端点尝试，再失败上层回退）
    if os.path.exists(ref):
        import base64, mimetypes
        mime = mimetypes.guess_type(ref)[0] or "image/jpeg"
        with open(ref, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    return ref  # 交给服务端，可能失败


def _vision_chat_json(base: str, key: str, model: str, image_ref: str, prompt: str) -> str:
    """调用 OpenAI 兼容视觉端点，返回模型文本（期望为 JSON）。"""
    import json
    import urllib.request

    url = f"{base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _to_image_url(image_ref)}},
            ],
        }],
        # 注：不强制 response_format=json_object，通义千问 VL 兼容模式下不一定接受，
        # 改为下游用正则逐级兜底提取首个 JSON 对象，跨厂商更稳。
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


def _normalize_vision_floorplan(content: str) -> dict:
    """从视觉模型输出中抽取并归一化为中文键的 floor_plan dict。

    兼容多种输出形态：纯 JSON / ```json 代码块 / 前后夹带解释文字 /
    markdown 包裹，逐级兜底提取首个 JSON 对象。
    """
    import json
    raw: dict = {}
    # 1) 整段即 JSON
    try:
        raw = json.loads(content)
    except Exception:
        raw = {}
    # 2) ```json ... ``` 代码块
    if not isinstance(raw, dict) or not raw:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
        if m:
            try:
                raw = json.loads(m.group(1))
            except Exception:
                raw = {}
    # 3) 非贪婪：首个 { ... }
    if not isinstance(raw, dict) or not raw:
        m = re.search(r"\{.*?\}", content, re.S)
        if m:
            try:
                raw = json.loads(m.group(0))
            except Exception:
                raw = {}
    # 4) 贪婪兜底
    if not isinstance(raw, dict) or not raw:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                raw = json.loads(m.group(0))
            except Exception:
                raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out: dict = {}
    for k, v in raw.items():
        nk = _FP_KEY_ALIAS.get(str(k)) or _FP_KEY_ALIAS.get(str(k).lower())
        if not nk:
            continue
        if nk in ("门向", "主卧方", "厨房方", "卫生间方"):
            out[nk] = _norm_dir(v)
        elif nk == "缺角":
            v = v if isinstance(v, list) else ([v] if v else [])
            out[nk] = [_norm_dir(x) for x in v]
        else:  # 横梁 / 穿堂
            out[nk] = bool(v)
    return out


def _vision_analyze_floor_plan(image_ref: str, ji: List[str], xiong: List[str]) -> Dict:
    """图片类户型图：走视觉模型解析；未配置或失败则回退 image_pending。

    配置读取自环境变量 GEO_VISION_API_BASE / GEO_VISION_API_KEY / GEO_VISION_MODEL。
    """
    base = os.environ.get("GEO_VISION_API_BASE", "").rstrip("/")
    key = os.environ.get("GEO_VISION_API_KEY", "")
    model = os.environ.get("GEO_VISION_MODEL", "gpt-4o-mini")
    if not (base and key):
        return {"provided": True, "mode": "image_pending",
                "note": "图片已接收，但未配置视觉模型(GEO_VISION_API_BASE/KEY)，"
                        "当前仅按坐向理气叠加结论。",
                "raw_hint": image_ref[:120]}
    try:
        content = _vision_chat_json(base, key, model, image_ref, _VISION_PROMPT)
        data = _normalize_vision_floorplan(content)
        inner = _analyze_floor_plan(data, ji, xiong)
        inner["mode"] = "vision"
        inner["vision_model"] = model
        inner["raw"] = content[:500]
        return inner
    except Exception as e:  # 任意异常均安全回退
        return {"provided": True, "mode": "image_pending",
                "note": f"视觉模型解析失败（{e}），回退为仅坐向理气结论。",
                "raw_hint": image_ref[:120]}


def geo_fengshui(orientation, gps: Dict = None, floor_plan=None) -> Dict:
    """风水堪舆（看空间）规则引擎：
      坐向(罗盘/24山) → 宅卦(八宅) → 四吉四凶方；叠加九宫绝对方位、GPS 峦头/磁偏角校正，
      以及户型图结构化峦头（形法）分析（大门/主卧/厨房/卫生间方位、缺角、横梁、穿堂）。

      注：图片类户型图走视觉模型解析（配置 GEO_VISION_* 后生效，未配置回退占位）；
           结构化 dict 直接进形法分析。
    """
    ori = _parse_orientation(orientation)
    house_tri = _MT_TO_TRIGRAM.get(ori["sitting_mountain"], "坎")
    ba = _BAZHAI.get(house_tri, {})

    # 八宅吉凶方（按绝对罗盘方位）
    mansions = []
    for d, star in ba.items():
        mansions.append({
            "dir": d, "trigram": _DIR_TO_TRIGRAM[d],
            "star": star, "lucky": star in _BAZHAI_JI,
        })
    ji = [m["dir"] for m in mansions if m["lucky"]]
    xiong = [m["dir"] for m in mansions if not m["lucky"]]

    # 九宫绝对方位（与坐向无关，作通用布局参考）
    jiu_gong = [{"dir": d, "trigram": tri, "note": _JIUGONG_NOTE[tri]}
                for d, tri in _DIR_TO_TRIGRAM.items()]
    jiu_gong.append({"dir": "中", "trigram": "中", "note": _JIUGONG_NOTE["中"]})

    # GPS：磁偏角校正 + 峦头占位
    geo_info = None
    if gps and isinstance(gps, dict) and "lat" in gps and "lon" in gps:
        lat, lon = float(gps["lat"]), float(gps["lon"])
        year = int(gps.get("year", datetime.date.today().year))
        decl = _magnetic_declination(lat, lon, year)
        bearing_true = (round((ori["bearing_mag"] + decl) % 360, 1)
                        if ori["bearing_mag"] is not None else None)
        geo_info = {
            "lat": lat, "lon": lon,
            "magnetic_declination": decl,
            "bearing_true_north": bearing_true,
            "luan_tou": "外部峦头需结合实地/地图（山形水势、路冲、邻栋），本引擎仅占位，建议配多模态识别。",
        }

    # 户型图：图片走视觉模型（未配置则占位），结构化 dict 走形法分析
    if isinstance(floor_plan, str):
        fp_analysis = _vision_analyze_floor_plan(floor_plan, ji, xiong)
    else:
        fp_analysis = _analyze_floor_plan(floor_plan, ji, xiong)

    advice = [
        f"本宅坐{ori['sitting_mountain']}向{ori['facing_mountain']}（{house_tri}宅），"
        f"吉方：{'、'.join(ji)}；凶方：{'、'.join(xiong)}。",
        "大门/主卧尽量落在吉方；灶台、卫生间避开凶方（尤其绝命、五鬼）。",
        "西北乾位忌压卫生间/杂物，若已压，挂天然葫芦+盐灯化解。",
        "灶台远离水龙头，以黄/棕色调和（土克水）。",
    ]

    return {
        "kind": "geo_fengshui",
        "orientation": ori,
        "house_trigram": house_tri,
        "east_west_zhai": "东四宅" if house_tri in ("坎", "离", "震", "巽") else "西四宅",
        "bagua_mansions": mansions,
        "lucky_dirs": ji,
        "unlucky_dirs": xiong,
        "jiu_gong": jiu_gong,
        "geo": geo_info,
        "floor_plan_analysis": fp_analysis,
        "advice": advice,
        "floor_plan_note": floor_plan,
        "disclaimer": "风水堪舆为传统人居环境文化，本结果为规则引擎演示，仅供娱乐与文化参考，不构成装修/人生决策依据。",
    }
