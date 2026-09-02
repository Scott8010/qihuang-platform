"""
tests/test_metering.py — 计量真落库验证（#664 / #663 根治「计量写 0」）

背景：上一轮安全审计里汇报的「下一步（可选）」——metering 此前只写内存、
不落库（重启即丢、配额/对账全基于空数据）。本轮把 MeteringStore.log 接上
billing.quota.record_usage 真写 call_log 表，并防两处双写（中间件 vs agent
自身 record_call；health_assistant 的 log vs charge_call）。

本文件用 monkeypatch 把 record_usage 换成桩，纯单元断言落库通路接通，
不依赖真实 DB，CI 稳定不 flaky。
"""
import asyncio

import pytest


class TestMeteringPersist:
    """MeteringStore.log 的 persist 开关行为"""

    def test_persist_true_writes_db(self, monkeypatch):
        """persist=True 必须真调 record_usage 把调用写进 call_log 表"""
        cap = {}

        def fake_record_usage(*args, **kwargs):
            cap["args"] = args
            cap["kwargs"] = kwargs
            return {"code": 0, "data": {}}

        monkeypatch.setattr(
            "qihuang_platform.billing.quota.record_usage", fake_record_usage
        )

        from qihuang_platform.gateway.metering import metering_store, CallLog

        call = CallLog(
            tenant_id="tenant_default",
            endpoint="/api/v1/test/x",
            method="POST",
            status_code=200,
            latency_ms=1.2,
            tokens_used=10,
            cost_cents=5,
            trace_id="t1",
        )
        asyncio.run(metering_store.log(call, persist=True))

        assert cap, "persist=True 必须真调 record_usage 落库 call_log 表"
        assert cap["args"][0] == "tenant_default"
        assert cap["args"][1] == "/api/v1/test/x"
        assert cap["args"][5] == 10   # tokens_used 位置参数
        assert cap["args"][6] == 5    # cost_cents 位置参数

    def test_persist_false_skips_db(self, monkeypatch):
        """persist=False 不应调 record_usage（防与 agent 自身 record_call 双写）"""
        called = {"n": 0}

        def fake_record_usage(*args, **kwargs):
            called["n"] += 1
            return {"code": 0, "data": {}}

        monkeypatch.setattr(
            "qihuang_platform.billing.quota.record_usage", fake_record_usage
        )

        from qihuang_platform.gateway.metering import metering_store, CallLog

        call = CallLog(tenant_id="tenant_default", endpoint="/x", method="GET", status_code=200)
        asyncio.run(metering_store.log(call, persist=False))

        assert called["n"] == 0, "persist=False 不应调 record_usage（防双写）"

    def test_anonymous_skips_db(self, monkeypatch):
        """匿名 / 无租户上下文不应落库，避免脏 null 记录"""
        called = {"n": 0}

        def fake_record_usage(*args, **kwargs):
            called["n"] += 1
            return {"code": 0, "data": {}}

        monkeypatch.setattr(
            "qihuang_platform.billing.quota.record_usage", fake_record_usage
        )

        from qihuang_platform.gateway.metering import metering_store, CallLog

        call = CallLog(tenant_id=None, endpoint="/x", method="GET", status_code=200)
        asyncio.run(metering_store.log(call, persist=True))

        assert called["n"] == 0, "匿名/无租户上下文不应落库（避免脏 null 记录）"


class TestMeteringMiddlewarePersist:
    """MeteringMiddleware 按路径/状态码决定 persist（#663）"""

    def test_should_persist_call_rules(self):
        """纯单元断言 should_persist 判定规则（防双写 + 只记成功）"""
        from qihuang_platform.gateway.middleware import _should_persist_call

        # 非 agent 成功端点 -> 落库
        assert _should_persist_call("/api/v1/protected/hello", 200) is True
        assert _should_persist_call("/api/v1/capability/x", 200) is True
        # agent 业务路径 -> 不落库（由 agent 自身 record_call 负责，防双写）
        assert _should_persist_call("/api/v1/agent/health-advisor/chat", 200) is False
        assert _should_persist_call("/api/v1/agent/health-assistant/chat", 200) is False
        # 失败响应 -> 不落库（与「成功才计」一致）
        assert _should_persist_call("/api/v1/protected/hello", 402) is False
        assert _should_persist_call("/api/v1/capability/x", 500) is False
        # agent + 失败 -> 不落库
        assert _should_persist_call("/api/v1/agent/x", 500) is False

    def test_non_agent_success_persists(self, client, user_headers, monkeypatch):
        """集成测：非 agent 成功端点经中间件真落库（capability 等核心端点）"""
        called = {"n": 0}

        def fake_record_usage(*args, **kwargs):
            called["n"] += 1
            return {"code": 0, "data": {}}

        monkeypatch.setattr(
            "qihuang_platform.billing.quota.record_usage", fake_record_usage
        )

        resp = client.get("/api/v1/protected/hello", headers=user_headers)
        assert resp.status_code == 200
        assert called["n"] >= 1, "非 agent 成功端点必须经中间件真落库（#663）"
