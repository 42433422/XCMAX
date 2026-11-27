"""structured_output 单元测试：提取 / 校验 / 修复循环 / 终败 / sync 桥。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from app.infrastructure.llm import structured_output as so

SCHEMA = {
    "type": "object",
    "required": ["intent"],
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "slots": {"type": "object"},
    },
}


def _llm_payload(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


class TestExtractJson:
    def test_plain_json(self):
        assert so.extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        assert so.extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_around_json(self):
        assert so.extract_json('好的，结果是：{"a": 1} 请查收') == {"a": 1}

    def test_nested_braces(self):
        assert so.extract_json('{"a": {"b": [1, 2]}, "c": "}"}') == {"a": {"b": [1, 2]}, "c": "}"}

    def test_no_json_returns_none(self):
        assert so.extract_json("完全没有 JSON") is None

    def test_array_root_returns_none(self):
        assert so.extract_json("[1, 2, 3]") is None

    def test_extract_json_closes_a_missing_wrapper_brace(self):
        raw = '```json\n{"output_schema":{"can_slice": true}\n```'
        assert so.extract_json(raw) == {"output_schema": {"can_slice": True}}
        assert so.extract_json('{"a": "未写完') is None


@pytest.mark.asyncio
class TestCompleteStructured:
    async def test_valid_first_try(self):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_llm_payload('{"intent": "x", "confidence": 0.9}')),
        ) as mock_call:
            result = await so.complete_structured(
                [{"role": "user", "content": "hi"}], schema=SCHEMA
            )
        assert result.data["intent"] == "x"
        assert result.attempts == 1 and result.repaired is False
        assert mock_call.await_count == 1

    async def test_bad_json_repaired_on_second_try(self):
        responses = [
            _llm_payload("不是 JSON"),
            _llm_payload('{"intent": "fixed"}'),
        ]
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=responses),
        ) as mock_call:
            result = await so.complete_structured(
                [{"role": "user", "content": "hi"}], schema=SCHEMA, max_repairs=2
            )
        assert result.data["intent"] == "fixed"
        assert result.attempts == 2 and result.repaired is True
        # 第二次调用带上了修复 prompt
        repair_messages = mock_call.await_args_list[1].args[0]
        assert repair_messages[-1]["role"] == "user"
        assert "未通过 JSON" in repair_messages[-1]["content"]

    async def test_schema_violation_triggers_repair(self):
        responses = [
            _llm_payload('{"wrong": 1}'),
            _llm_payload('{"intent": "ok"}'),
        ]
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=responses),
        ):
            result = await so.complete_structured(
                [{"role": "user", "content": "hi"}], schema=SCHEMA
            )
        assert result.data["intent"] == "ok"

    async def test_exhausted_repairs_raises(self):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_llm_payload("永远不是 JSON")),
        ):
            with pytest.raises(so.StructuredOutputError) as exc_info:
                await so.complete_structured(
                    [{"role": "user", "content": "hi"}], schema=SCHEMA, max_repairs=1
                )
        assert exc_info.value.attempts == 2
        assert exc_info.value.last_raw == "永远不是 JSON"

    async def test_llm_none_counts_as_failed_attempt(self):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured(
                    [{"role": "user", "content": "hi"}], schema=SCHEMA, max_repairs=0
                )

    @pytest.mark.parametrize(
        "error",
        [
            OSError("outcome unknown"),
            TimeoutError("provider outcome unknown"),
            httpx.ReadTimeout("response lost"),
            httpx.WriteTimeout("partial dispatch"),
            ValueError("429 Too Many Requests inside untrusted text"),
            *[
                httpx.HTTPStatusError(
                    "provider rejected",
                    request=httpx.Request("POST", "https://model.invalid"),
                    response=httpx.Response(code),
                )
                for code in (401, 403, 408, 409, 500)
            ],
        ],
    )
    async def test_unknown_or_denied_request_is_never_replayed_as_schema_repair(self, error):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=[error, _llm_payload('{"intent": "replayed"}')]),
        ) as call:
            with pytest.raises(type(error)) as caught:
                await so.complete_structured(
                    [{"role": "user", "content": "hi"}], schema=SCHEMA, max_repairs=2
                )
        assert caught.value is error and call.await_count == 1

    async def test_guardrail_or_missing_response_does_not_consume_repair_calls(self):
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(return_value=None)
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured([], schema=SCHEMA, max_repairs=2)
        assert call.await_count == 1

    @pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", None])
    async def test_explicit_incomplete_response_cannot_pass_with_valid_json(self, reason):
        response = _llm_payload('{"intent": "looks valid"}')
        response["choices"][0]["finish_reason"] = reason
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(return_value=response)
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured([], schema=SCHEMA, max_repairs=2)
        assert call.await_count == 1

    @pytest.mark.parametrize("content", [None, '{"intent":"looks valid"}'])
    async def test_provider_refusal_is_not_repaired(self, content):
        response = {
            "choices": [
                {"finish_reason": "stop", "message": {"content": content, "refusal": "denied"}}
            ]
        }
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(return_value=response)
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured([], schema=SCHEMA)
        assert call.await_count == 1

    async def test_malformed_message_envelope_consumes_only_bounded_repairs(self):
        response = {"choices": [{"message": "malformed"}]}
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(return_value=response)
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured([], schema=SCHEMA, max_repairs=1)
        assert call.await_count == 2

    @pytest.mark.parametrize("configured", [False, True])
    async def test_repair_count_has_a_hard_ceiling(self, monkeypatch, configured):
        monkeypatch.setenv("XCAGI_STRUCTURED_OUTPUT_MAX_REPAIRS", "1000000")
        with patch.object(
            so.invoke,
            "chat_completion_openai_format",
            AsyncMock(return_value=_llm_payload("invalid")),
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured(
                    [], schema=SCHEMA, **({"max_repairs": 1000000} if configured else {})
                )
        assert call.await_count == 3

    async def test_bad_schema_fails_before_paid_call(self):
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(return_value=_llm_payload("{}"))
        ) as call:
            with pytest.raises(SchemaError):
                await so.complete_structured([], schema={"type": "not-a-type"})
        call.assert_not_awaited()

    @pytest.mark.parametrize("entry", [so.complete_structured, so.complete_structured_bounded])
    async def test_request_deadline_cancels_retry_wait(self, entry):
        error = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("POST", "https://model.invalid"),
            response=httpx.Response(429, headers={"Retry-After": "60"}),
        )
        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(side_effect=error)
        ) as call:
            with pytest.raises(so.StructuredOutputError):
                await entry([], schema=SCHEMA, timeout_seconds=0.01)
        assert call.await_count == 1

    async def test_safe_transport_retry_budget_is_shared_with_repairs(self):
        error = httpx.ConnectTimeout("not sent")
        attempts = [error, _llm_payload("invalid"), error, error]
        with (
            patch.object(
                so.invoke, "chat_completion_openai_format", AsyncMock(side_effect=attempts)
            ) as call,
            patch.object(so.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            with pytest.raises(httpx.ConnectTimeout) as caught:
                await so.complete_structured([], schema=SCHEMA, max_repairs=2)
        assert caught.value is error and call.await_count == 4
        assert sleep.await_count == 2

    async def test_rate_limit_retry_preserves_provider_wait_and_does_not_spend_repair(self):
        error = httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("POST", "https://model.invalid"),
            response=httpx.Response(429, headers={"Retry-After": "12"}),
        )
        with (
            patch.object(
                so.invoke,
                "chat_completion_openai_format",
                AsyncMock(side_effect=[error, _llm_payload('{"intent":"done"}')]),
            ) as call,
            patch.object(so.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            result = await so.complete_structured([], schema=SCHEMA, max_repairs=0)
        assert result.attempts == 1 and not result.repaired and call.await_count == 2
        sleep.assert_awaited_once_with(12.0)

    async def test_cancellation_reaches_provider_without_repair(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def model(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch.object(
            so.invoke, "chat_completion_openai_format", AsyncMock(side_effect=model)
        ) as call:
            task = asyncio.create_task(so.complete_structured([], schema=SCHEMA))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cancelled.is_set() and call.await_count == 1

    async def test_inherited_deadline_clamps_public_api_and_provider_budget(self):
        from app.application.tool_execution_deadline import (
            invocation_deadline,
            remaining_invocation_seconds,
        )

        seen = []

        async def model(*args, **kwargs):
            seen.append(remaining_invocation_seconds(60))
            await asyncio.Event().wait()

        with (
            invocation_deadline(time.monotonic() + 0.02),
            patch.object(
                so.invoke, "chat_completion_openai_format", AsyncMock(side_effect=model)
            ) as call,
        ):
            with pytest.raises(so.StructuredOutputError):
                await so.complete_structured([], schema=SCHEMA, timeout_seconds=60)
        assert call.await_count == 1 and 0 < seen[0] <= 0.02


def test_full_json_schema_contract_and_no_silent_type_coercion():
    schema = {
        "type": "object",
        "required": ["intent", "ids"],
        "properties": {
            "intent": {"const": "approved"},
            "ids": {"type": "array", "items": {"type": "integer"}},
        },
    }
    payload = {"intent": "unapproved", "ids": [1]}
    assert not so.validate_payload(schema, payload)[0]
    payload = {"intent": "approved", "ids": "1,2"}
    assert not so.validate_payload(schema, payload)[0]
    assert payload["ids"] == "1,2"


def test_schema_refs_are_local_only():
    assert so.validate_payload({"$defs": {"x": {"type": "object"}}, "$ref": "#/$defs/x"}, {})[0]
    with pytest.raises(Unresolvable):
        so.validate_payload({"$ref": "https://model.invalid/untrusted-schema"}, {})


class TestSyncBridge:
    def test_sync_bridge_returns_result(self):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_llm_payload('{"intent": "sync"}')),
        ):
            result = so.complete_structured_sync([{"role": "user", "content": "hi"}], schema=SCHEMA)
        assert result.data["intent"] == "sync"
