"""
tests/test_agent_metering_persist.py — 锁死 agent 端点 call_log 双写回归（#667）

背景：上一轮把 MeteringStore.log 默认 persist=True 真落库（治「计量写 0」中间件路径），
导致 5 个 agent 的 record_call（persist 用默认 → True）与路由层
charge_agent → charge_call（真值源：既真扣积分钱包、又写 call_log）对同一请求写 2~3 行
call_log，对账/用量聚合被重复计数。

修复（#667）：coach / content_writer / health_advisor / insight / store_coach 这 5 个
agent 的 record_call 显式 persist=False，真值源交路由层 charge_agent（对齐 health_assistant）。

本文件断言这 5 个 record_call 内部调 metering_store.log 时 persist=False，且因 persist=False
不触发 billing.quota.record_usage 落库，从而把双写回归锁死。

纯单元、monkeypatch，不依赖真实 DB，CI 稳定不 flaky。
"""
import asyncio

import pytest


# 各 agent record_call 的最小有效入参（对齐各自签名，避免触发额外分支）
AGENTS = {
    "coach": (
        "qihuang_platform.agent.coach.metering",
        dict(
            tenant_id="tenant_default", store_id="s1", code=0,
            latency_ms=12.3, trace_id="t",
            endpoint="/api/v1/agent/coach/evaluate",
            status_code=200, action="evaluate",
        ),
    ),
    "content_writer": (
        "qihuang_platform.agent.content_writer.metering",
        dict(
            tenant_id="tenant_default", user_id="u1", store_id="s1", code=0,
            latency_ms=12.3, trace_id="t",
            endpoint="/api/v1/agent/content-writer/generate",
            status_code=200, action="generate", variants=1, token_used=100,
        ),
    ),
    "health_advisor": (
        "qihuang_platform.agent.health_advisor.metering",
        dict(
            tenant_id="tenant_default", store_id="s1", code=0, partial=False,
            latency_ms=12.3, trace_id="t",
            endpoint="/api/v1/agent/health-advisor/consult",
            status_code=200,
        ),
    ),
    "insight": (
        "qihuang_platform.agent.insight.metering",
        dict(
            tenant_id="tenant_default", user_id="u1", store_id="s1", code=0,
            latency_ms=12.3, trace_id="t",
            endpoint="/api/v1/agent/insight/diagnose",
            status_code=200, action="diagnose", metric_count=3, token_used=50,
        ),
    ),
    "store_coach": (
        "qihuang_platform.agent.store_coach.metering",
        dict(
            tenant_id="tenant_default", user_id="u1", store_id="s1", code=0,
            latency_ms=12.3, trace_id="t",
            endpoint="/api/v1/agent/store-coach/evaluate",
            status_code=200, action="evaluate", scene="reception",
            compliance_ok=True, token_used=80,
        ),
    ),
}


@pytest.mark.parametrize(
    "modname,kwargs", list(AGENTS.values()), ids=list(AGENTS.keys())
)
def test_record_call_persist_false(monkeypatch, modname, kwargs):
    """agent record_call 必须显式 persist=False（真值源交 charge_agent），否则双写 call_log。"""
    captured = {}

    async def fake_log(call, persist=True):
        captured["persist"] = persist
        captured["call"] = call
        return None

    # 替换模块内引用的 metering_store.log 实例方法为 spy
    module = __import__(modname, fromlist=["metering_store", "record_call"])
    monkeypatch.setattr(module.metering_store, "log", fake_log)

    # record_usage 计数，证明 persist=False 不落库（防双写）
    usage_calls = {"n": 0}

    def fake_record_usage(*a, **k):
        usage_calls["n"] += 1
        return {"code": 0, "data": {}}

    monkeypatch.setattr("qihuang_platform.billing.quota.record_usage", fake_record_usage)

    asyncio.run(module.record_call(**kwargs))

    assert "persist" in captured, (
        f"{modname}.record_call 必须调用 metering_store.log"
    )
    assert captured["persist"] is False, (
        f"{modname}.record_call 必须 persist=False（真值源交 charge_agent），"
        f"否则会与路由层 charge_agent 双写 call_log"
    )
    assert usage_calls["n"] == 0, (
        f"{modname}.record_call 不应触发 record_usage 落库（防双写回归）"
    )
