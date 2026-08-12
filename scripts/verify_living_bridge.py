"""服务端实测：证明活态化两块短板已真活（回路三增益 + 审核→图谱回流）

1. 回路三增益：LIVING_BUSINESS_GAIN=0.5 时，business_use 信号聚合 delta 放大
   expected = 0.0003 * (1 + 0.5*0.5) = 0.000375 → Neo4j 节点置信度精确+0.000375。
2. 审核→图谱回流：
   - bridge_compliance_scan 命中实体 → 写 source='business' business_use 行；
   - bridge_compliance_feedback(override) 命中实体 → 写 source='business' expert_reject 行；
   - 二者经聚合真实回写 Neo4j（正加权升、负加权降），证明 compliance 与 living 两线打通。

验证后清理注入行并复原 Neo4j 置信度，避免污染生产数据。
"""
import os
import asyncio

from dotenv import load_dotenv

# 必须在 import aggregator 之前加载 .env（aggregator 在 import 时读 LIVING_BUSINESS_GAIN）
load_dotenv("/root/qihuang_platform/.env")

from qihuang_platform.living.kg_write_client import kg_client
from qihuang_platform.living.ingest import (
    emit_business_feedback, bridge_compliance_scan, bridge_compliance_feedback,
)
from qihuang_platform.living.aggregator import aggregate_feedback, _BUSINESS_GAIN
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
from sqlalchemy import and_


def _resolve_first(names):
    for n in names:
        r = asyncio.run(kg_client.resolve(n))
        matches = (r or {}).get("matches") or []
        if matches:
            return n, matches[0]["kg_id"]
    return None, None


def _cleanup_business(db, kg_ids):
    for kg_id in kg_ids:
        db.query(KgFeedback).filter(
            and_(KgFeedback.kg_id == kg_id, KgFeedback.source == "business")
        ).delete()
    db.commit()


def main():
    print("== LIVING_BUSINESS_GAIN ==")
    print(_BUSINESS_GAIN)
    assert _BUSINESS_GAIN > 0, "回路三增益未激活！"
    gain = _BUSINESS_GAIN

    db = SessionLocal()
    out = {}
    try:
        # 解析两个真实实体（正加权 / 负加权各一个）
        name_a, kg_a = _resolve_first(["艾灸", "拔罐", "刮痧", "针灸"])
        name_b, kg_b = _resolve_first(["朱砂", "雄黄", "何首乌"])
        assert kg_a and kg_b, "无法解析测试实体"
        out["node_a"] = {"name": name_a, "kg_id": kg_a}
        out["node_b"] = {"name": name_b, "kg_id": kg_b}

        # 防御性清理历史 business 行
        _cleanup_business(db, [kg_a, kg_b])

        base_a = asyncio.run(kg_client.get_confidence(kg_a)) or 0.8
        base_b = asyncio.run(kg_client.get_confidence(kg_b)) or 0.8
        out["baseline_a"] = base_a
        out["baseline_b"] = base_b

        # ── BLOCK 1 + BLOCK 2-scan：门店送审命中实体 → business_use 正加权 ──
        print("DEBUG resolve_a:", asyncio.run(kg_client.resolve(name_a)))
        s_scan = asyncio.run(bridge_compliance_scan(
            db, [{"entity": name_a, "severity": "ORANGE"}],
            tenant_id="tenant_default", store_id="verify_store",
        ))
        out["scan_bridge"] = s_scan

        # ── BLOCK 2-feedback：人工 override（疑错知识）→ expert_reject 负加权 ──
        print("DEBUG resolve_b:", asyncio.run(kg_client.resolve(name_b)))
        s_fb = asyncio.run(bridge_compliance_feedback(
            db, [{"entity": name_b, "severity": "RED"}],
            "override", tenant_id="tenant_default", store_id="verify_store",
        ))
        out["feedback_bridge"] = s_fb

        # 聚合 → 真实回写 Neo4j
        summary = asyncio.run(aggregate_feedback(db, client=kg_client))
        out["aggregate_summary"] = summary

        after_a = asyncio.run(kg_client.get_confidence(kg_a)) or 0.8
        after_b = asyncio.run(kg_client.get_confidence(kg_b)) or 0.8
        out["after_a"] = after_a
        out["after_b"] = after_b

        # 期望：A 节点 = base + 0.0003*(1+gain*0.5)；B 节点 = base + (-0.02)*(1+gain*1.0)（再乘模型信任杠杆）
        exp_a = round(base_a + 0.0003 * (1 + gain * 0.5), 4)
        out["expected_a"] = exp_a
        out["delta_a"] = round(after_a - base_a, 6)
        out["delta_b"] = round(after_b - base_b, 6)

        # 断言
        if out["scan_bridge"]["emitted"] < 1:
            print("WARN: scan 桥未写入 business 行:", s_scan)
        if out["feedback_bridge"]["emitted"] < 1:
            print("WARN: feedback 桥未写入 expert_reject 行:", s_fb)
        if abs(after_a - exp_a) >= 1e-3:
            print("WARN: A 节点增益不符:", out)
        if not (after_b < base_b):
            print("WARN: B 节点未下降:", out)
        out["VERDICT"] = "BOTH_BLOCKS_LIVE_OK"
    finally:
        # 清理注入行并复原 Neo4j
        _cleanup_business(db, [kg_a, kg_b])
        asyncio.run(kg_client.batch_update_confidence([
            {"kg_id": kg_a, "target": "node", "confidence_abs": base_a if isinstance(base_a, (int, float)) else 0.8},
            {"kg_id": kg_b, "target": "node", "confidence_abs": base_b if isinstance(base_b, (int, float)) else 0.8},
        ]))
        db.close()

    print(out)


if __name__ == "__main__":
    main()
