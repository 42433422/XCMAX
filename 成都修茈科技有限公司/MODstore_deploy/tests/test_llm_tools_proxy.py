"""市场端 LLM 网关 tools 透传：工具调用经 /api/llm/chat/stream 到达上游并被透回。

覆盖修复：桌面端携带 tools 调用市场网关，但网关原先丢弃 tools 导致模型看不到
工具、永远不产生 tool_calls（“功能一个都没执行”）。这里验证 DTO 接收 tools、
``stream_openai_compatible`` 累计并透出 tool_calls、``chat_dispatch_stream``
把 tools/tool_choice 透传给 openai 兼容分支。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx

from modstore_server.llm_api import LlmChatDTO


def test_llm_chat_dto_accepts_tools_and_tool_choice():
    dto = LlmChatDTO(
        provider="xiaomi",
        model="mimo-v2.5-pro",
        messages=[{"role": "user", "content": "北京天气"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "查询天气",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ],
        tool_choice="auto",
    )
    assert dto.tools is not None
    assert dto.tools[0]["function"]["name"] == "get_weather"
    assert dto.tool_choice == "auto"


def test_chat_message_dto_preserves_tool_role_and_tool_calls():
    from modstore_server.llm_api import ChatMessageDTO

    # assistant 消息携带 tool_calls
    assistant = ChatMessageDTO.model_validate(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"beijing"}',
                    },
                }
            ],
        }
    )
    dumped = assistant.model_dump(exclude_none=True)
    assert dumped["tool_calls"][0]["id"] == "call_1"
    assert dumped["tool_calls"][0]["function"]["name"] == "get_weather"

    # tool 角色消息携带 tool_call_id / name
    tool_msg = ChatMessageDTO.model_validate(
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "get_weather",
            "content": "晴",
        }
    )
    tool_dumped = tool_msg.model_dump(exclude_none=True)
    assert tool_dumped["tool_call_id"] == "call_1"
    assert tool_dumped["name"] == "get_weather"


def test_stream_openai_compatible_accumulates_and_emits_tool_calls():
    from modstore_server import llm_chat_proxy, platform_model_transport

    lines = [
        'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"type":"function","function":{"name":"get_weather","arguments":""}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"{\\"city\\":\\"beijing\\"}"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    chunks = [(line + "\n\n").encode("utf-8") for line in lines]

    class Body(httpx.AsyncByteStream):
        close_calls = 0

        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

        async def aclose(self):
            self.close_calls += 1

    body = Body()
    response = httpx.Response(200, stream=body, headers={"content-type": "text/event-stream"})
    requests = []

    def respond(request):
        requests.append(request)
        return response

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    async def _collect():
        events = []
        async for ev in llm_chat_proxy.stream_openai_compatible(
            "https://api.xiaomi.example/v1",
            "sk-test",
            "mimo-v2.5-pro",
            [{"role": "user", "content": "北京天气"}],
            provider="xiaomi",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            tool_choice="auto",
        ):
            events.append(ev)
        return events

    with (
        patch.object(llm_chat_proxy.httpx, "AsyncClient", return_value=client),
        patch.object(platform_model_transport, "MAX_MODEL_STREAM_BYTES", sum(map(len, chunks))),
    ):
        events = asyncio.run(_collect())

    assert len(requests) == 1
    assert requests[0].headers["accept-encoding"] == "identity"
    assert body.close_calls == 1 and response.is_closed and client.is_closed
    toolcall = [e for e in events if e.get("type") == "toolcall"]
    assert toolcall, "应产出 toolcall 事件"
    choices = toolcall[0]["choices"]
    delta = choices[0]["delta"]
    assert choices[0]["finish_reason"] == "tool_calls"
    tc = delta["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["function"]["name"] == "get_weather"
    assert tc["function"]["arguments"] == '{"city":"beijing"}'


def test_chat_dispatch_stream_forwards_tools_to_openai_branch(monkeypatch):
    from modstore_server import llm_chat_proxy

    monkeypatch.setenv("MODSTORE_LLM_ROUTER_ENABLED", "false")
    captured = {}

    async def fake_stream_openai_compatible(
        base_url,
        api_key,
        model,
        messages,
        *,
        provider="openai",
        max_tokens=None,
        tools=None,
        tool_choice=None,
    ):
        captured["base_url"] = base_url
        captured["tools"] = tools
        captured["tool_choice"] = tool_choice
        if False:
            yield

    tools = [{"type": "function", "function": {"name": "get_weather"}}]

    async def _run():
        async for _ev in llm_chat_proxy.chat_dispatch_stream(
            "xiaomi",
            api_key="sk",
            base_url=None,
            model="mimo-v2.5-pro",
            messages=[{"role": "user", "content": "北京天气"}],
            tools=tools,
            tool_choice="auto",
        ):
            pass

    with patch.object(
        llm_chat_proxy,
        "stream_openai_compatible",
        new=fake_stream_openai_compatible,
    ):
        asyncio.run(_run())

    assert captured.get("tools") == tools
    assert captured.get("tool_choice") == "auto"


def test_same_stream_reports_processing_without_a_second_call():
    from modstore_server.llm_chat_proxy import _with_processing_status

    calls = {"n": 0}

    async def one_call():
        calls["n"] += 1
        await asyncio.sleep(0.03)
        yield {"type": "delta", "delta": "一次"}

    async def _run():
        return [item async for item in _with_processing_status(one_call(), interval=0.01)]

    events = asyncio.run(_run())
    assert calls["n"] == 1
    assert {"type": "status", "state": "processing"} in events
    assert events[-1] == {"type": "delta", "delta": "一次"}
