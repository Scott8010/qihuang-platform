"""活态化周期聚合调度器（轻量 asyncio 后台任务，无需额外依赖）

在 FastAPI lifespan 中启动一个后台任务，按固定间隔（默认 T+1 = 24h）自动执行
聚合回写，使活态闭环无需人工触发也能持续运转。

间隔可用环境变量 QH_LIVING_AGG_INTERVAL_SECONDS 覆盖（开发期可设小值便于观察）。
"""
import asyncio
import logging
from typing import Optional

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.aggregator import (
    aggregate_feedback, process_corrections, process_gaps,
)

logger = logging.getLogger("living.scheduler")

_DEFAULT_INTERVAL = 24 * 3600  # 默认 24 小时


async def _run_once():
    db = SessionLocal()
    try:
        agg = await aggregate_feedback(db)
        corr = await process_corrections(db)
        gaps = await process_gaps(db)
        logger.info(
            "[living] 周期聚合完成: conf_written=%s corr=%s gap=%s",
            agg.get("items_written"),
            corr.get("corrections_processed"),
            gaps.get("gaps_processed"),
        )
    except Exception as e:
        logger.exception(f"[living] 周期聚合异常: {e}")
    finally:
        db.close()

    # 趋势采集（方案 2）：独立于聚合，失败不影响闭环
    try:
        from qihuang_platform.living.trend import collect_living_snapshot
        res = await collect_living_snapshot()
        logger.info("[living] 趋势采集完成: %s", res)
    except Exception as e:
        logger.exception(f"[living] 趋势采集异常: {e}")

    # 回路三（业务实证加权）采集：默认开关关闭，不影响仿真期闭环
    try:
        from qihuang_platform.living.business_signal import collect_business_signals
        bres = await collect_business_signals()
        logger.info("[living] 回路三采集: %s", bres)
    except Exception as e:
        logger.exception(f"[living] 回路三采集异常: {e}")


async def _loop(interval: int):
    while True:
        await asyncio.sleep(interval)
        await _run_once()


def start_living_scheduler(interval: int = _DEFAULT_INTERVAL):
    """在 lifespan 中启动周期聚合后台任务，返回 asyncio.Task。"""
    try:
        task = asyncio.create_task(_loop(interval))
        logger.info(f"[living] 周期聚合调度已启动，间隔 {interval}s")
        return task
    except RuntimeError:
        # 无运行中的事件循环（如被非异步上下文直接导入）
        logger.warning("[living] 无事件循环，跳过调度启动")
        return None
