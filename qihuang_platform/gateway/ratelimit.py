"""
API Gateway - 限流配额
Token Bucket 算法，双维度：用户/API Key + 接口

Redis 优先，不可用时降级为内存实现
"""
import time
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional


@dataclass
class TokenBucket:
    """令牌桶（内存版）"""
    rate: float          # 每秒补充令牌数（QPS）
    capacity: int        # 桶容量（突发上限）
    tokens: float = 0.0  # 当前令牌数
    last_refill: float = 0.0  # 上次补充时间

    def consume(self, count: int = 1) -> bool:
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


# ───────── Redis Lua 脚本（原子令牌桶操作）─────────

REDIS_RATELIMIT_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- 补充令牌
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * rate)
last_refill = now

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

-- TTL = 2×容量时间，避免冷桶占内存
local ttl = math.ceil(capacity / rate * 2) + 1
redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
redis.call('EXPIRE', key, ttl)

return {allowed, math.floor(tokens), math.floor(last_refill + math.max(1, (capacity - tokens) / rate)), math.floor(capacity)}
"""


class RateLimiter:
    """
    双维度限流器
    - Redis 可用时：分布式限流（多进程安全）
    - Redis 不可用时：内存限流（单进程）
    """

    def __init__(self):
        self._buckets: Dict[Tuple[str, str], TokenBucket] = {}
        self._default_rate = float(os.getenv("QH_RATELIMIT_DEFAULT_QPS", "10"))
        self._default_capacity = int(os.getenv("QH_RATELIMIT_DEFAULT_BURST", "20"))
        self._redis_script = None  # 延迟加载

    def _get_redis(self):
        try:
            from qihuang_platform.db.redis import get_redis
            return get_redis()
        except Exception:
            return None

    def _redis_check(self, identity: str, endpoint: str,
                     rate: float, capacity: int) -> Tuple[bool, dict]:
        """Redis 原子限流"""
        r = self._get_redis()
        if not r or r is False:
            return None, {}

        try:
            if self._redis_script is None:
                self._redis_script = r.register_script(REDIS_RATELIMIT_SCRIPT)

            key = f"qh:ratelimit:{identity}:{endpoint}"
            result = self._redis_script(
                keys=[key],
                args=[rate, capacity, time.time(), 1]
            )
            allowed, remaining, reset_at, limit = result
            return bool(allowed), {
                "limit": int(limit),
                "remaining": int(remaining),
                "reset": int(reset_at),
                "rate": rate,
            }
        except Exception:
            return None, {}

    def _memory_check(self, identity: str, endpoint: str,
                      rate: float, capacity: int) -> Tuple[bool, dict]:
        """内存限流（fallback）"""
        key = (identity, endpoint)
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(rate=rate, capacity=capacity)
        bucket = self._buckets[key]
        allowed = bucket.consume(1)
        info = {
            "limit": int(bucket.capacity),
            "remaining": bucket.remaining,
            "reset": int(bucket.reset_at),
            "rate": bucket.rate,
        }
        return allowed, info

    def check(self, identity: str, endpoint: str,
              rate: float = None, capacity: int = None) -> Tuple[bool, dict]:
        """检查是否允许请求，返回 (allowed, info)"""
        rate_val = rate or self._default_rate
        cap_val = capacity or self._default_capacity

        # 先试 Redis
        allowed, info = self._redis_check(identity, endpoint, rate_val, cap_val)
        if allowed is not None:
            return allowed, info

        # Redis 不可用，用内存
        return self._memory_check(identity, endpoint, rate_val, cap_val)

    def set_rate(self, identity: str, endpoint: str,
                 rate: float, capacity: int = None):
        """动态设置 rate"""
        cap_val = capacity or int(rate * 2)

        # 更新内存桶
        key = (identity, endpoint)
        self._buckets[key] = TokenBucket(rate=rate, capacity=cap_val)

        # 同步 Redis
        r = self._get_redis()
        if r and r is not False:
            try:
                rk = f"qh:ratelimit:{identity}:{endpoint}"
                r.hset(rk, mapping={"tokens": cap_val, "last_refill": time.time()})
                r.expire(rk, int(cap_val / rate * 2) + 1)
            except Exception:
                pass

    def reset(self, identity: str = None, endpoint: str = None):
        """清除桶（测试用）"""
        r = self._get_redis()
        if identity and endpoint:
            self._buckets.pop((identity, endpoint), None)
            if r and r is not False:
                try:
                    r.delete(f"qh:ratelimit:{identity}:{endpoint}")
                except Exception:
                    pass
        elif identity:
            to_delete = [k for k in self._buckets if k[0] == identity]
            for k in to_delete:
                del self._buckets[k]
            if r and r is not False:
                try:
                    keys = r.keys(f"qh:ratelimit:{identity}:*")
                    if keys:
                        r.delete(*keys)
                except Exception:
                    pass
        else:
            self._buckets.clear()
            if r and r is not False:
                try:
                    keys = r.keys("qh:ratelimit:*")
                    if keys:
                        r.delete(*keys)
                except Exception:
                    pass


# 全局单例
rate_limiter = RateLimiter()
