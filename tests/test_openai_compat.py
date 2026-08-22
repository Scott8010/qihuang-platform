"""OpenAI 兼容层测试（Open WebUI 接入健康助手，2026-08-23 老黄拍板）

端点：
  GET  /v1/models            → Bearer app_key 鉴权，返回 health-assistant
  POST /v1/chat/completions  → OpenAI 协议（非流式 + SSE 流式），转发 health-assistant 链路
"""
import pytest


@pytest.fixture
def fake_llm(monkeypatch):
    """测试环境无 LLM key：mock 文本链路固定回复 + 配额放行。"""
    import importlib
    # health_assistant/__init__.py 把 router 名绑定成 APIRouter，字符串路径会解析错，
    # 必须 importlib 取真正的子模块对象再 patch
    ha_router = importlib.import_module("qihuang_platform.agent.health_assistant.router")

    async def _fake_text_reply(user_msg, history, system, max_tokens):
        return "我是健康助手（mock）：" + user_msg[:20], "deepseek"
    monkeypatch.setattr(ha_router, "_text_reply", _fake_text_reply)
    monkeypatch.setattr("qihuang_platform.agent.openai_compat.check_quota", lambda tenant_id: True)
    yield


class TestOpenAICompatModels:
    def test_models_unauthorized(self, client):
        r = client.get("/v1/models")
        assert r.status_code == 401
        assert "error" in r.json()

    def test_models_invalid_key(self, client):
        r = client.get("/v1/models", headers={"Authorization": "Bearer bad_key_xxx"})
        assert r.status_code == 401

    def test_models_ok(self, client, api_key_info):
        r = client.get("/v1/models",
                       headers={"Authorization": f"Bearer {api_key_info['app_key']}"})
        assert r.status_code == 200
        assert any(m["id"] == "health-assistant" for m in r.json()["data"])


class TestOpenAICompatChat:
    def test_chat_unauthorized(self, client):
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 401

    def test_chat_invalid_key(self, client, fake_llm):
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "hi"}]},
                        headers={"Authorization": "Bearer bad_key_xxx"})
        assert r.status_code == 401

    def test_chat_no_user_msg_rejected(self, client, api_key_info, fake_llm):
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "assistant", "content": "hi"}]},
                        headers={"Authorization": f"Bearer {api_key_info['app_key']}"})
        assert r.status_code == 400

    def test_chat_nonstream(self, client, api_key_info, fake_llm):
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "最近失眠怎么办"}]},
                        headers={"Authorization": f"Bearer {api_key_info['app_key']}"})
        assert r.status_code == 200
        j = r.json()
        assert j["object"] == "chat.completion"
        assert j["model"] == "deepseek"
        assert j["choices"][0]["message"]["content"].startswith("我是健康助手")
        assert j["choices"][0]["finish_reason"] == "stop"

    def test_chat_stream(self, client, api_key_info, fake_llm):
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "怕冷怎么办"}],
                              "stream": True},
                        headers={"Authorization": f"Bearer {api_key_info['app_key']}"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        assert "data: [DONE]" in r.text
        assert "chat.completion.chunk" in r.text
        assert "健康助手" in r.text

    def test_chat_history_last_user_as_question(self, client, api_key_info, fake_llm):
        r = client.post("/v1/chat/completions",
                        json={"messages": [
                            {"role": "user", "content": "我失眠"},
                            {"role": "assistant", "content": "建议调理"},
                            {"role": "user", "content": "手心热"},
                        ]},
                        headers={"Authorization": f"Bearer {api_key_info['app_key']}"})
        assert r.status_code == 200
        # 最后一条 user 消息作为问题，mock 回复会带出该问题
        assert "手心热" in r.json()["choices"][0]["message"]["content"]
