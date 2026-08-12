"""聚焦诊断 A 节点：business_use 正加权增益是否真实写入 Neo4j（用 cypher 直接核对）。
不依赖 8601 GET /confidence 读路径，避免读路径遮蔽。"""
import os
import asyncio
import subprocess

from dotenv import load_dotenv
load_dotenv("/root/qihuang_platform/.env")

from qihuang_platform.living.kg_write_client import kg_client
from qihuang_platform.living.ingest import emit_business_feedback, bridge_compliance_scan
from qihuang_platform.living.aggregator import aggregate_feedback
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
from sqlalchemy import and_


def cypher_read(kg_id):
    q = f"MATCH (n) WHERE n.kg_id='{kg_id}' RETURN n.confidence AS c"
    out = subprocess.run(
        ["docker", "exec", "-i", "app-neo4j-1", "cypher-shell",
         "-u", "neo4j", "-p", "qihuang123", q],
        capture_output=True, text=True,
    )
    return out.stdout.strip() or out.stderr.strip()


def cypher_write(kg_id, val):
    q = f"MATCH (n) WHERE n.kg_id='{kg_id}' SET n.confidence={val}"
    subprocess.run(
        ["docker", "exec", "-i", "app-neo4j-1", "cypher-shell",
         "-u", "neo4j", "-p", "qihuang123", q],
        capture_output=True, text=True,
    )


db = SessionLocal()
try:
    name_a, kg_a = None, None
    for n in ["艾灸", "拔罐", "刮痧", "针灸"]:
        r = asyncio.run(kg_client.resolve(n))
        m = (r or {}).get("matches") or []
        if m:
            name_a, kg_a = n, m[0]["kg_id"]
            break
    print("A node:", name_a, kg_a)
    base = asyncio.run(kg_client.get_confidence(kg_a))
    print("GET baseline:", base, "| CYPHER baseline:", cypher_read(kg_a))

    # 清历史 business 行
    db.query(KgFeedback).filter(and_(KgFeedback.kg_id == kg_a, KgFeedback.source == "business")).delete()
    db.commit()

    # 门店送审命中 → business_use（weight=0.5 → 1+0.5*0.5=1.25 倍）
    s = asyncio.run(bridge_compliance_scan(
        db, [{"entity": name_a, "severity": "ORANGE"}],
        tenant_id="tenant_default", store_id="verify_store", business_weight=0.5,
    ))
    print("scan_bridge:", s)
    summary = asyncio.run(aggregate_feedback(db, client=kg_client))
    print("aggregate:", summary)

    after_get = asyncio.run(kg_client.get_confidence(kg_a))
    after_cypher = cypher_read(kg_a)
    print("GET after:", after_get, "| CYPHER after:", after_cypher)
    print("expected ~", round((base if isinstance(base,(int,float)) else 0.8) + 0.0003*1.25, 4))
finally:
    # 复原
    db.query(KgFeedback).filter(and_(KgFeedback.kg_id == kg_a, KgFeedback.source == "business")).delete()
    db.commit()
    cypher_write(kg_a, base if isinstance(base,(int,float)) else 0.8)
    db.close()
print("DONE")
