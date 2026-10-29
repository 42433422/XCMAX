"""Provider calls, context ownership and hard estimated-budget postconditions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.agent_orchestrator.context_window_manager import (
    ContextWindowExceeded,
    ContextWindowManager,
    estimate_messages_tokens,
)
from app.domain.shared_services.conversation.context import ConversationContext


def provider():
    return SimpleNamespace(
        provider_id="fake",
        model_name="fake",
        chat_completion=AsyncMock(
            return_value={"choices": [{"message": {"content": "历史摘要"}}], "usage": {}}
        ),
    )


@pytest.fixture(autouse=True)
def no_external_billing(monkeypatch):
    monkeypatch.setattr(ContextWindowManager, "_record_summary_usage", lambda *_: None)


@pytest.mark.asyncio
async def test_fourteen_short_messages_have_no_summary_call():
    model = provider()
    messages = [{"role": "user", "content": "你好"} for _ in range(14)]
    result = await ContextWindowManager().compress(messages, provider=model)
    assert result.strategy == "noop" and result.messages == messages
    model.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["中" * 24000, "1" * 50000])
async def test_oversized_latest_input_is_rejected_before_provider_io(content):
    model = provider()
    with pytest.raises(ContextWindowExceeded):
        await ContextWindowManager().compress(
            [{"role": "user", "content": content}], provider=model
        )
    model.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserves_output_and_tool_schema_budget_without_truncating_latest_input():
    manager = ContextWindowManager(token_budget=200)
    messages = [{"role": "user", "content": "中" * 80}]
    assert (await manager.compress(messages)).strategy == "noop"
    with pytest.raises(ContextWindowExceeded):
        await manager.compress(messages, reserved_tokens=100)


@pytest.mark.asyncio
async def test_summary_reuses_covered_history_and_survives_append_without_cross_user_cache():
    manager = ContextWindowManager(token_budget=1100, recent_keep=4)
    model = provider()
    context = ConversationContext("owner")
    context.conversation_history = [{"role": "user", "content": "中" * 100} for _ in range(8)]
    messages = [*context.conversation_history, {"role": "user", "content": "接着说"}]
    first = await manager.compress(messages, provider=model, context=context)
    assert first.strategy == "summarize" and model.chat_completion.await_count == 1
    assert context.summary and context.summary_covered_until >= 0
    context.conversation_history.extend([messages[-1], {"role": "assistant", "content": "回复"}])
    following = [*context.conversation_history, {"role": "user", "content": "继续"}]
    second = await manager.compress(following, provider=model, context=context)
    assert model.chat_completion.await_count == 1 and second.summary_llm_call is None
    assert second.post_estimated_tokens <= manager.token_budget
    another = ConversationContext(
        "different", conversation_history=list(context.conversation_history[:8])
    )
    await manager.compress(messages, provider=model, context=another)
    assert model.chat_completion.await_count == 2


@pytest.mark.asyncio
async def test_parallel_same_context_reuses_summary_and_history_edit_invalidates_it():
    manager = ContextWindowManager(token_budget=1100, recent_keep=4)
    model = provider()
    context = ConversationContext(
        "u", conversation_history=[{"role": "user", "content": "中" * 100} for _ in range(8)]
    )
    messages = [*context.conversation_history, {"role": "user", "content": "现在"}]
    reply = model.chat_completion.return_value

    async def delayed(**_):
        await asyncio.sleep(0.01)
        return reply

    model.chat_completion.side_effect = delayed
    await asyncio.gather(
        *(manager.compress(messages, provider=model, context=context) for _ in range(3))
    )
    assert model.chat_completion.await_count == 1
    context.conversation_history[0] = {"role": "user", "content": "新" * 100}
    await manager.compress(
        [*context.conversation_history, messages[-1]], provider=model, context=context
    )
    assert model.chat_completion.await_count == 2


@pytest.mark.asyncio
async def test_fallback_obeys_budget_and_does_not_orphan_tool_replies():
    manager = ContextWindowManager(token_budget=450, recent_keep=6)
    model = provider()
    model.chat_completion.side_effect = RuntimeError("controlled provider failure")
    history = [{"role": "user", "content": "中" * 100} for _ in range(10)]
    latest = [
        {"role": "user", "content": "新请求"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call", "type": "function", "function": {"name": "read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call", "content": "结果"},
    ]
    result = await manager.compress([*history, *latest], provider=model)
    assert result.post_estimated_tokens <= manager.token_budget
    assert result.messages[-3:] == latest
    assert estimate_messages_tokens(result.messages) == result.post_estimated_tokens


@pytest.mark.asyncio
async def test_provider_oversized_summary_cannot_escape_postcondition():
    model = provider()
    model.chat_completion.return_value = {"choices": [{"message": {"content": "中" * 10000}}]}
    manager = ContextWindowManager(token_budget=1100, recent_keep=2)
    messages = [{"role": "user", "content": "中" * 100} for _ in range(8)]
    result = await manager.compress(messages, provider=model)
    assert result.strategy == "truncate" and result.post_estimated_tokens <= manager.token_budget


@pytest.mark.asyncio
async def test_api_rejects_schema_plus_output_over_budget_before_main_provider(monkeypatch):
    from app.domain.shared_services.conversation.api_llm import ConversationLlmMixin

    model = provider()
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: model
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.context_window_manager.get_context_window_manager",
        lambda: ContextWindowManager(token_budget=200),
    )
    service = ConversationLlmMixin()
    result = await service.call_llm_api(
        [{"role": "user", "content": "请求"}],
        max_tokens=100,
        tools=[{"function": {"name": "read", "description": "1" * 1000}}],
    )
    assert result["error"]["code"] == "context_window_exceeded"
    model.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_roll_preserves_summary_coverage_without_resummarizing(monkeypatch):
    from app.domain.shared_services.conversation.manager import AIConversationService

    monkeypatch.setenv("FHD_CONVERSATION_HISTORY_MAX", "10")
    service = AIConversationService.__new__(AIConversationService)
    context = ConversationContext(
        "u", conversation_history=[{"role": "user", "content": "中" * 100} for _ in range(10)]
    )
    service.contexts = {"u": context}
    model = provider()
    manager = ContextWindowManager(token_budget=1400, recent_keep=4)
    await manager.compress(
        [*context.conversation_history, {"role": "user", "content": "新请求"}],
        provider=model,
        context=context,
    )
    assert model.chat_completion.await_count == 1
    covered = context.summary_covered_until
    service.add_to_history("u", "user", "新请求")
    service.add_to_history("u", "assistant", "答复")
    assert context.summary_covered_until == covered - 2 and context.summary
    result = await manager.compress(
        [*context.conversation_history, {"role": "user", "content": "继续"}],
        provider=model,
        context=context,
    )
    assert (
        model.chat_completion.await_count == 1
        and result.post_estimated_tokens <= manager.token_budget
    )
