"""命理运程 · 审计留痕（与 compliance 同构，写 JSONL）。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AuditStore:
    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def append(self, action: str, **fields) -> None:
        rec = {"at": datetime.now(timezone.utc).isoformat(), "action": action, **fields}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def query(self, action: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if action and rec.get("action") != action:
                    continue
                out.append(rec)
        return out[offset: offset + limit]

    def count(self) -> int:
        if not os.path.exists(self.path):
            return 0
        with open(self.path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
