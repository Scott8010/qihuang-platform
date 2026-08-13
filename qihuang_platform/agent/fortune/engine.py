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

免责：所有输出均为传统文化娱乐参考，不作医疗 / 投资 / 人生决策依据。
"""
from __future__ import annotations

import datetime
import random
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
# 八字排盘
# ═══════════════════════════════════════════════════════════════
def bazi_profile(pillars) -> Dict:
    ps = parse_pillars(pillars)
    year, month, day, hour = ps
    day_gan = day[0]
    dwx = GAN_WX[day_gan]

    # 五行统计（天干 + 地支本气）
    count = {w: 0 for w in WX}
    for p in ps:
        count[GAN_WX[p[0]]] += 1
        count[ZHI_BEN[p[1]]] += 1

    # 十神（年干、月干、时干相对日干；日支本气亦列）
    tenshen = {
        "年干": shishen(day_gan, year[0]),
        "月干": shishen(day_gan, month[0]),
        "时干": shishen(day_gan, hour[0]),
        "日支": shishen(day_gan, ZHI_BEN_GAN[day[1]]),
    }

    # 身强身弱打分（传统经验启发式，可随样本调参）
    score = 0.0
    month_zhi_wx = ZHI_BEN[month[1]]
    if month_zhi_wx == dwx or month_zhi_wx == _sheng_wo(dwx):
        score += 2.0          # 得令（比劫月令 / 印月令）
    elif month_zhi_wx in (SHENG[dwx], KE[dwx], _ke_wo(dwx)):
        score -= 1.0          # 失令（食伤/财/官杀月令，泄耗日主）
    # 根：日支为日主自坐强根权重最高，余支本气次之，藏干余气轻
    for i, p in enumerate(ps):
        if ZHI_BEN[p[1]] == dwx:
            score += 3.0 if i == 2 else 1.5     # 日支(座位)强根
        elif dwx in ZHI_HIDDEN[p[1]][1:]:
            score += 0.5
    # 帮身天干（比肩/劫财透干）
    for g in (year[0], month[0], hour[0]):
        if GAN_WX[g] == dwx:
            score += 1.0
    strength = "身强" if score >= 3 else ("身弱" if score <= 1.5 else "中和")

    # 喜用神
    if strength == "身强":
        xi = [_ke_wo(dwx), SHENG[dwx], KE[dwx]]   # 官杀 / 食伤 / 财
        ji = [_sheng_wo(dwx), dwx]               # 印 / 比劫
    else:
        xi = [_sheng_wo(dwx), dwx]               # 印 / 比劫
        ji = [_ke_wo(dwx), SHENG[dwx], KE[dwx]]
    xi = list(dict.fromkeys(xi))
    ji = list(dict.fromkeys(ji))

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


def liuyao(method: str = "coin", question: str = "", seed_key: str = None) -> Dict:
    if method == "time":
        # 时间卦：以当前时辰干支扰动随机种子，保证"同时问近似同局"
        now = datetime.datetime.now()
        random.seed((now.year * 372 + now.month * 31 + now.day) ^ (now.hour * 7))
    lines = [_coin() for _ in range(6)]
    ben, bian, dyn = _lines_to_hex(lines)
    yang_line = [v in (7, 9) for v in lines]
    result = {
        "method": method,
        "question": question,
        "lines": [{"value": v, "yang": yang_line[i], "old": v in (6, 9)} for i, v in enumerate(lines)],
        "ben_gua": ben,
        "bian_gua": bian,
        "changing_lines": dyn,
        "is_static": len(dyn) == 0,
    }
    # 趣味解析（模板，不含真实占断）
    if dyn:
        result["reading"] = f"本卦【{ben}】，第{'、'.join(map(str, dyn))}爻发动，事态演变趋于【{bian}】。"
    else:
        result["reading"] = f"本卦【{ben}】，六爻俱静，事象稳定，宜守不宜攻。"
    result["reading"] += "（趣味解析，仅供娱乐参考）"
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


def daily_sign(date: datetime.date = None, favorable: List[str] = None,
               unfavorable: List[str] = None) -> Dict:
    date = date or datetime.date.today()
    dg = day_ganzhi(date)
    dgan, dzhi = dg[0], dg[1]
    dwx = GAN_WX[dgan]
    fav = favorable or []
    unfav = unfavorable or []

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
    return {
        "year": year,
        "year_ganzhi": yg,
        "day_master": prof["day_master"],
        "strength": prof["strength"],
        "favorable": fav,
        "unfavorable": prof["unfavorable"],
        "liunian_relation": rel,
        "advice": {
            "重点五行": advice_wx or fav,
            "宜": "补水金土相关行业/人际；借伙伴之力推进。",
            "忌": "单打独斗、冲动投资、与人争功。",
        },
        "disclaimer": "传统文化娱乐参考，不作为医疗/投资/人生决策依据。",
    }
