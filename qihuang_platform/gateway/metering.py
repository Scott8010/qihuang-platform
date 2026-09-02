"""
API Gateway — 计量埋点（含3D模块独立计量维度）

子任务7: 独立计量维度
- 3D模块调用独立计数
- 支持按 module 维度查询
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List

logger = logging.getLogger("gateway.metering")


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

    async def log(self, call: CallLog, persist: bool = True):
        """写入内存计量 + （可选）真落库到 DB call_log 表。

        persist=True 时调 billing.quota.record_usage 把本次调用写进 call_log 表，
        使 admin 用量聚合 / 配额校验 / 对账均基于真实持久化数据（根治「计量写 0」）。
        用 asyncio.to_thread 把同步 DB 写放进线程池，避免阻塞事件循环；
        任何异常仅告警、绝不阻断主业务响应（旁路非阻断）。
        """
        self._logs.append(call)
        # 增值模块独立计数
        if call.module and call.module in self._module_counters:
            self._module_counters[call.module] += 1
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

        if persist:
            await self._persist(call)

    async def _persist(self, call: CallLog) -> None:
        """真落库到 call_log 表（旁路非阻断）。"""
        if not call.tenant_id:
            # 匿名 / 无租户上下文请求不落库，避免脏 null 记录
            return
        try:
            from qihuang_platform.billing.quota import record_usage
            await asyncio.to_thread(
                record_usage,
                call.tenant_id,
                call.endpoint,
                call.method,
                call.status_code,
                call.latency_ms or 0,
                call.tokens_used or 0,
                call.cost_cents or 0,
                user_id=call.user_id,
                trace_id=call.trace_id,
                app_key=call.app_key,
                org_id=call.org_id,
                ip=call.ip,
                user_agent=call.user_agent,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[metering] 真落库失败(旁路非阻断): %s", e)

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
