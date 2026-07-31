"""
监控大盘 — QPS/延迟/错误率/Token消耗/告警判断

提供管理端 /admin/v1/monitor/overview 所需的数据聚合
"""
import time
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque


@dataclass
class MetricSnapshot:
    """指标快照"""
    timestamp: float
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    tokens_used: int = 0
    cost_cents: float = 0.0
    is_3d: bool = False
    tenant_id: str = ""
    error: bool = False


class MonitorStore:
    """监控数据存储（内存环形缓冲）"""

    BUFFER_SIZE = 10000  # 保留最近10000条

    def __init__(self):
        self._metrics: deque = deque(maxlen=self.BUFFER_SIZE)
        self._alerts: deque = deque(maxlen=100)  # 最近100条告警
        self._start_time = time.time()

    def record(self, metric: MetricSnapshot):
        """记录一条指标"""
        self._metrics.append(metric)

    def record_alert(self, level: str, title: str, message: str):
        """记录一条告警"""
        self._alerts.append({
            "level": level,  # critical/warning/info
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_overview(self, window_seconds: int = 300) -> Dict[str, Any]:
        """
        获取监控大盘概览

        Args:
            window_seconds: 统计窗口（秒），默认5分钟

        Returns:
            {
                qps, avg_latency_ms, p95_latency_ms, error_rate,
                total_calls, total_tokens, total_cost_cents,
                calls_by_endpoint, status_distribution,
                llm_status, uptime_seconds, active_alerts
            }
        """
        now = time.time()
        cutoff = now - window_seconds

        recent = [m for m in self._metrics if m.timestamp >= cutoff]

        total = len(recent)
        if total == 0:
            return {
                "qps": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "error_rate": 0.0,
                "total_calls": 0,
                "total_tokens": 0,
                "total_cost_cents": 0.0,
                "calls_by_endpoint": {},
                "status_distribution": {},
                "llm_status": [],
                "uptime_seconds": int(now - self._start_time),
                "active_alerts": [],
                "window_seconds": window_seconds,
            }

        # 基础统计
        total_tokens = sum(m.tokens_used for m in recent)
        total_cost = sum(m.cost_cents for m in recent)
        errors = sum(1 for m in recent if m.error or m.status_code >= 400)
        latencies = sorted([m.latency_ms for m in recent])

        # QPS
        qps = total / window_seconds if window_seconds > 0 else 0

        # P95延迟
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[p95_idx] if latencies else 0

        # 按端点统计
        by_endpoint: Dict[str, int] = defaultdict(int)
        for m in recent:
            by_endpoint[m.endpoint] += 1

        # 状态码分布
        status_dist: Dict[str, int] = defaultdict(int)
        for m in recent:
            status_dist[str(m.status_code)] += 1

        # 活跃告警
        active_alerts = [a for a in self._alerts]

        return {
            "qps": round(qps, 2),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "p95_latency_ms": round(p95, 1),
            "error_rate": round(errors / total * 100, 2),
            "total_calls": total,
            "total_tokens": total_tokens,
            "total_cost_cents": round(total_cost, 2),
            "calls_by_endpoint": dict(sorted(by_endpoint.items(), key=lambda x: -x[1])[:10]),
            "status_distribution": dict(status_dist),
            "llm_status": self._get_llm_status(),
            "uptime_seconds": int(now - self._start_time),
            "active_alerts": active_alerts,
            "window_seconds": window_seconds,
        }

    def _get_llm_status(self) -> list:
        """获取LLM降级链状态"""
        try:
            from qihuang_platform.gateway.llm_fallback import llm_fallback
            return llm_fallback.get_status()
        except Exception:
            return []

    def get_tenant_stats(self, tenant_id: str, window_seconds: int = 3600) -> Dict[str, Any]:
        """获取租户级统计"""
        now = time.time()
        cutoff = now - window_seconds
        recent = [m for m in self._metrics if m.timestamp >= cutoff and m.tenant_id == tenant_id]

        total = len(recent)
        tokens = sum(m.tokens_used for m in recent)
        cost = sum(m.cost_cents for m in recent)
        errors = sum(1 for m in recent if m.error or m.status_code >= 400)
        is_3d_calls = sum(1 for m in recent if m.is_3d)

        return {
            "tenant_id": tenant_id,
            "total_calls": total,
            "total_tokens": tokens,
            "total_cost_cents": round(cost, 2),
            "error_count": errors,
            "error_rate": round(errors / total * 100, 2) if total > 0 else 0,
            "d3_module_calls": is_3d_calls,
            "window_seconds": window_seconds,
        }

    def check_and_alert(self) -> list:
        """检查指标并生成告警"""
        overview = self.get_overview(window_seconds=60)
        new_alerts = []

        # 错误率告警
        if overview["error_rate"] > 10:
            self.record_alert(
                "critical",
                "错误率过高",
                f"最近1分钟错误率 {overview['error_rate']}%，超过10%阈值",
            )
            new_alerts.append("error_rate_high")

        # P95延迟告警
        if overview["p95_latency_ms"] > 3000:
            self.record_alert(
                "warning",
                "响应延迟过高",
                f"P95延迟 {overview['p95_latency_ms']}ms，超过3秒阈值",
            )
            new_alerts.append("latency_high")

        # QPS突降告警
        if overview["total_calls"] > 0 and overview["qps"] < 0.1:
            self.record_alert(
                "warning",
                "请求量异常低",
                f"最近QPS仅 {overview['qps']}，可能服务异常",
            )
            new_alerts.append("low_qps")

        return new_alerts


# 全局单例
monitor = MonitorStore()
