"""
API Gateway - 限流配额
Token Bucket 算法，双维度：用户/API Key + 接口
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class TokenBucket:
    """令牌桶"""
    rate: float          # 每秒补充令牌数（QPS）
    capacity: int        # 桶容量（突发上限）
    tokens: float = 0.0  # 当前令牌数
    last_refill: float = 0.0  # 上次补充时间

    def consume(self, count: int = 1) -> bool:
        """尝试消费 count 个令牌，成功返回 True"""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    @property
    def remaining(self) -> int:
        return int(self.tokens)

    @property
    def reset_at(self) -> float:
        return self.last_refill + max(1.0, (self.capacity - self.tokens) / self.rate)


class RateLimiter:
    """
    双维度限流器（内存版，后续替换 Redis）
    维度1: 用户/Key 级别（per_identity）
    维度2: 接口级别（per_endpoint）
    取较严格的 qps 上限
    """

    def __init__(self):
        self._buckets: Dict[Tuple[str, str], TokenBucket] = {}
        self._default_rate = 10.0    # 默认 10 QPS
        self._default_capacity = 20  # 默认突发 20

    def check(self, identity: str, endpoint: str,
              rate: float = None, capacity: int = None) -> Tuple[bool, dict]:
        """
        检查是否允许请求
        返回 (allowed, info) 其中 info = {limit, remaining, reset}
        """
        key = (identity, endpoint)
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                rate=rate or self._default_rate,
                capacity=capacity or self._default_capacity,
            )
        bucket = self._buckets[key]
        allowed = bucket.consume(1)

        info = {
            "limit": int(bucket.capacity),
            "remaining": bucket.remaining,
            "reset": int(bucket.reset_at),
            "rate": bucket.rate,
        }
        return allowed, info

    def set_rate(self, identity: str, endpoint: str,
                 rate: float, capacity: int = None):
        """动态设置 rate"""
        key = (identity, endpoint)
        self._buckets[key] = TokenBucket(
            rate=rate,
            capacity=capacity or int(rate * 2),
        )

    def reset(self, identity: str = None, endpoint: str = None):
        """清除桶（主要用于测试）"""
        if identity and endpoint:
            self._buckets.pop((identity, endpoint), None)
        elif identity:
            to_delete = [k for k in self._buckets if k[0] == identity]
            for k in to_delete:
                del self._buckets[k]
        else:
            self._buckets.clear()


# 全局单例
rate_limiter = RateLimiter()
