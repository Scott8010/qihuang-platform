"""
种子生成器：把 hb-compliance-guard 的 32 条规则反演为权威合规条款（L1 底座种子）。

运行：python build_seed.py
  - 从 COMPLIANCE_RULES_PATH（默认 HealthBridge guard/rules.py）读 RULES
  - 反演为 ComplianceClause，写入 seed/compliance_clauses.jsonl
  - 这是「横向建库标准范式」的首次落地：规则(判定式) -> 条款(权威溯源)，可复核可演化

之后再增条款，直接往 rules.py 加规则或手工追加 jsonl 即可；kg_id 由 clause_id 确定性派生。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(__file__)
_RULES_PATH = os.getenv(
    "COMPLIANCE_RULES_PATH",
    r"C:/Users/Administrator/WorkBuddy/HealthBridge/hb-compliance-guard/rules.py",
)
_OUT = os.path.join(_HERE, "compliance_clauses.jsonl")

# 将项目根（含 qihuang_platform 包）与规则文件所在目录加入 sys.path，使其自包含可运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(_RULES_PATH))

# 动态加载 rules 模块（避免与包命名冲突）
spec = importlib.util.spec_from_file_location("hb_guard_rules", _RULES_PATH)
_rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_rules)

from qihuang_platform.agent.compliance.kb import rules_to_clauses  # noqa: E402


def main():
    rules = _rules.RULES
    clauses = rules_to_clauses(rules)
    os.makedirs(_HERE, exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        for c in clauses:
            f.write(__import__("json").dumps(c.model_dump(), ensure_ascii=False) + "\n")
    print(f"已生成 {len(clauses)} 条合规条款 -> {_OUT}")
    # 简单统计
    by_cat: dict[str, int] = {}
    for c in clauses:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    print("按类分布:", by_cat)


if __name__ == "__main__":
    main()
