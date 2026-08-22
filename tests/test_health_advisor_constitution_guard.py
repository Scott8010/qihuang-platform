"""health-advisor 体质护栏测试（2026-08-22 老黄质疑「一句失眠乏力为什么判平和质」修复）

护栏规则：舌象/脉象任一缺失 → L1 兜底体质（如平和质，score=None）降级为「暂不判定」，
不把"编的"当"辨证结果"透传给用户。有舌脉时正常返回。
"""
from unittest.mock import AsyncMock, patch

import pytest

from qihuang_platform.agent.health_advisor.orchestrator import HealthAdvisor
from qihuang_platform.agent.health_advisor.schema import (
    ConsultRequest,
    Profile,
    Syndrome,
)


@pytest.mark.asyncio
async def test_constitution_suppressed_when_tongue_pulse_missing():
    """缺舌脉：L1 兜底返回平和质 → 护栏应降级为 None（不落具体体质名）"""
    advisor = HealthAdvisor()
    req = ConsultRequest(question="最近总失眠，还容易累")

    l1_sizhen = {
        "constitution": {"type": "平和质", "description": "阴阳气血调和，精力充沛"},
        "medication": {"formulas": []},
        "tiaoli": {"diet": "宜多样化", "lifestyle": "规律作息"},
    }
    with patch("qihuang_platform.agent.health_advisor.orchestrator.L1Client.sizhen", new=AsyncMock(return_value=l1_sizhen)), \
         patch("qihuang_platform.agent.health_advisor.orchestrator.L1Client.chat", new=AsyncMock(return_value={})), \
         patch("qihuang_platform.agent.health_advisor.orchestrator.extract_syndrome_rule", return_value=Syndrome(name="心阳虚")), \
         patch.object(advisor, "_emit_metering", new=AsyncMock()):
        resp = await advisor.consult(req, tenant_id="t1")

    assert resp.constitution is None or resp.constitution.type is None, \
        f"缺舌脉时体质应降级为 None，实际: {resp.constitution}"
    assert "平和质" not in (resp.reply or ""), "回复不应出现兜底体质名"
    assert "暂不判定" in (resp.reply or "") or "补充舌象" in (resp.reply or ""), \
        "回复应明确提示体质暂不判定/需补舌脉"


@pytest.mark.asyncio
async def test_constitution_kept_when_tongue_pulse_provided():
    """有舌脉：体质正常返回（不误伤有依据的判定）"""
    advisor = HealthAdvisor()
    req = ConsultRequest(
        question="最近总失眠，还容易累",
        profile=Profile(age=45, sex="男", tongue="舌淡红苔薄白", pulse="脉细弱"),
    )

    l1_sizhen = {
        "constitution": {"type": "气虚质", "description": "元气不足，疲乏气短"},
        "medication": {"formulas": []},
        "tiaoli": {"diet": "宜食益气健脾", "lifestyle": "避免过度劳累"},
    }
    with patch("qihuang_platform.agent.health_advisor.orchestrator.L1Client.sizhen", new=AsyncMock(return_value=l1_sizhen)), \
         patch("qihuang_platform.agent.health_advisor.orchestrator.L1Client.chat", new=AsyncMock(return_value={})), \
         patch("qihuang_platform.agent.health_advisor.orchestrator.extract_syndrome_rule", return_value=Syndrome(name="心脾两虚")), \
         patch.object(advisor, "_emit_metering", new=AsyncMock()):
        resp = await advisor.consult(req, tenant_id="t1")

    assert resp.constitution is not None and resp.constitution.type == "气虚质", \
        f"有舌脉时应正常返回体质，实际: {resp.constitution}"
    assert "气虚质" in (resp.reply or "")


@pytest.mark.asyncio
async def test_health_assistant_chat_endpoint_mocked():
    """健康助手自由问答端点：mock 引擎返回 → 响应含 reply + model（从 health-advisor 拆出 #478）"""
    from fastapi import Request as FastAPIRequest

    from qihuang_platform.agent.health_assistant.router import ChatRequest, chat

    # 构造 fake request（带 tenant_id）
    class FakeScope(dict):
        pass
    scope = FakeScope({"type": "http", "method": "POST", "path": "/api/v1/agent/health-assistant/chat"})
    fake_req = FastAPIRequest(scope)
    fake_req.state.tenant_id = "t1"
    fake_user = {"tenant_id": "t1", "user_id": "u1"}

    with patch("qihuang_platform.agent.refine_llm._chat_once", new=AsyncMock(return_value="失眠多是心神不宁，建议睡前少看手机、泡泡脚。")), \
         patch("qihuang_platform.agent.health_assistant.metering.check_quota", return_value=True), \
         patch("qihuang_platform.agent.health_assistant.router._plan_per_user_limit", return_value=None):
        # 直接调用端点函数（跳过 Depends 鉴权层）
        resp = await chat(
            req=ChatRequest(question="失眠怎么办", history=[], max_tokens=800),
            request=fake_req, user=fake_user, _=None,
        )
    # chat 返回 success() 字典（code=0）
    assert resp.get("code") == 0, f"应成功: {resp}"
    data = resp.get("data", {})
    assert data.get("reply") and "失眠" in data["reply"], f"应返回回复: {data}"
    assert data.get("model") == "deepseek"
