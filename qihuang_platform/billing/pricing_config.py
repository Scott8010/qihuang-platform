"""
计费中台定价配置（#474）— 价目「小账本」。

设计原则：代码只调 key，不读死数字。所有价目在此一处配置，
调价只需改本文件 commit 部署，不碰任何业务代码（老黄 2026-08-25 拍板）。

计量单位：积分（底层 = token，统一单一表，无双轨换算）。
  - 混合计量（三规则类 agent：compliance/fortune/geo）：每次必收固定基值(FLAT_CREDITS_PER_CALL)起步价，
    若本次实际走了 LLM（L2 语义层 / 象义层）再叠加 token × A（多模态 ×1.5）。
    即：实际计价 = 基本固定值 + LLM 调用费（老板 2026-08-26 拍板）。
  - 纯 LLM agent（其余）：无基值，直接 token × A（多模态 ×1.5）。

清零规则（两层）：
  - 基本包（套餐内含）：base_credits，按自然月清零
  - 叠加包（充值购买）：addon_credits，永久有效

钱包定位：加购层 — 调用先扣 base_credits，不足再扣 addon_credits。
"""
from __future__ import annotations

from typing import Dict, Any

# ──────────────────────────────────────────────────────────────
# 汇率 A（文本类基础汇率）
# ──────────────────────────────────────────────────────────────
# 双锚（老板拍板 + 成本侧重校）：
#   1 积分 = ¥0.05 ≈ 500 token（文本）；多模态 1 积分 ≈ 333 token（因 ×1.5）
# 覆盖最贵采购路由（GLM/Kimi 旗舰 ¥0.028/千token）留 72% 毛利，符合转售加成。
# 下限铁律：A 单价下限 ≥ ¥0.03/500token，防模型再涨价亏。
A_YUAN_PER_CREDIT: float = 0.05          # 1 积分 = ¥0.05
A_TOKENS_PER_CREDIT_TEXT: int = 500      # 文本：1 积分 ≈ 500 token
MULTIMODAL_FACTOR: float = 1.5           # 多模态上浮 50%

# 由 A 推导：1 token 文本消耗多少积分（= 1 / A_TOKENS_PER_CREDIT_TEXT）
CREDITS_PER_TEXT_TOKEN: float = 1.0 / A_TOKENS_PER_CREDIT_TEXT
CREDITS_PER_MULTIMODAL_TOKEN: float = CREDITS_PER_TEXT_TOKEN * MULTIMODAL_FACTOR


# ──────────────────────────────────────────────────────────────
# 基本包送积分（套餐档位 → 当月清 base_credits）
# ──────────────────────────────────────────────────────────────
# 体验版 300 / 标准版 1000 / 专业版 2000 / 企业版 3500（老板定死）
BASE_CREDITS_BY_PLAN: Dict[str, int] = {
    "trial": 300,
    "standard": 1000,
    "professional": 2000,
    "enterprise": 3500,
}
BASE_CREDITS_DEFAULT: int = 300  # 未知档位兜底


# ──────────────────────────────────────────────────────────────
# 叠加包（充值购买 → 永久有效 addon_credits）
# ──────────────────────────────────────────────────────────────
# 前=人民币¥，后=积分；量大单价自然递降 ¥0.05→¥0.044（老板钉死语义）
RECHARGE_PACKS: Dict[str, Dict[str, Any]] = {
    "pack_50":   {"yuan": 50,  "credits": 1000, "label": "标准充值包"},
    "pack_100":  {"yuan": 100, "credits": 2200, "label": "进阶充值包"},
    "pack_200":  {"yuan": 200, "credits": 4500, "label": "专业充值包"},
    "pack_500":  {"yuan": 500, "credits": 12000, "label": "企业充值包"},
}


# ──────────────────────────────────────────────────────────────
# 单加 Agent 月费（开门订阅费，权益维度，不含赠送积分）
# ──────────────────────────────────────────────────────────────
# 老板 2026-08-28 拍板（套餐定稿草案 · 六·6.3）：客户单独开通某 agent 的月度订阅入口。
#   文本类 ¥59/月 · 多模态类 ¥99/月；二者不含任何赠送积分（仅开调用权限的权益订阅费）。
#   开通后该 agent 调用即走积分池：消耗顺序严格先赠后充（同叠加包）。
# 注意：此价目此前只写在文档、未落代码常量 → 补进单一真源，调价只改本文件。
AGENT_ADDON_PRICE: Dict[str, int] = {
    "text": 59,        # 文本类 agent 月费（¥/月）
    "multimodal": 99,  # 多模态类 agent 月费（¥/月）
}


# ──────────────────────────────────────────────────────────────
# 三规则类 agent 固定基值（起步价，单位：积分）— 老板 2026-08-26 拍板
# ──────────────────────────────────────────────────────────────
# 混合计量模型（事件二）：这三个 agent 每次调用必收固定基值作起步价；
# 若本次实际走了 LLM（compliance 的 L2 语义层 / fortune 的 ai=True 象义层），
# 再叠加 token × 汇率。即：实际计价 = 基本固定值 + LLM 调用费。
#   - 0.1 元 = 2 积分（按 1 积分 = ¥0.05 推导），三类统一基值 2。
#   - geo 纯规则零 LLM：只收 2 积分起步价，不再上浮。
#   - 改本文件一行即调价（不碰业务代码）。
FLAT_CREDITS_PER_CALL: Dict[str, int] = {
    "compliance": 2,   # 内容合规审核：起步价 0.1元(2积分)；L2 语义层真调 LLM 时再叠加 token
    "fortune": 2,      # 命理运程：起步价 0.1元(2积分)；ai=True 象义层真调 LLM 时再叠加 token
    "geo": 2,          # 风水堪舆：起步价 0.1元(2积分)；纯规则零 LLM，仅收基值
}
# 未列出的 agent 一律视为调 LLM（uses_llm=True），走 token 计量。


def compute_credits(
    agent_key: str,
    token_used: int = 0,
    is_multimodal: bool = False,
    uses_llm: bool = True,
) -> int:
    """计算一次 agent 调用消耗的积分。

    混合计量模型（老板 2026-08-26 拍板）：
      - 三规则类 agent（在 FLAT_CREDITS_PER_CALL 中）：必收固定基值作起步价；
        若本次实际走了 LLM，再叠加 token × 汇率（多模态 ×1.5）。
        即：实际计价 = 基本固定值 + LLM 调用费。
      - 纯 LLM agent（其余）：无基值，直接 token × 汇率。

    token 部分向上取整（0 token 时不叠加）；整笔保底为基值（已含）+ 叠加。
    """
    base = FLAT_CREDITS_PER_CALL.get(agent_key, 0)  # 三规则类起步价；其余为 0
    if not uses_llm:
        return max(base, 1)  # 没走 LLM：只收起步价；未配置起步价的 agent 兜底 1 积分
    rate = CREDITS_PER_MULTIMODAL_TOKEN if is_multimodal else CREDITS_PER_TEXT_TOKEN
    extra = max(0, int(token_used * rate + 0.999))  # 向上取整，0 token 时不加
    return base + extra


def get_base_credits(plan_id: str) -> int:
    """套餐档位 → 基本包赠送积分（当月清）。"""
    return BASE_CREDITS_BY_PLAN.get((plan_id or "").lower(), BASE_CREDITS_DEFAULT)


def get_pack(pack_key: str) -> Dict[str, Any] | None:
    """充值包查询。"""
    return RECHARGE_PACKS.get(pack_key)
