"""
内容合规审核 · 审计日志（合规操作留痕）

每条审计记录记录：
  - 操作类型（scan 送审 / feedback 人工回写 / view_audit 查看审计）
  - 操作人（JWT sub）
  - 操作时间
  - material_id（关联被操作的物料）
  - 变更前状态（feedback 时有值；scan 时为 None）
  - 变更后状态
  - 详细信息（decision / action_taken / hit_count 等）

设计原则：
  - 追加写（append-only），永不修改历史记录
  - JSONL 落盘 + 文件锁（复用 store._file_lock 模式）
  - 查询支持按操作类型 / material_id / 时间范围过滤
"""
from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _file_lock(path: str):
    """跨平台文件锁，保护 JSONL 并发写入。"""
    lock_path = path + ".lock"
    f = open(lock_path, "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        f.close()


class AuditStore:
    """审计日志存储（JSONL 追加写，永不修改）。"""

    def __init__(self, path: str):
        self.path = path
        self._ensure_dir()

    def _ensure_dir(self):
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        """追加一条审计记录（追加写，不加锁也可——单行 write 是原子的）。

        但为防止极端并发交错，仍加文件锁保护。
        """
        record["audited_at"] = _now_iso()
        with _file_lock(self.path):
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def query(
        self,
        action: Optional[str] = None,
        material_id: Optional[str] = None,
        operator: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """查询审计日志，支持按操作类型 / material_id / 操作人过滤。"""
        if not os.path.exists(self.path):
            return []
        results: list[dict] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if action and rec.get("action") != action:
                    continue
                if material_id and rec.get("material_id") != material_id:
                    continue
                if operator and rec.get("operator") != operator:
                    continue
                results.append(rec)
        # 按时间倒序（最新在前）
        results.sort(key=lambda r: r.get("audited_at", ""), reverse=True)
        return results[offset:offset + limit]

    def count(self) -> int:
        """总记录数。"""
        if not os.path.exists(self.path):
            return 0
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


# ───────── 审计记录工厂 ─────────

def make_scan_audit(
    operator: str,
    tenant_id: Optional[str],
    store_id: str,
    material_id: str,
    state: str,
    hit_count: int,
    text_preview: str = "",
) -> dict[str, Any]:
    """构造 scan 审计记录。"""
    return {
        "action": "scan",
        "operator": operator,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "material_id": material_id,
        "state_before": None,
        "state_after": state,
        "hit_count": hit_count,
        "text_preview": text_preview[:120],
    }


def make_feedback_audit(
    operator: str,
    tenant_id: Optional[str],
    material_id: str,
    state_before: Optional[str],
    state_after: str,
    decision: str,
    action_taken: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """构造 feedback 审计记录。"""
    return {
        "action": "feedback",
        "operator": operator,
        "tenant_id": tenant_id,
        "material_id": material_id,
        "state_before": state_before,
        "state_after": state_after,
        "decision": decision,
        "action_taken": action_taken,
        "note": note,
    }
