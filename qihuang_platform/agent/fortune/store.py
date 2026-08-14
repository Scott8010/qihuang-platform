"""
命理运程 · 本地物料存储与回写（对齐 compliance 的 MAT 式幂等）

  - material_key 给定时按业务键生成指纹，同业务反复重提覆盖同一条，避免看板堆积；
  - fortune 数据独立 JSONL（不入 Neo4j、不污染中医库），生产可换 PG 后端（接口一致）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def make_material_id(seed: str, prefix: str = "FOR") -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest.upper()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FortuneStore:
    def __init__(self, path: str):
        self.path = path
        self._recs: Dict[str, dict] = {}
        self._load()

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _load(self):
        self._recs = {}
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._recs[rec["material_id"]] = rec

    def _flush(self):
        self._ensure_dir()
        lock = self.path + ".lock"
        f = open(lock, "w")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            with open(self.path, "w", encoding="utf-8") as w:
                for r in self._recs.values():
                    w.write(json.dumps(r, ensure_ascii=False) + "\n")
        finally:
            f.close()

    def upsert(self, material_id: str, record: dict) -> dict:
        record["material_id"] = material_id
        record["updated_at"] = now_iso()
        self._recs[material_id] = record
        self._flush()
        return record

    def get(self, material_id: str) -> Optional[dict]:
        return self._recs.get(material_id)

    def all(self, kind: Optional[str] = None, user_id: Optional[str] = None) -> list:
        out = list(self._recs.values())
        if kind:
            out = [r for r in out if r.get("kind") == kind]
        if user_id:
            out = [r for r in out if r.get("user_id") == user_id]
        return out

    def dashboard(self, user_id: Optional[str] = None) -> dict:
        rows = self.all(user_id=user_id)
        kinds = {}
        for r in rows:
            k = r.get("kind", "unknown")
            kinds[k] = kinds.get(k, 0) + 1
        return {
            "total": len(rows),
            "by_kind": kinds,
            "recent": rows[-10:][::-1],
        }
