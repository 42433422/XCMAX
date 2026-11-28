"""The installed LiteLLM bridge must preserve raw metering and MCP tool rounds."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace

import pytest
from fastapi import HTTPException
from openai import DefaultAsyncHttpxClient

from modstore_server import llm_client_requests as ledger
from modstore_server import llm_responses_transport as transport
from modstore_server.llm_gateway_contract import codex_route_contract
from modstore_server.llm_model_taxonomy import model_context_capabilities
from tests.platform_model_support import isolated as isolated
from tests.test_llm_client_requests import db as db
from tests.test_openai_responses import KEY, _consume
from tests.test_openai_responses import billed as billed
from tests.test_strategic_stream_usage import real_router_runtime as real_router_runtime

MODEL = "mimo-v2.6-flash"
pytestmark = pytest.mark.filterwarnings(
    r"ignore:^Accessing the 'model_(computed_)?fields' attribute on the instance is deprecated\."
    r":pydantic.PydanticDeprecatedSince211"
    r":^litellm\.litellm_core_utils\.model_response_utils$"
)


def _body(*, stream=False, history=None):
    return {
        "model": "xiaomi/" + MODEL,
        "input": history
        or [{"role": "user", "content": [{"type": "input_text", "text": "Inspect orders"}]}],
        "tools": [
            {
                "type": "namespace",
                "name": "mcp__xcmax",
                "description": "Authorized business tools",
                "tools": [
                    {
                        "type": "function",
                        "name": "task_evidence",
                        "description": "Read task evidence",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                        "strict": True,
                    }
                ],
            }
        ],
        "max_output_tokens": 32,
        "stream": stream,
    }


@pytest.fixture
def native(billed, monkeypatch, real_router_runtime, request):
    minimax = getattr(request, "param", None) == "minimax"
    route = replace(
        billed["route"],
        provider="minimax" if minimax else "xiaomi",
        model="MiniMax-M2.7" if minimax else MODEL,
        api_key="minimaxsk-cp-fixture" if minimax else billed["route"].api_key,
        base_url=(
            "https://api.minimax.io/v1" if minimax else "https://token-plan-cn.xiaomimimo.com/v1"
        ),
    )
    capabilities = (
        {"context_window": 32000, "max_input_tokens": 24000, "max_output_tokens": 4000}
        if minimax
        else model_context_capabilities(route.provider, route.model)
    )
    billed["route"] = route
    billed["contract"] = {
        "runtime": codex_route_contract(route.provider, route.model, capabilities),
        "model_capabilities": capabilities,
    }
    state = {
        "requests": [],
        "model": route.model,
        "usage": {"prompt_tokens": 13, "completion_tokens": 3, "total_tokens": 16},
        "status": 200,
        "finish": True,
        "tool": "",
        "closed": False,
        "arguments": "{}",
    }
    sdk_http = importlib.import_module(DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0])

    class Body(sdk_http.AsyncByteStream):
        async def __aiter__(self):
            common = {
                "id": "chatcmpl-orders",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": state["model"],
            }
            frames = [
                {
                    **common,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                **(
                                    {"reasoning_content": "Inspect the tool evidence."}
                                    if minimax
                                    else {}
                                ),
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-orders",
                                        "type": "function",
                                        "function": {
                                            "name": state["tool"],
                                            "arguments": state["arguments"][:1],
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    **common,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": state["arguments"][1:]}}
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                },
            ]
            if minimax and len(state["requests"]) == 2:
                frames = [
                    {
                        **common,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "Read 3 orders."},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ]
            elif state["finish"]:
                frames.append(
                    {
                        **common,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    }
                )
            if state["usage"] is not None:
                frames.append({**common, "choices": [], "usage": state["usage"]})
            for frame in frames:
                yield ("data: " + json.dumps(frame) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            state["closed"] = True

    def respond(request):
        state["requests"].append(request)
        assert request.url.path == "/v1/chat/completions"
        if minimax:
            assert request.url.host == "api.minimax.io"
            assert request.headers["authorization"] == "Bearer sk-cp-fixture"
        else:
            assert request.headers["api-key"] == "server-only-model-key"
        body = json.loads(request.content)
        assert body["model"] == route.model
        if not minimax:
            assert body["thinking"] == {"type": "disabled"}
        assert "input" not in body and isinstance(body["messages"], list)
        state["tool"] = body["tools"][0]["function"]["name"]
        if state["status"] != 200:
            return sdk_http.Response(state["status"], json={"error": {"message": "declined"}})
        if body.get("stream"):
            assert body["stream_options"]["include_usage"] is True
            return sdk_http.Response(
                200, stream=Body(), headers={"content-type": "text/event-stream"}
            )
        result = {
            "id": "chatcmpl-orders",
            "object": "chat.completion",
            "created": 1,
            "model": state["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-orders",
                                "type": "function",
                                "function": {
                                    "name": state["tool"],
                                    "arguments": state["arguments"],
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls" if state["finish"] else None,
                }
            ],
        }
        if state["usage"] is not None:
            result["usage"] = state["usage"]
        return sdk_http.Response(200, json=result)

    def client(**options):
        assert options["follow_redirects"] is False and options["trust_env"] is False
        instance = DefaultAsyncHttpxClient(transport=sdk_http.MockTransport(respond), **options)
        billed["clients"].append(instance)
        return instance

    monkeypatch.setattr(transport, "DefaultAsyncHttpxClient", client)
    state["billed"] = billed
    return state


@pytest.mark.parametrize("native", ["minimax"], indirect=True)
async def test_minimax_subscription_returns_tool_result_and_exact_terminal_usage(native, db):
    billed = native["billed"]
    billed["route"] = replace(billed["route"], key_source="user_override")
    body = {**_body(stream=True), "model": "minimax/MiniMax-M2.7"}
    first, _ = await _consume(await billed["call"](body=body))
    call = next(item for item in first["output"] if item["type"] == "function_call")
    body["input"] += [
        *first["output"],
        {"type": "function_call_output", "call_id": call["call_id"], "output": "3 orders"},
    ]
    final, _ = await _consume(await billed["call"](body=body, key=KEY + "-followup"))
    assert final["model"] == "MiniMax-M2.7"
    assert final["output"][0]["content"][0]["text"] == "Read 3 orders."
    assert final["xcagi"]["usage"]["input_tokens"] == 13
    assert final["xcagi"]["billing_status"] == "byok"
    assert len(native["requests"]) == 2
    messages = json.loads(native["requests"][1].content)["messages"]
    assert any(message.get("tool_call_id") == call["call_id"] for message in messages)
    assert any(
        message.get("role") == "assistant"
        and message.get("reasoning_content") == "Inspect the tool evidence."
        and message.get("tool_calls")
        for message in messages
    )
    assert ledger.lookup(db, 7, KEY + "-followup", 90) == "completed"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("byok", [False, True])
async def test_real_litellm_namespace_tool_round_retains_call_id_and_original_usage(
    native, db, stream, byok
):
    billed = native["billed"]
    if byok:
        billed["route"] = replace(billed["route"], key_source="user_override")
    first = await billed["call"](body=_body(stream=stream))
    result, events = await _consume(first)
    assert result is not None, events
    assert result["model"] == MODEL
    call = next(item for item in result["output"] if item["type"] == "function_call")
    assert call["call_id"] == "call-orders" and call["arguments"] == "{}"
    assert call["name"] == "task_evidence" and call["namespace"] == "mcp__xcmax"
    assert result["xcagi"]["usage"]["input_tokens"] == 13
    assert result["xcagi"]["usage"]["output_tokens"] == 3
    assert result["xcagi"]["billing_status"] == ("byok" if byok else "settled")
    assert first.headers["x-xcmax-upstream-attempts"] == "1"
    assert "x-litellm-attempted-retries" not in first.headers
    assert ledger.lookup(db, 7, KEY, 90) == "completed"
    followup = [
        *_body()["input"],
        *result["output"],
        {
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": "3 orders",
        },
    ]
    again = await billed["call"](body=_body(stream=stream, history=followup), key=KEY + "-followup")
    second, _ = await _consume(again)
    assert second["model"] == MODEL
    messages = json.loads(native["requests"][1].content)["messages"]
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "call-orders"
        and message.get("content") == "3 orders"
        for message in messages
    )
    assert len(native["requests"]) == 2
    assert billed["wallet"].settle.await_count == (0 if byok else 2)
    assert all(client.is_closed for client in billed["clients"])


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "failure",
    ["missing-usage", "wrong-model", "http-error", "missing-finish", "incomplete-arguments"],
)
async def test_bridge_cannot_replace_missing_or_wrong_original_provider_receipt(
    native, db, stream, failure
):
    billed = native["billed"]
    if failure == "missing-usage":
        native["usage"] = None
    elif failure == "wrong-model":
        native["model"] = "different-model"
    elif failure == "missing-finish":
        native["finish"] = False
    elif failure == "incomplete-arguments":
        native["arguments"] = "{"
    else:
        native["status"] = 503
    if stream and failure != "http-error":
        result, events = await _consume(await billed["call"](body=_body(stream=True)))
        assert result is None and events[-1]["type"] == "error"
    else:
        with pytest.raises(HTTPException) as error:
            await billed["call"](body=_body(stream=stream))
        assert error.value.status_code == 409
    assert len(native["requests"]) == 1
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()


async def test_native_tool_argument_overflow_is_stopped_before_bridge_retention(
    native, db, monkeypatch
):
    from modstore_server import llm_gateway_contract

    monkeypatch.setattr(llm_gateway_contract, "MAX_STREAM_BYTES", 2048)
    native["arguments"] = '{"data":"' + "x" * 8192 + '"}'
    observed = []
    initialize = transport.ResponsesTransport.__init__

    def capture(self, *args):
        initialize(self, *args)
        observed.append(self)

    monkeypatch.setattr(transport.ResponsesTransport, "__init__", capture)
    billed = native["billed"]
    body = _body(stream=True)
    result, events = await _consume(await billed["call"](body=body))
    assert result is None and events[-1]["code"] == "CODEX_REQUEST_UNRESOLVED"
    assert observed[0].tool_arguments == {0: "{"}
    assert native["closed"] and all(client.is_closed for client in billed["clients"])
    assert len(native["requests"]) == 1 and ledger.lookup(db, 7, KEY, 90) == "settling"
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=body)
    assert error.value.status_code == 409 and len(native["requests"]) == 1


@pytest.mark.parametrize(
    "base",
    [
        "https://api.openai.com/v1",
        "https://x.openai.azure.com/v1",
        "http://remote.example/v1",
        "https://api.deepseek.com/v1?key=secret",
        "https://api.deepseek.com/v1#fragment",
        "https://user:password@api.deepseek.com/v1",
    ],
)
async def test_actual_direct_endpoint_is_rejected_before_any_wallet_or_provider_io(native, base):
    billed = native["billed"]
    billed["route"] = replace(billed["route"], base_url=base)
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=_body())
    assert (
        error.value.status_code == 412 and error.value.detail["code"] == "CODEX_MODEL_UNSUPPORTED"
    )
    assert native["requests"] == []
    billed["wallet"].preauthorize.assert_not_awaited()


@pytest.mark.parametrize("stream", [False, True])
async def test_mature_bridge_consumes_explicit_reasoning_and_compaction_without_remote_history(
    native, stream
):
    from litellm.responses.litellm_completion_transformation.compaction_items import (
        summary_only_compaction_content,
    )

    history = [
        {"role": "developer", "content": "Only use authorized business tools"},
        {
            "type": "compaction",
            "id": "cmp-orders",
            "encrypted_content": summary_only_compaction_content(
                "The previous round found 3 orders; inspect their evidence."
            ),
        },
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Need current task evidence"}],
        },
        {"role": "user", "content": "Continue inspection"},
    ]
    response = await native["billed"]["call"](body=_body(stream=stream, history=history))
    result, events = await _consume(response)
    assert result is not None, events
    forwarded = json.loads(native["requests"][0].content)
    assert "previous_response_id" not in forwarded and "conversation" not in forwarded
    assert "The previous round found 3 orders" in json.dumps(forwarded["messages"])
    assert result["xcagi"]["usage"]["total_tokens"] == 16
