"""
health-advisor · 会话持久化（S2 追问轮次 + 多轮历史）

设计（对齐平台范式）：
  - 优先用平台 `qihuang_platform.db.redis.get_redis()` 单例（生产有 redis 即持久化，带 TTL）。
  - redis 不可用（本地/未部署）时**降级内存 dict**，行为与骨架阶段一致，零新依赖。
  - 复用 ratelimit 同款 `get_redis()` 调用方式（`if r:` 判定，None/False 均 falsy）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from qihuang_platform.db.redis import get_redis

_SESSION_TTL = 1800  # 30 分钟会话有效期


class SessionStore:
    """health-advisor 多轮会话存储。结构：{history:[...], ask_count:int}。"""

    def __init__(self) -> None:
        try:
            self._r = get_redis()  # type: ignore[assignment]
        except Exception:  # noqa: BLE001
            self._r = None
        self._mem: Dict[str, dict] = {}  # redis 不可用时的降级存储

    def _key(self, session_id: str) -> str:
        return f"ha:session:{session_id}"

    def get(self, session_id: str) -> Dict[str, Any]:
        if self._r:
            try:
                raw = self._r.get(self._key(session_id))
                if raw:
                    return json.loads(raw)
            except Exception:  # noqa: BLE001
                pass
        return self._mem.get(session_id, {"history": [], "ask_count": 0})

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        if self._r:
            try:
                self._r.set(self._key(session_id), json.dumps(data, ensure_ascii=False), ex=_SESSION_TTL)
            except Exception:  # noqa: BLE001
                pass
        self._mem[session_id] = data

    def touch_ask(self, session_id: str) -> int:
        """追问轮次 +1 并写回，返回最新轮次。"""
        d = self.get(session_id)
        d["ask_count"] = d.get("ask_count", 0) + 1
        self.set(session_id, d)
        return d["ask_count"]

    def append(self, session_id: str, item: Dict[str, Any]) -> None:
        """追加一条对话历史并写回。"""
        d = self.get(session_id)
        d.setdefault("history", []).append(item)
        self.set(session_id, d)
