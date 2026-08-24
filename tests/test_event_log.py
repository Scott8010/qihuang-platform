"""P0 append-only 事件日志 — 单元测试（不污染开发库，用独立内存 SQLite）。

验证契约：
1. emit 后 JSONL 兜底文件 + DB 表都能查到同一条事件；
2. 未知 event_type 自动回退到 DECISION；
3. DB 写入失败时仍写 JSONL 兜底、且不抛异常（绝不阻断业务）。
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from qihuang_platform import event_log
from qihuang_platform.event_log import (
    emit_event,
    SchedulerEventLog,
    configure_event_log,
    EVENT_DECISION,
)


@pytest.fixture
def tmp_log(tmp_path):
    p = str(tmp_path / "events.jsonl")
    configure_event_log(p)
    yield p


@pytest.fixture
def tmp_db():
    eng = create_engine("sqlite:///:memory:")
    SchedulerEventLog.__table__.create(bind=eng, checkfirst=True)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield session
    session.close()


def test_emit_writes_jsonl_and_db(tmp_log, tmp_db):
    rid = emit_event(
        tenant_id="t1",
        agent_key="health-advisor",
        event_type="PERMISSION",
        payload={"action": "agent_invoke", "result": "allowed"},
        db_session=tmp_db,
    )
    with open(tmp_log, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tenant_id"] == "t1"
    assert rec["event_type"] == "PERMISSION"
    assert rec["payload"]["result"] == "allowed"
    # DB 可查且字段一致
    rows = tmp_db.query(SchedulerEventLog).filter_by(id=rid).all()
    assert len(rows) == 1
    assert rows[0].tenant_id == "t1"
    assert json.loads(rows[0].payload)["result"] == "allowed"


def test_unknown_event_type_falls_back(tmp_log, tmp_db):
    rid = emit_event(event_type="WEIRD", payload={"x": 1}, db_session=tmp_db)
    row = tmp_db.query(SchedulerEventLog).filter_by(id=rid).one()
    assert row.event_type == EVENT_DECISION  # 回退到默认 DECISION


def test_db_failure_still_writes_jsonl(tmp_log):
    class BadSession:
        def add(self, *a, **k):
            raise RuntimeError("db down")

        def commit(self):
            pass

        def close(self):
            pass

    emit_event(event_type="ERROR", payload={"x": 1}, db_session=BadSession())
    with open(tmp_log, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == 1  # JSONL 兜底成功，且未抛异常
