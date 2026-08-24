"""活态调度器 — append-only 事件日志（P0，来自 OpenViking/Maka 双开源评估）

设计思想（参考 Apache Maka "Log is the Runtime"）：把 Agent 调用、工具调用、
权限判定、计费 / 拦截决策等结构化事件，以「只能追加、不可篡改」的方式留痕，
服务于：① 监管合规留痕 ② HB 合规巡检 guard 审计 ③ 对账核查
（"为啥这单算了我 2 套餐 / agent 为啥没拦住"）。

实现要点：
- 旁路日志：先写 JSONL 文件兜底（即使 DB 宕机也不丢证据），再写 DB。
- 绝不阻断业务：emit_event 任何环节失败仅 logger.warning，绝不 raise。
- append-only：SchedulerEventLog 只提供写入，无 update / delete 方法；
  如需强约束，生产侧可加触发器禁止 UPDATE / DELETE（原始证据永不丢，
  Maka: Context is not history）。
- 仅参考 Maka 设计模式，不引入任何外部依赖（纯 stdlib + SQLAlchemy）。
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Index
from qihuang_platform.db.config import Base, SessionLocal

logger = logging.getLogger("event_log")

# 事件类型（与 Maka runtime 事件对齐的精简集）
EVENT_INVOCATION = "INVOCATION"
EVENT_TOOL_CALL = "TOOL_CALL"
EVENT_PERMISSION = "PERMISSION"
EVENT_DECISION = "DECISION"
EVENT_ERROR = "ERROR"
EVENT_TYPES = (
    EVENT_INVOCATION,
    EVENT_TOOL_CALL,
    EVENT_PERMISSION,
    EVENT_DECISION,
    EVENT_ERROR,
)

_log_lock = threading.Lock()
_default_log_path = os.getenv("QH_EVENT_LOG_PATH") or os.path.join(
    os.getcwd(), "event_logs", "scheduler_events.jsonl"
)
_event_log_path = _default_log_path


def configure_event_log(path: str = None):
    """覆盖 JSONL 兜底文件路径（测试 / 部署用）。"""
    global _event_log_path
    _event_log_path = path or _default_log_path


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class SchedulerEventLog(Base):
    """append-only 调度事件日志表。

    只 INSERT，不提供 update / delete —— 原始证据永不丢。
    """

    __tablename__ = "scheduler_event_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), index=True)
    trace_id = Column(String(36), index=True)
    agent_key = Column(String(50), index=True)
    event_type = Column(String(20), nullable=False, index=True)
    payload = Column(Text)  # JSON 字符串
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    __table_args__ = (
        Index("idx_sched_ev_tenant_ts", "tenant_id", "created_at"),
        Index("idx_sched_ev_type_ts", "event_type", "created_at"),
    )


def emit_event(
    tenant_id=None,
    agent_key=None,
    event_type=EVENT_DECISION,
    payload=None,
    trace_id=None,
    db_session=None,
):
    """旁路发射一条事件。任何失败仅 warn，绝不阻断调用方业务。

    :param db_session: 可选，传入则复用该 session 并在内部 commit；
                       不传则内部新建 SessionLocal()（写生产库）。
                       单测应传入独立 session 以避免污染开发库。
    :return: 事件 id（即使全程失败也尽量返回 uuid，便于链路串联）
    """
    if event_type not in EVENT_TYPES:
        event_type = EVENT_DECISION
    rec_id = str(uuid.uuid4())
    trace = trace_id or str(uuid.uuid4())
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    rec = {
        "id": rec_id,
        "tenant_id": tenant_id,
        "trace_id": trace,
        "agent_key": agent_key,
        "event_type": event_type,
        "payload": payload or {},
        "created_at": _now_iso(),
    }
    # 1) JSONL 兜底（第一道保险，DB 宕机也留痕）
    try:
        parent = os.path.dirname(_event_log_path) or "."
        os.makedirs(parent, exist_ok=True)
        with _log_lock:
            with open(_event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[event_log] JSONL 兜底写入失败(忽略): %s", e)
    # 2) DB（第二道保险）
    try:
        db = db_session or SessionLocal()
        try:
            db.add(
                SchedulerEventLog(
                    id=rec_id,
                    tenant_id=tenant_id,
                    trace_id=trace,
                    agent_key=agent_key,
                    event_type=event_type,
                    payload=payload_json,
                )
            )
            db.commit()
        finally:
            if db_session is None:
                db.close()
    except Exception as e:
        logger.warning("[event_log] DB 写入失败(已 JSONL 兜底): %s", e)
    return rec_id
