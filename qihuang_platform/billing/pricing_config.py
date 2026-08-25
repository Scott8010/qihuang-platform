"""
计费中台定价配置（#474）— 价目「小账本」。

设计原则：代码只调 key，不读死数字。所有价目在此一处配置，
调价只需改本文件 commit 部署，不碰任何业务代码（老黄 2026-08-25 拍板）。

计量单位：积分（底层 = token，统一单一表，无双轨换算）。
  - 调 LLM 的 agent：消耗积分 = token × A（文本）/ token × A × 1.5（多模态）
  - 不调 LLM 的 agent：消耗积分 = flat_credits_per_call（固定积分/次，见下方）

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
    "pack_500":  {"yuan": 500, "credits": 8800, "label": "企业充值包"},
}


# ──────────────────────────────────────────────────────────────
# 不调 LLM 的 agent — 固定积分/次（老板 2026-08-25 拍板：3~5 分，金虎拿捏）
# ──────────────────────────────────────────────────────────────
# 设计意图：这些 agent 默认走规则引擎、不消耗 token，但消耗算力/DB/规则资源，必须计价（老板硬约束）。
# ⚠️ 实测坑（代码核查 2026-08-25）：compliance 有 L2 LLM 语义层、fortune 有可选 ai=True LLM 象义层——
#   这俩的 LLM 层一旦开启，只收固定积分会少算真实 token 成本。当前（默认关闭）按固定积分收合理；
#   若启用 LLM 层，应升级为「固定积分 + 实际 token 增量」混合计量（#474 延伸，待排期）。
# geo 为真正纯规则引擎（代码零 LLM 调用），固定积分无歧义。
# 数值：geo=3（最便宜）/ fortune=4 / compliance=5（L2 风险最高）。改本文件一行即调。
FLAT_CREDITS_PER_CALL: Dict[str, int] = {
    "compliance": 5,   # 内容合规审核：L0/L1 正则+检索，L2 语义层会真调 LLM（命中模糊违规），风险最高
    "fortune": 4,      # 命理运程：默认 ai=False 纯规则保底；ai=True 挂 LLM 象义层才烧 token
    "geo": 3,          # 风水堪舆：纯规则引擎，代码零 LLM 调用（最便宜）
}
# 未列出的 agent 一律视为调 LLM（uses_llm=True），走 token 计量。


def compute_credits(
    agent_key: str,
    token_used: int = 0,
    is_multimodal: bool = False,
    uses_llm: bool = True,
) -> int:
    """计算一次 agent 调用消耗的积分（向上取整，最少 1 积分）。

    - 调 LLM：token × A（多模态 ×1.5）
    - 不调 LLM：flat_credits_per_call 固定值
    """
    if not uses_llm:
        return FLAT_CREDITS_PER_CALL.get(agent_key, 1)
    rate = CREDITS_PER_MULTIMODAL_TOKEN if is_multimodal else CREDITS_PER_TEXT_TOKEN
    raw = token_used * rate
    return max(1, int(raw + 0.999))  # 向上取整，保底 1 积分


def get_base_credits(plan_id: str) -> int:
    """套餐档位 → 基本包赠送积分（当月清）。"""
    return BASE_CREDITS_BY_PLAN.get((plan_id or "").lower(), BASE_CREDITS_DEFAULT)


def get_pack(pack_key: str) -> Dict[str, Any] | None:
    """充值包查询。"""
    return RECHARGE_PACKS.get(pack_key)
