"""Provider calls, context ownership and hard estimated-budget postconditions."""

import asyncio
import hashlib
import json
from pathlib import Path
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
@pytest.mark.parametrize("content", ["中" * 24000, "1" * 100000], ids=["chinese", "numeric"])
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
    assert first.strategy == "summarize"
    paid_batches = model.chat_completion.await_count
    assert paid_batches > 0
    assert context.summary and context.summary_covered_until >= 0
    context.conversation_history.extend([messages[-1], {"role": "assistant", "content": "回复"}])
    following = [*context.conversation_history, {"role": "user", "content": "继续"}]
    second = await manager.compress(following, provider=model, context=context)
    assert model.chat_completion.await_count == paid_batches and second.summary_llm_call is None
    assert second.post_estimated_tokens <= manager.token_budget
    another = ConversationContext(
        "different", conversation_history=list(context.conversation_history[:8])
    )
    await manager.compress(messages, provider=model, context=another)
    assert model.chat_completion.await_count > paid_batches


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
    results = await asyncio.gather(
        *(manager.compress(messages, provider=model, context=context) for _ in range(3))
    )
    assert sum(result.summary_llm_call is not None for result in results) == 1
    paid_batches = model.chat_completion.await_count
    context.conversation_history[0] = {"role": "user", "content": "新" * 100}
    await manager.compress(
        [*context.conversation_history, messages[-1]], provider=model, context=context
    )
    assert model.chat_completion.await_count > paid_batches


@pytest.mark.asyncio
async def test_failed_summary_does_not_discard_history_or_orphan_tool_replies():
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
    original = [*history, *latest]
    with pytest.raises(ContextWindowExceeded):
        await manager.compress(original, provider=model)
    assert original[-3:] == latest and original[:-3] == history


@pytest.mark.asyncio
async def test_provider_oversized_summary_cannot_escape_postcondition():
    model = provider()
    model.chat_completion.return_value = {"choices": [{"message": {"content": "中" * 10000}}]}
    manager = ContextWindowManager(token_budget=1100, recent_keep=2)
    messages = [{"role": "user", "content": "中" * 100} for _ in range(8)]
    with pytest.raises(ContextWindowExceeded):
        await manager.compress(messages, provider=model)


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
    paid_batches = model.chat_completion.await_count
    assert paid_batches > 0
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
        model.chat_completion.await_count == paid_batches
        and result.post_estimated_tokens <= manager.token_budget
    )


@pytest.mark.asyncio
async def test_summary_budget_reserves_its_own_output_without_planner_tools():
    from app.infrastructure.llm.model_context_windows import ModelLimits

    prepared_route = object()
    limits = ModelLimits(
        model="litellm/xcmax-doubao-code",
        context_window=2200,
        max_input_tokens=2200,
        max_output_tokens=1000,
        source="deployment",
        safety_margin_tokens=0,
        request_options={
            "_prepared_chat_route": prepared_route,
            "model": "litellm/xcmax-doubao-code",
        },
    )
    model = provider()
    history = [{"role": "user", "content": f"历史{i}：" + "中" * 180} for i in range(10)]
    latest = {"role": "user", "content": "保留这个最新请求"}
    result = await ContextWindowManager(recent_keep=1, summarize_max_tokens=96).compress(
        [*history, latest],
        provider=model,
        model_limits=limits,
        output_tokens=300,
        external_tokens=800,
    )
    assert result.post_estimated_tokens <= limits.input_budget(
        output_tokens=300, external_tokens=800
    )
    assert result.messages[-1] == latest
    summary_requests = [call.kwargs for call in model.chat_completion.await_args_list]
    assert summary_requests
    for request in summary_requests:
        assert request["model"] == limits.model
        assert request["_prepared_chat_route"] is prepared_route
        assert not {"tools", "functions", "tool_choice"} & request.keys()
        assert estimate_messages_tokens(request["messages"]) <= limits.input_budget(
            output_tokens=96
        )
        assert latest["content"] not in str(request["messages"])
    assert max(estimate_messages_tokens(r["messages"]) for r in summary_requests) > 1100


@pytest.mark.asyncio
async def test_interrupted_tool_turn_stays_whole_when_user_clarifies():
    model = provider()
    latest = [
        {"role": "user", "content": "按A口径执行"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "pending",
                    "type": "function",
                    "function": {
                        "name": "read_business",
                        "arguments": '{"scope":"A"}',
                    },
                },
            ],
        },
        {"role": "user", "content": "确认A，只读"},
    ]
    history = [{"role": "user", "content": "旧" * 180} for _ in range(8)]
    result = await ContextWindowManager(token_budget=1100, recent_keep=1).compress(
        [*history, *latest],
        provider=model,
    )
    assert result.messages[-3:] == latest
    assert all(
        "确认A，只读" not in str(call.kwargs["messages"])
        for call in model.chat_completion.await_args_list
    )


@pytest.mark.asyncio
async def test_failed_incremental_batch_does_not_replace_existing_summary():
    from app.application.agent_orchestrator.context_window_manager import summary_fingerprint

    history = [{"role": "user", "content": "旧" * 120} for _ in range(14)]
    context = ConversationContext("u", conversation_history=history)
    context.summary = "先前有效摘要：等待审批，未执行"
    context.summary_covered_until = 1
    context.summary_fingerprint = summary_fingerprint(history[:2])
    before = (context.summary, context.summary_covered_until, context.summary_fingerprint)
    model = provider()
    model.chat_completion.side_effect = [
        {"choices": [{"message": {"content": "第一批摘要"}}]},
        RuntimeError("second batch failed"),
    ]
    with pytest.raises(ContextWindowExceeded):
        await ContextWindowManager(token_budget=900, recent_keep=1).compress(
            [*history, {"role": "user", "content": "继续等待审批"}],
            provider=model,
            context=context,
        )
    assert model.chat_completion.await_count == 2
    assert (context.summary, context.summary_covered_until, context.summary_fingerprint) == before
    assert context.conversation_history == history


@pytest.mark.asyncio
async def test_account_switch_in_summary_blocks_next_batch_and_cache_commit(monkeypatch):
    from app.infrastructure.llm.model_context_windows import ModelLimits
    from app.infrastructure.modstore_transport import MarketModelError

    current = ["account-a"]

    def guard():
        if current[0] != "account-a":
            raise MarketModelError({"status": 409})

    limits = ModelLimits(
        model="litellm/alias",
        context_window=900,
        source="deployment",
        safety_margin_tokens=0,
        request_guard=guard,
    )
    model = provider()

    async def switch_account(**_):
        current[0] = "account-b"
        return {
            "choices": [{"message": {"content": "旧账号摘要"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

    model.chat_completion.side_effect = switch_account
    calls = []
    monkeypatch.setattr(
        ContextWindowManager, "_record_summary_usage", lambda _, call: calls.append(call)
    )
    history = [{"role": "user", "content": "旧" * 120} for _ in range(14)]
    context = ConversationContext("account-a", conversation_history=history)
    with pytest.raises(MarketModelError):
        await ContextWindowManager(recent_keep=1).compress(
            [*history, {"role": "user", "content": "继续"}],
            user_id="account-a",
            provider=model,
            context=context,
            model_limits=limits,
        )
    assert model.chat_completion.await_count == 1
    assert not context.summary and context.summary_covered_until == -1
    assert context.conversation_history == history
    assert len(calls) == 1 and calls[0].status == "failed"
    assert calls[0].total_tokens == 7 and calls[0].metadata["user_id"] == "account-a"


@pytest.mark.asyncio
async def test_fixed_overflow_diagnostics_and_output_limit_are_distinct():
    from app.infrastructure.llm.model_context_windows import ModelLimits

    limits = ModelLimits(
        model="alias",
        context_window=500,
        max_input_tokens=500,
        max_output_tokens=100,
        source="default",
        safety_margin_tokens=0,
    )
    model = provider()
    with pytest.raises(ContextWindowExceeded) as invalid_output:
        await ContextWindowManager().compress(
            [{"role": "user", "content": "你好"}],
            provider=model,
            model_limits=limits,
            output_tokens=101,
        )
    assert invalid_output.value.reason == "model_output_limit_exceeded"
    with pytest.raises(ContextWindowExceeded) as fixed:
        await ContextWindowManager().compress(
            [{"role": "system", "content": "固" * 500}, {"role": "user", "content": "你好"}],
            provider=model,
            model_limits=limits,
            output_tokens=100,
        )
    assert fixed.value.reason == "fixed_context_overflow"
    assert fixed.value.diagnostics["capability_source"] == "default"
    assert fixed.value.diagnostics["system_tokens"] > fixed.value.diagnostics["budget_tokens"]
    assert "分批提交" not in str(fixed.value)
    model.chat_completion.assert_not_awaited()


def test_openhands_component_is_pinned_and_license_preserved():
    import tomllib

    from setuptools import find_packages

    from app.infrastructure.llm._vendor import openhands_condenser

    directory = Path(openhands_condenser.__file__).parent
    provenance = json.loads((directory / "PROVENANCE.json").read_text())
    assert provenance["upstream_commit"] == "885242b563b1d2695d6c7b3d4bfe642f1c8838a3"
    assert "OpenHands contributors" in (directory / "LICENSE").read_text()
    for name, digest in provenance["local_sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    project = Path(__file__).resolve().parents[2]
    package = "app.infrastructure.llm._vendor.openhands_condenser"
    assert package in find_packages(where=str(project), include=["app*"])
    config = tomllib.loads((project / "pyproject.toml").read_text())
    assert {"LICENSE", "PROVENANCE.json"} <= set(
        config["tool"]["setuptools"]["package-data"][package]
    )
