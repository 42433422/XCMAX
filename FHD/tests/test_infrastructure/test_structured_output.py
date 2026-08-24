"""structured_output 单元测试：提取 / 校验 / 修复循环 / 终败 / sync 桥。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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

    async def test_forwards_explicit_owner_provider(self):
        owner_provider = object()
        conversation_service = object()
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_llm_payload('{"intent": "owner"}')),
        ) as mock_call:
            result = await so.complete_structured(
                [{"role": "user", "content": "hi"}],
                schema=SCHEMA,
                provider=owner_provider,
                conversation_service=conversation_service,
            )
        assert result.data["intent"] == "owner"
        assert mock_call.await_args.kwargs["provider"] is owner_provider
        assert mock_call.await_args.kwargs["conversation_service"] is conversation_service

    async def test_explicit_owner_provider_runs_end_to_end(self):
        class OwnerProvider:
            async def chat_completion(self, messages, **kwargs):
                assert messages[0]["content"] == "hi"
                assert kwargs["temperature"] == 0.3
                return _llm_payload('{"intent": "session-owner"}')

        result = await so.complete_structured(
            [{"role": "user", "content": "hi"}],
            schema=SCHEMA,
            provider=OwnerProvider(),
            max_repairs=0,
        )
        assert result.data["intent"] == "session-owner"

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

    async def test_llm_exception_counts_as_failed_attempt(self):
        responses = [OSError("net down"), _llm_payload('{"intent": "recovered"}')]
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=responses),
        ):
            result = await so.complete_structured(
                [{"role": "user", "content": "hi"}], schema=SCHEMA, max_repairs=1
            )
        assert result.data["intent"] == "recovered"


class TestSyncBridge:
    def test_sync_bridge_returns_result(self):
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_llm_payload('{"intent": "sync"}')),
        ):
            result = so.complete_structured_sync([{"role": "user", "content": "hi"}], schema=SCHEMA)
        assert result.data["intent"] == "sync"
