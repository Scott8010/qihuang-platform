"""
内容合规审核 · 本地物料存储与回写

取代原先对 hb-compliance-guard HTTP 服务的依赖——Agent 中台自己拥有完整流水线
（L0 硬红线 + L1 检索 + L2 推理 + 本存储）。回写钉在业务实体上，客观真实：
  - material_key 给定时，按「业务键」而非文本 hash 生成指纹，同业务反复重提覆盖同一条，
    避免平台看板堆积历史版本（呼应《内容审核开发汇总》幂等设计）。
  - feedback 把人工结论（keep/override/remediated/ignore/escalate）落到 material_id 上，
    平台只审不下结论、不替门店改文案。

本地用 JSONL 落盘（离线可验证）；生产可换 Neo4j/PG 后端（接口一致）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

# 四态
STATE_BLOCKED = "违规拦截"
STATE_REVIEW = "存疑待复核"
STATE_PENDING = "待审查"
STATE_PASSED = "已通过"

_DECISION_STATE = {
    "keep": STATE_PASSED,
    "remediated": STATE_PASSED,
    "ignore": STATE_PASSED,
    "override": STATE_BLOCKED,
    "escalate": STATE_REVIEW,
}


def make_material_id(text: str, institution_id: str, material_key: str | None = None) -> str:
    """内容指纹 ID —— 幂等（material_key 给定时按业务键生成）。"""
    seed = material_key if material_key else text
    digest = hashlib.sha1(f"{institution_id}::{seed}".encode("utf-8")).hexdigest()[:12]
    return f"MAT-{digest.upper()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComplianceStore:
    def __init__(self, path: str):
        self.path = path
        self._materials: dict[str, dict] = {}
        self._load()

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _load(self):
        self._materials = {}
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._materials[rec["material_id"]] = rec

    def _append(self, rec: dict):
        self._ensure_dir()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def upsert(self, material_id: str, record: dict) -> dict:
        """写入/覆盖一条物料（幂等：同 material_id 始终覆盖同一条）。"""
        record["material_id"] = material_id
        record["updated_at"] = now_iso()
        self._materials[material_id] = record
        # 重新整写（保持 jsonl 单条即最新语义，且便于审计全量历史留痕）
        self._ensure_dir()
        with open(self.path, "w", encoding="utf-8") as f:
            for r in self._materials.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return record

    def get(self, material_id: str) -> Optional[dict]:
        return self._materials.get(material_id)

    def all(self, institution_id: str | None = None,
            port: str | None = None) -> list[dict]:
        out = list(self._materials.values())
        if institution_id:
            out = [m for m in out if m.get("institution_id") == institution_id]
        if port:
            out = [m for m in out if m.get("port") == port]
        return out

    def feedback(self, material_id: str, decision: str, action_taken: str,
                 note: str | None, operator: str | None) -> dict | None:
        """人工结论回写：钉在 material_id 上，状态按决策推导，追加流水。"""
        rec = self._materials.get(material_id)
        if rec is None:
            return None
        new_state = _DECISION_STATE.get(decision, rec.get("state"))
        rec["state"] = new_state
        rec.setdefault("feedback_log", []).append({
            "decision": decision,
            "action_taken": action_taken,
            "note": note,
            "operator": operator,
            "at": now_iso(),
        })
        rec["updated_at"] = now_iso()
        self._materials[material_id] = rec
        self._ensure_dir()
        with open(self.path, "w", encoding="utf-8") as f:
            for r in self._materials.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return rec

    def dashboard(self, institution_id: str | None = None,
                  port: str | None = None) -> dict:
        rows = self.all(institution_id, port)
        counts = {STATE_BLOCKED: 0, STATE_REVIEW: 0, STATE_PENDING: 0, STATE_PASSED: 0}
        for m in rows:
            counts[m.get("state", STATE_PENDING)] = counts.get(m.get("state", STATE_PENDING), 0) + 1
        return {
            "total": len(rows),
            "states": counts,
            "recent": rows[-10:][::-1],
        }
