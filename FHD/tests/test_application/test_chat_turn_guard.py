"""Locks the chat failure chain: visible model text, preview gate, and idempotent retry."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.application.chat_turn_guard import (
    chunk_display_text,
    is_bulk_destructive,
    joined_display_text,
    mutation_block,
    mutation_policy,
    note_tool_commit,
    prepare_turn,
    reset_turn_ledger,
)
from app.legacy.chat import legacy_chat_adapter as adapter
from app.legacy.chat.legacy_chat_runtime import chat, chat_stream_sse_events, chat_stream_text


@pytest.fixture(autouse=True)
def _isolated_turn_ledger():
    reset_turn_ledger()
    yield
    reset_turn_ledger()


def test_keeps_displayable_text_and_rejects_whitespace_or_reasoning():
    assert joined_display_text(["  ", "已保留正文"]) == "  已保留正文"
    assert joined_display_text([" \n\t"]) is None
    choice = SimpleNamespace(
        delta=SimpleNamespace(content=None, reasoning_content="只是思考"),
        message=SimpleNamespace(content="客户仍在，未删除。"),
    )
    assert chunk_display_text(choice) == "客户仍在，未删除。"
    reasoning_only = SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="只是思考"), message=None)
    assert chunk_display_text(reasoning_only) == ""


def test_bulk_preview_names_scope_and_does_not_call_the_model():
    client = MagicMock()
    result = chat(
        "清理全部客户和产品",
        client=client,
        runtime_context={
            "tenant_id": "XCAGI-ENTERPRISE-DEMO",
            "turn_id": "turn-1",
            "scope_counts": {"customers": 4, "products": 9},
        },
    )
    client.chat.completions.create.assert_not_called()
    assert result["execution"]["committed"] is False
    assert result["execution"]["effect"] == "preview"
    assert "XCAGI-ENTERPRISE-DEMO" in result["response"]
    assert "客户 4 条" in result["response"]
    assert "产品 9 条" in result["response"]
    assert "尚未写入" in result["response"]
    assert is_bulk_destructive("删除所有订单")
    assert not is_bulk_destructive("删除这个客户")


def test_stream_shows_message_body_when_delta_content_is_empty():
    chunk = MagicMock()
    chunk.choices = [MagicMock(finish_reason="stop")]
    chunk.choices[0].delta = SimpleNamespace(content=None, tool_calls=None)
    chunk.choices[0].message = SimpleNamespace(content="可见的模型正文")
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.return_value = iter([chunk])
    parts = list(chat_stream_text("你好", client=client, model="test-model"))
    assert "可见的模型正文" in parts
    assert not any(isinstance(part, dict) and part.get("error") == "planner_empty_response" for part in parts)


def test_whitespace_stream_stays_an_explicit_empty_result():
    chunk = MagicMock()
    chunk.choices = [MagicMock(finish_reason="stop")]
    chunk.choices[0].delta = SimpleNamespace(content="  \n", tool_calls=None)
    chunk.choices[0].message = None
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.return_value = iter([chunk])
    parts = list(chat_stream_text("你好", client=client, model="test-model"))
    assert any(isinstance(part, dict) and part.get("error") == "planner_empty_response" for part in parts)


def test_retry_and_second_confirm_do_not_write():
    ctx = {"tenant_id": "demo", "idempotency_key": "turn-1", "destructive_confirmed": True, "scope_counts": {"customers": 1, "products": 1}}
    assert prepare_turn("清理全部客户和产品", ctx) is None
    assert mutation_policy() == "allow_once"
    blocked = mutation_block("delete_customers", '{"all": true}', {"mutation_policy": "model_only", "idempotency_key": "turn-1"})
    assert blocked["committed"] is False
    note_tool_commit(ctx, "delete_customers")
    again = prepare_turn("清理全部客户和产品", {"idempotency_key": "turn-1", "destructive_confirmed": True, "tenant_id": "demo"})
    assert again["execution"]["committed"] is True
    retry_ctx = {"idempotency_key": "turn-1", "retry_of": "turn-1"}
    assert prepare_turn("清理全部客户和产品", retry_ctx) is None
    assert mutation_policy() == "model_only"
    assert mutation_block("delete_customers", "{}", retry_ctx)["error"] == "already_committed"


def test_stream_keeps_the_execution_record_through_preview_commit_and_retry(monkeypatch):
    executed: list[str] = []

    def execute(name, _arguments, *_args, **_kwargs):
        executed.append(name)
        return '{"success": true}'

    monkeypatch.setattr(adapter, "_get_workflow_tool_registry", lambda: [])
    monkeypatch.setattr(adapter, "_resolve_chat_execute_tool", lambda: execute)
    ctx = {
        "tenant_id": "demo-tenant",
        "idempotency_key": "turn-bulk",
        "turn_id": "turn-bulk",
        "scope_counts": {"customers": 2, "products": 3},
    }
    preview = list(chat_stream_sse_events("清理全部客户和产品", runtime_context=ctx, client=MagicMock()))
    assert preview[-1]["result"]["execution"]["effect"] == "preview"
    assert preview[-1]["result"]["execution"]["committed"] is False
    assert executed == []

    def chunk(content="", calls=None, finish="stop"):
        return SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=calls or []),
                finish_reason=finish,
            )]
        )

    call = SimpleNamespace(index=0, id="call-1", function=SimpleNamespace(name="delete_all_customers", arguments="{}"))
    rounds = iter([
        iter([chunk(calls=[call], finish="tool_calls")]),
        iter([chunk("  \n")]),
    ])
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.side_effect = lambda **_: next(rounds)
    confirmed = {**ctx, "destructive_confirmed": True}
    failed = list(chat_stream_sse_events("清理全部客户和产品", runtime_context=confirmed, client=client, model="test"))
    assert executed == ["delete_all_customers"]
    assert failed[-1]["type"] == "error"
    assert failed[-1]["execution"]["committed"] is True
    assert failed[-1]["result"]["execution"]["effect"] == "committed"

    retry = list(chat_stream_sse_events(
        "清理全部客户和产品",
        runtime_context={**ctx, "retry_of": "turn-bulk"},
        client=MagicMock(is_modstore_openai_compatible=False, chat=MagicMock(
            completions=MagicMock(create=MagicMock(return_value=iter([chunk("只回答，不删除。")])))
        )),
        model="test",
    ))
    assert executed == ["delete_all_customers"]
    assert retry[-1]["result"]["execution"]["committed"] is True


def test_uncommitted_confirm_is_not_repeated_by_another_confirm():
    first = {"idempotency_key": "turn-2", "destructive_confirmed": True, "tenant_id": "demo", "scope_counts": {"customers": 0, "products": 0}}
    assert prepare_turn("清空所有产品", first) is None
    second = {"idempotency_key": "turn-2", "destructive_confirmed": True, "tenant_id": "demo"}
    reply = prepare_turn("清空所有产品", second)
    assert mutation_policy() == "model_only"
    assert reply["execution"]["committed"] is False
    assert "不会执行删除" in reply["response"]
