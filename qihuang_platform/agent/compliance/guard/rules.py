"""hb-compliance-guard 规则库 — 32 条内容合规规则（A~F 六大类）。

分类契约（与颐掌柜HB中台对接手册一致）：
  A 夸大/绝对化用语      —— 《广告法》第九条
  B 疗效/功效承诺        —— 《广告法》第十七/二十八条、《医疗广告管理办法》
  C 医疗用语越界        —— 非医疗机构不得使用诊疗类表述
  D 虚假描述/无依据数据  —— 《广告法》第二十八条（虚假广告）
  E 缺失禁忌/风险提示    —— 中医调理类服务安全底线
  F 敏感/违禁表述        —— 涉及特殊人群、违禁成分、迷信

严重度：RED（硬违规，拦截）/ ORANGE（高风险，建议整改）/ YELLOW（提示，人工确认）
处置：block（禁止上架）/ advise（建议修改）
"""
from __future__ import annotations

import re
from typing import Any

# 全局免责/否定语境豁免词：命中片段处于此类语境时不算违规。
# 例：「本品不能替代药物」「不作为医疗诊断依据」—— 这些恰恰是合规必备的声明，不能反过来判罚。
GLOBAL_EXEMPT_CONTEXT: tuple[str, ...] = (
    "不能替代", "不可替代", "不能代替", "不得替代",
    "不作为", "不构成", "不属于", "不视为",
    "非医疗", "非药品", "不是药", "不能治疗",
    "仅供参考", "仅作参考", "不得宣称", "禁止宣称", "不宜宣称",
    "请勿", "切勿", "避免使用",
)

# 每条规则：
#   rule_id / category / severity / effective_action / confidence
#   patterns: 正则列表（已用 re.escape 处理的字面量或手写正则）
#   title: 违规理由（给运营看的人话 + 法条）
#   suggested_replace: 整改建议
RULES: list[dict[str, Any]] = [
    # ==================== A 夸大/绝对化用语（8 条） ====================
    {
        "rule_id": "HC-A-001", "category": "A", "severity": "RED",
        "effective_action": "block", "confidence": 0.98,
        # 「第一」类：用「限定词 + 第一」的组合式正则覆盖，避免漏掉「全国第一/销量全国第一」等变体；
        # 同时不裸匹配「第一」二字，规避「第一次/第一步/第一家门店」等事实性表述的误伤。
        "patterns": [
            # 后置否定：排除「全国第一次/第一届/第一批」等事实性时序表述
            r"(?:全国|全网|全球|全省|全市|行业|业内|国内|国际|世界|市场|销量|口碑|排名|中国|亚洲)"
            r"第一(?!次|步|时间|届|阶段|批|轮|季|天|年|月|周|版|集|课|讲|章|节|站)",
            r"第一品牌",
            r"第一[的之]?(?:选择|名)",
        ],
        "title": "「第一」类绝对化用语，违反《广告法》第九条第(三)项（禁止使用国家级、最高级、最佳等用语）",
        "suggested_replace": "删除排名表述，改为客观描述，如「专注XX领域的品牌」",
    },
    {
        "rule_id": "HC-A-002", "category": "A", "severity": "RED",
        "effective_action": "block", "confidence": 0.97,
        "patterns": [r"最好的", r"最佳", r"最优", r"最有效", r"最强", r"最权威", r"最安全"],
        "title": "「最」字类绝对化用语，违反《广告法》第九条第(三)项",
        "suggested_replace": "删除「最」字表述，改为「较为适合」「广受认可」等相对描述",
    },
    {
        "rule_id": "HC-A-003", "category": "A", "severity": "RED",
        "effective_action": "block", "confidence": 0.96,
        "patterns": [r"国家级", r"国家指定", r"国家认证", r"央视推荐", r"国宴专用"],
        "title": "冒用国家级背书，违反《广告法》第九条第(二)项（不得使用国家机关名义）",
        "suggested_replace": "删除国家级背书表述；确有资质请标注具体证书编号",
    },
    {
        "rule_id": "HC-A-004", "category": "A", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.9,
        "patterns": [r"唯一", r"独家", r"首选", r"顶级", r"极致", r"世界领先", r"销量领先"],
        "title": "准绝对化用语，缺乏可验证依据时构成误导",
        "suggested_replace": "删除或补充可核验依据（如第三方检测报告、销售数据来源）",
    },
    {
        "rule_id": "HC-A-005", "category": "A", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.9,
        "patterns": [r"无任何副作用", r"绝无副作用", r"零副作用", r"无任何风险", r"绝对安全"],
        "title": "「无副作用」绝对化表述，中药材与调理手法存在个体差异，属误导性宣传",
        "suggested_replace": "改为「本方剂性味平和，具体适用请咨询门店中医师」并补充禁忌提示",
    },
    {
        "rule_id": "HC-A-006", "category": "A", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.88,
        # 含两族：①无差异适用宣称 ②对孕妇/哺乳期/婴幼儿等禁忌人群的「安全性宣称」。
        # 后者是重罚区：孕妇为最高敏感人群，声称「也能用/可放心用」等同于替代医嘱做安全背书。
        "patterns": [
            r"适合所有人", r"人人适用", r"老少皆宜", r"全民适用",
            r"任何人(?:都|均)(?:能|可)(?:用|服用|食用|饮用)",
            # 间隔字符集排除「不/禁/忌/慎/避/勿/须」：否则「孕妇不能用」「孕妇及糖尿病患者慎用」
            # 这类正确的警示语会被反向判成违规——免责/禁忌提示被罚是运营最不能忍的误报。
            r"(?:孕妇|孕期|哺乳期|备孕|婴幼儿|新生儿)[^。；;，,不禁忌慎避勿须]{0,6}"
            r"(?:也?[能可](?:以)?(?:用|服用|食用|饮用|喝)|可放心|放心(?:用|服用|食用|饮用)|无需忌口)",
        ],
        "title": "适用人群绝对化 / 对孕妇等禁忌人群作安全性宣称，忽视禁忌风险",
        "suggested_replace": "明确适宜人群，并标注不适宜人群（孕妇、婴幼儿、慢病患者等）；禁忌人群一律改为「请遵医嘱」",
    },
    {
        "rule_id": "HC-A-007", "category": "A", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.86,
        "patterns": [r"一次[见有]效", r"立竿见影", r"当天见效", r"终身受益", r"永不复发"],
        "title": "效果时效性绝对化承诺，属不可验证的夸大宣传",
        "suggested_replace": "删除时效承诺，改为「坚持调理有助于逐步改善」",
    },
    {
        "rule_id": "HC-A-008", "category": "A", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.85,
        "patterns": [r"祖传秘方", r"宫廷秘方", r"独门秘方", r"祖传绝技"],
        "title": "「祖传秘方」属含糊不实表述，来源与真实性无法验证",
        "suggested_replace": "改为「传统中医配方」或标明具体方剂名（如参苓白术散加减）",
    },

    # ==================== B 疗效/功效承诺（8 条） ====================
    {
        "rule_id": "HC-B-011", "category": "B", "severity": "RED",
        "effective_action": "block", "confidence": 0.98,
        "patterns": [r"包治百病", r"药到病除", r"根治", r"彻底治愈", r"保证治愈", r"治愈率"],
        "title": "疗效承诺用语，中医调理服务不得承诺治疗效果，违反《医疗广告管理办法》第七条",
        "suggested_replace": "改为辅助调理类表述，如「辅助改善、日常调理」，不承诺结果",
    },
    {
        "rule_id": "HC-B-012", "category": "B", "severity": "RED",
        "effective_action": "block", "confidence": 0.96,
        "patterns": [r"有效率[高达]*\s*\d+%", r"\d+%\s*有效", r"治愈率\s*\d+", r"成功率\s*\d+%"],
        "title": "量化疗效数据承诺，无临床依据不得宣称，违反《广告法》第二十八条",
        "suggested_replace": "删除具体数字，改为「多数顾客反馈调理后有所改善」",
    },
    {
        "rule_id": "HC-B-013", "category": "B", "severity": "RED",
        "effective_action": "block", "confidence": 0.95,
        "patterns": [r"抗癌", r"防癌", r"治癌", r"抑制肿瘤", r"杀死癌细胞"],
        "title": "涉癌宣称属严重违规，普通食品与调理服务一律禁止",
        "suggested_replace": "全部删除涉癌表述，不得以任何形式暗示抗肿瘤功效",
    },
    {
        "rule_id": "HC-B-014", "category": "B", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.92,
        "patterns": [r"增强免疫力", r"提高免疫力", r"抗衰老", r"延缓衰老", r"改善睡眠", r"缓解疲劳", r"辅助降[血]*[糖脂压]"],
        "title": "保健功能宣称属保健食品专属，普通食品/服务不得宣称（《食品安全法》第七十三条）",
        "suggested_replace": "取得保健食品批文后方可宣称；否则改为「日常滋补的健康选择」",
    },
    {
        "rule_id": "HC-B-015", "category": "B", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.9,
        "patterns": [r"吃\s*[一二三四五六七八九十\d]+\s*[个]*[天周月疗]", r"[一二三四五六七八九十\d]+\s*天见效", r"[一二三四五六七八九十\d]+\s*个疗程"],
        "title": "对食用/调理效果做具体时间承诺，属功效承诺",
        "suggested_replace": "删除具体时间承诺，改为「坚持调理有助于日常养护」",
    },
    {
        "rule_id": "HC-B-016", "category": "B", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.88,
        "patterns": [r"替代药物", r"停药", r"不用吃药", r"告别药物", r"代替西药"],
        "title": "暗示可替代药物治疗，可能延误就医，构成重大健康风险",
        "suggested_replace": "补充「本品/本服务不能替代药物，疾病请及时就医」",
    },
    {
        "rule_id": "HC-B-017", "category": "B", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.85,
        "patterns": [r"排毒", r"清宿便", r"净化血液", r"排出毒素"],
        "title": "「排毒」类伪科学功效宣称，无医学定义支撑",
        "suggested_replace": "改为「促进代谢/帮助消化」等有依据的表述",
    },
    {
        "rule_id": "HC-B-018", "category": "B", "severity": "YELLOW",
        "effective_action": "advise", "confidence": 0.7,
        "patterns": [r"调理[好痊]", r"改善明显", r"效果显著", r"效果特别好"],
        "title": "效果描述主观且缺少客观评估依据",
        "suggested_replace": "改为可量化描述（如「体质评估量表评分由7分降至4分」）",
    },

    # ==================== C 医疗用语越界（5 条） ====================
    {
        "rule_id": "HC-C-021", "category": "C", "severity": "RED",
        "effective_action": "block", "confidence": 0.95,
        "patterns": [r"诊断", r"确诊", r"临床治疗", r"开[具处]方", r"处方药"],
        "title": "非医疗机构使用诊疗类表述，违反《医疗机构管理条例》",
        "suggested_replace": "改为「体质辨识」「调理建议」，明确非医疗诊断行为",
    },
    {
        "rule_id": "HC-C-022", "category": "C", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.9,
        "patterns": [r"治疗", r"疗法", r"医治", r"主治", r"适应症"],
        "title": "医疗行为表述，健康调理门店不具备诊疗资质",
        "suggested_replace": "改为「调理」「养护方案」，避免「治疗」类词汇",
    },
    {
        "rule_id": "HC-C-023", "category": "C", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.88,
        "patterns": [r"消炎", r"抗菌", r"杀菌", r"镇痛", r"退烧", r"降压药"],
        "title": "药理作用宣称，非药品不得使用",
        "suggested_replace": "删除药理表述，改为「有助于舒缓不适感」",
    },
    {
        "rule_id": "HC-C-024", "category": "C", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.85,
        "patterns": [r"专家坐诊", r"名医", r"主任医师", r"教授亲诊"],
        "title": "医师身份宣称需具备执业资质并公示，否则构成虚假宣传",
        "suggested_replace": "标注技师真实资质（如「持推拿按摩师资格证」），或删除医师表述",
    },
    {
        "rule_id": "HC-C-025", "category": "C", "severity": "YELLOW",
        "effective_action": "advise", "confidence": 0.7,
        "patterns": [r"病症", r"疾病", r"患者", r"病人"],
        "title": "疾病相关表述，建议改用健康管理口径",
        "suggested_replace": "改为「亚健康状态」「顾客」等非医疗语境词汇",
        # 出现在禁忌/慎用提示中的「患者」属于必要风险告知，不应判罚
        "exempt_context": ["慎用", "禁忌", "不宜", "不适宜", "忌用", "遵医嘱", "请就医", "咨询医师"],
    },

    # ==================== D 虚假描述/无依据数据（5 条） ====================
    {
        "rule_id": "HC-D-031", "category": "D", "severity": "RED",
        "effective_action": "block", "confidence": 0.93,
        "patterns": [r"权威认证", r"机构指定", r"协会认证", r"官方唯一"],
        "title": "无可核验来源的权威背书，属虚假宣传（《广告法》第二十八条）",
        "suggested_replace": "补充可核验的认证机构全称与证书编号，否则删除",
    },
    {
        "rule_id": "HC-D-032", "category": "D", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.87,
        "patterns": [r"[百千万亿]+\s*[位名]*\s*[用顾客户女男]", r"\d+\s*万\s*[用顾]", r"数十万", r"上百万"],
        "title": "用户规模数据缺乏可验证依据",
        "suggested_replace": "无权威数据则删除，或改为「深受消费者喜爱」",
    },
    {
        "rule_id": "HC-D-033", "category": "D", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.85,
        "patterns": [r"专家推荐", r"医生推荐", r"权威推荐", r"名人代言"],
        "title": "医疗、保健类广告不得利用专家或消费者名义作推荐（《广告法》第十六/十八条）",
        "suggested_replace": "删除推荐表述；如为真实科普作者请标注姓名与职务",
    },
    {
        "rule_id": "HC-D-034", "category": "D", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.83,
        "patterns": [r"名额有限", r"仅剩\s*\d+", r"先到先得", r"限时\s*\d*\s*[天小时]", r"最后\s*\d+\s*[天名]"],
        "title": "促销紧迫感话术，如无实际限制构成诱导性虚假宣传",
        "suggested_replace": "确有名额/时限请标注具体数量与截止时间，否则删除",
    },
    {
        "rule_id": "HC-D-035", "category": "D", "severity": "YELLOW",
        "effective_action": "advise", "confidence": 0.72,
        "patterns": [r"进口原料", r"道地药材", r"有机", r"纯天然", r"零添加"],
        "title": "原料品质宣称需具备相应证明文件",
        "suggested_replace": "补充产地证明/有机认证编号，否则改为一般性描述",
    },

    # ==================== E 缺失禁忌/风险提示（3 条） ====================
    {
        "rule_id": "HC-E-041", "category": "E", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.85,
        "patterns": [r"拔罐", r"刮痧", r"艾灸", r"针灸", r"放血"],
        "title": "侵入性/热力类调理项目须标注禁忌症（皮肤破损、凝血障碍、孕妇等）",
        "suggested_replace": "补充「禁忌：皮肤破损处、凝血功能障碍者、孕妇腰骶部禁用」",
        "requires_missing": ["禁忌", "不适宜", "慎用", "孕妇"],
    },
    {
        "rule_id": "HC-E-042", "category": "E", "severity": "YELLOW",
        "effective_action": "advise", "confidence": 0.75,
        "patterns": [r"儿童", r"小儿", r"婴幼儿", r"宝宝"],
        "title": "涉及未成年人的调理项目须标注年龄区间与家长陪同要求",
        "suggested_replace": "补充适用年龄段、须监护人陪同及异常反应处理提示",
        "requires_missing": ["监护", "陪同", "禁忌", "岁以下", "不适宜", "慎用"],
    },
    {
        "rule_id": "HC-E-043", "category": "E", "severity": "YELLOW",
        "effective_action": "advise", "confidence": 0.7,
        "patterns": [r"食疗", r"药膳", r"茶饮", r"膏方", r"代茶饮"],
        "title": "食疗类内容建议补充「不能替代医疗手段」的风险提示",
        "suggested_replace": "补充「以上为日常饮食建议，不能替代医疗手段，症状明显请就医」",
        "requires_missing": ["不能替代", "请就医", "咨询医师", "遵医嘱"],
    },

    # ==================== F 敏感/违禁表述（3 条） ====================
    {
        "rule_id": "HC-F-051", "category": "F", "severity": "RED",
        "effective_action": "block", "confidence": 0.96,
        "patterns": [r"壮阳", r"丰胸", r"减肥\s*\d+\s*斤", r"催情", r"性功能"],
        "title": "涉及特殊功效的违禁宣称，属重点监管禁区",
        "suggested_replace": "全部删除，此类宣称不得出现在任何平台物料中",
    },
    {
        "rule_id": "HC-F-052", "category": "F", "severity": "RED",
        "effective_action": "block", "confidence": 0.94,
        "patterns": [r"何首乌", r"朱砂", r"雄黄", r"马兜铃", r"关木通", r"细辛\s*\d+\s*[克g]"],
        "title": "涉及肝肾毒性或用量严格管控的药材，不得在面向消费者的物料中随意出现",
        "suggested_replace": "删除该药材表述；确需使用请由执业中医师开方并单独告知风险",
    },
    {
        "rule_id": "HC-F-053", "category": "F", "severity": "ORANGE",
        "effective_action": "advise", "confidence": 0.86,
        "patterns": [r"转运", r"改命", r"风水", r"辟邪", r"符咒", r"开光"],
        "title": "封建迷信内容，违反《广告法》第九条第(八)项",
        "suggested_replace": "删除迷信表述，改为传统文化科普口径",
    },
]

CATEGORY_LABELS = {
    "A": "夸大/绝对化用语",
    "B": "疗效/功效承诺",
    "C": "医疗用语越界",
    "D": "虚假描述/无依据数据",
    "E": "缺失禁忌/风险提示",
    "F": "敏感/违禁表述",
}

SEVERITY_ORDER = {"RED": 0, "ORANGE": 1, "YELLOW": 2}

# 预编译，避免每次扫描重复编译
_COMPILED: list[tuple[dict, list[re.Pattern]]] = [
    (rule, [re.compile(p) for p in rule["patterns"]]) for rule in RULES
]


def compiled_rules() -> list[tuple[dict, list[re.Pattern]]]:
    return _COMPILED


def rule_count() -> int:
    return len(RULES)


def category_stats() -> dict[str, int]:
    stats: dict[str, int] = {}
    for r in RULES:
        stats[r["category"]] = stats.get(r["category"], 0) + 1
    return stats
