"""
岐黄智脑商业化平台 - Redis 连接模块
生产通过 QH_REDIS_URL 环境变量配置
开发阶段 Redis 不可用时优雅降级（返回 None）
"""
import os
import logging
from typing import Optional

logger = logging.getLogger("qihuang.redis")

REDIS_URL = os.getenv("QH_REDIS_URL", "")

_redis_client: Optional["Redis"] = None  # type: ignore


def get_redis() -> Optional["Redis"]:  # type: ignore
    """获取 Redis 客户端，不可用时返回 None"""
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    if not REDIS_URL:
        logger.info("QH_REDIS_URL 未配置，Redis 功能禁用")
        return None

    try:
        import redis
        pool = redis.ConnectionPool.from_url(
            REDIS_URL,
            socket_connect_timeout=3,
            socket_keepalive=True,
            retry_on_timeout=True,
            max_connections=int(os.getenv("QH_REDIS_POOL_SIZE", "20")),
        )
        _redis_client = redis.Redis(connection_pool=pool)
        _redis_client.ping()
        logger.info(f"Redis 连接成功: {REDIS_URL.split('@')[-1] if '@' in REDIS_URL else REDIS_URL}")
        return _redis_client
    except ImportError:
        logger.warning("redis-py 未安装，Redis 功能禁用")
        return None
    except Exception as e:
        logger.warning(f"Redis 连接失败: {e}，功能降级运行")
        _redis_client = False  # 标记已尝试，不再重试
        return None


def redis_available() -> bool:
    """检查 Redis 是否可用"""
    client = get_redis()
    return client is not None and client is not False
