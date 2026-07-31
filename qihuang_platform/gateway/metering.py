"""
API Gateway — 计量埋点（含3D模块独立计量维度）

子任务7: 独立计量维度
- 3D模块调用独立计数
- 支持按 module 维度查询
"""
import time
from datetime import datetime, timezone
from typing import Optional, List


class CallLog:
    __slots__ = (
        "id", "trace_id", "endpoint", "method", "tenant_id", "user_id",
        "app_key", "org_id", "status_code", "latency_ms", "tokens_used",
        "cost_cents", "ip", "user_agent", "timestamp", "extra",
        "module",  # 增值模块标识: "3d"/"agent"等
    )
    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))
        self.timestamp = self.timestamp or datetime.now(timezone.utc).isoformat()
        self.module = self.module or ""


class MeteringStore:
    def __init__(self, max_logs: int = 10000):
        self._logs: List[CallLog] = []
        self._max_logs = max_logs
        # 3D模块独立计数器
        self._module_counters = {"3d": 0}

    async def log(self, call: CallLog):
        self._logs.append(call)
        # 增值模块独立计数
        if call.module and call.module in self._module_counters:
            self._module_counters[call.module] += 1
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

    def query(self, tenant_id=None, user_id=None, endpoint=None,
              start_time=None, end_time=None, module=None, limit=100):
        results = self._logs
        if tenant_id:
            results = [l for l in results if l.tenant_id == tenant_id]
        if user_id:
            results = [l for l in results if l.user_id == user_id]
        if endpoint:
            results = [l for l in results if endpoint in (l.endpoint or "")]
        if module:
            results = [l for l in results if l.module == module]
        if start_time:
            results = [l for l in results if (l.timestamp or "") >= start_time]
        if end_time:
            results = [l for l in results if (l.timestamp or "") <= end_time]
        return list(reversed(results))[:limit]

    def stats(self, tenant_id=None, module=None):
        logs = self._logs
        if tenant_id:
            logs = [l for l in logs if l.tenant_id == tenant_id]
        if module:
            logs = [l for l in logs if l.module == module]
        if not logs:
            return {
                "total_calls": 0, "total_tokens": 0,
                "total_cost_cents": 0, "avg_latency_ms": 0,
            }
        return {
            "total_calls": len(logs),
            "total_tokens": sum(l.tokens_used or 0 for l in logs),
            "total_cost_cents": sum(l.cost_cents or 0 for l in logs),
            "avg_latency_ms": round(
                sum(l.latency_ms or 0 for l in logs) / len(logs), 1
            ),
        }

    def module_stats(self, module_name="3d"):
        """获取增值模块独立统计"""
        return {
            "module": module_name,
            "total_loads": self._module_counters.get(module_name, 0),
            "recent_calls": len([l for l in self._logs[-100:] if l.module == module_name]),
        }

    def clear(self):
        self._logs.clear()
        self._module_counters = {"3d": 0}


metering_store = MeteringStore()
