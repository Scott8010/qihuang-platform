"""活态化 B · 回路三（业务实证加权）采集器

目标：让「真实租户的业务使用行为」反向加权知识置信度，使系统「越用越聪明」。

设计要点：
  - 默认开关 LIVING_BUSINESS_SIGNAL_ENABLED=false（仿真数据期关闭，零副作用，不污染闭环）。
    真实租户业务实证数据回灌后，置为 true 即可激活。
  - 数据源可插拔（fetch_business_usage）：当前 8601 无节点使用统计接口、Neo4j 也无 usage 节点，
    故现返回空 dict —— 不产生任何信号、不写入数据、不影响现有闭环。
    真实客户上线后，在此接入：8601 未来提供的 /kg/api/usage，或 8602 业务调用日志 ETL。
  - 采集结果写入 KgFeedback(source='business', feedback_type='business_use', business_weight=W)，
    aggregator 已支持据此：① business_use 基础正加权 ② _business_multiplier 按 business_weight 放大。

激活步骤（真实客户来了以后）：
  1. 接数据源：实现 fetch_business_usage（从业务库/8601 摄取 kg_id -> 实证权重）。
  2. 开开关：环境变量 LIVING_BUSINESS_SIGNAL_ENABLED=true。
  3. 调增益：环境变量 LIVING_BUSINESS_GAIN=0.5（或其他经验值）。
"""
import logging
import os
from typing import Dict, Any

from sqlalchemy import func, select

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback
from qihuang_platform.living.kg_write_client import kg_client

logger = logging.getLogger("living.business_signal")

_BUSINESS_SIGNAL_ENABLED = os.getenv(
    "LIVING_BUSINESS_SIGNAL_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")


async def fetch_business_usage(db, client) -> Dict[str, float]:
    """从真实业务数据源摄取某 kg_id 的业务实证权重。

    返回 {kg_id: weight}，weight ∈ (0, 1] 表示该知识点的业务实证强度。
    当前无数据源 → 返回空 dict（不污染仿真数据）。
    真实客户上线后在此接入（示例）：
      - 8601 GET /kg/api/usage -> {kg_id: 调用频次归一化}
      - 或 8602 业务调用日志（capability 层按 kg_id 归因）ETL 聚合
    """
    return {}


async def collect_business_signals() -> dict:
    """执行一轮回路三业务信号采集并落库（KgFeedback source='business'）。

    返回采集摘要 dict（含 enabled/skipped 或 signals_written）。容错：异常不影响闭环。
    """
    if not _BUSINESS_SIGNAL_ENABLED:
        logger.info(
            "[living.business] 回路三采集未启用"
            "（LIVING_BUSINESS_SIGNAL_ENABLED=false），跳过"
        )
        return {"enabled": False, "skipped": True}

    db = SessionLocal()
    try:
        usage = await fetch_business_usage(db, kg_client)
        written = 0
        for kg_id, w in usage.items():
            if not kg_id or str(kg_id).startswith("pending:"):
                continue
            try:
                weight = float(w)
            except (TypeError, ValueError):
                continue
            if weight <= 0:
                continue
            db.add(KgFeedback(
                kg_id=str(kg_id),
                feedback_type="business_use",
                source="business",
                business_weight=weight,
                tenant_id=None,
            ))
            written += 1
        db.commit()
        logger.info("[living.business] 回路三采集完成，写入业务信号 %s 条", written)
        return {"enabled": True, "signals_written": written}
    except Exception as e:
        db.rollback()
        logger.exception(f"[living.business] 采集异常: {e}")
        return {"error": str(e)}
    finally:
        db.close()
