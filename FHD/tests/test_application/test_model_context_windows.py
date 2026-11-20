"""Context budgets follow the active model's window instead of a fixed 8000."""

from __future__ import annotations

import pytest

from app.application.agent_orchestrator.context_window_manager import ContextWindowManager
from app.infrastructure.llm import model_context_windows as windows


@pytest.fixture(autouse=True)
def _reset_catalog():
    windows.reset_cache()
    yield
    windows.reset_cache()


def test_known_model_uses_catalog_window():
    assert windows.context_window_for("deepseek-chat") == 131072
    assert windows.context_window_for("gpt-4o") == 128000
    assert windows.context_window_for("claude-sonnet-4-6") == 1000000
    assert windows.context_window_for("Xiaomi/MiMo-V2.6-Flash") == 1000000


def test_unknown_model_falls_back_to_default_window():
    assert windows.context_window_for("not-a-real-model") == 16384
    assert windows.context_window_for("claude-3-5-sonnet") == 16384
    assert windows.context_window_for("gateway/not-a-real-model") == 16384


@pytest.mark.asyncio
async def test_market_budget_follows_resolved_account_model():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, call

    resolve = AsyncMock(return_value=("xiaomi", "mimo-v2.6-flash"))
    adapter = SimpleNamespace(model_name="fallback", resolve_chat_route=resolve)
    provider = SimpleNamespace(_inner=SimpleNamespace(provider_id="modstore", _adapter=adapter))

    assert windows.resolve_token_budget(await windows.model_for_budget(provider)) == 32000
    assert await windows.model_for_budget(provider, "account-alias") == "xiaomi/mimo-v2.6-flash"
    assert resolve.await_args_list == [call(None, None), call(None, "account-alias")]


def test_budget_is_half_the_window_with_floor_and_ceiling():
    assert windows.resolve_token_budget("deepseek-chat") == 32000
    assert windows.resolve_token_budget("unknown-small-model") == 8192
    assert windows.resolve_token_budget("deepseek-chat", window=4000) == 4000


def test_missing_catalog_degrades_to_defaults(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(windows, "_CATALOG_PATH", missing)
    assert windows.load_catalog() == {}
    assert windows.resolve_token_budget("deepseek-chat") == 8192


def test_manager_resolves_budget_from_model_when_not_explicit():
    manager = ContextWindowManager()
    assert manager.budget_for("deepseek-chat") == 32000
    assert manager.budget_for("mimo-v2.6-flash") == 32000
    assert manager.budget_for("xiaomi/mimo-v2.6-flash") == 32000
    assert manager.budget_for(None) == 8192


def test_manager_keeps_explicit_budget():
    manager = ContextWindowManager(token_budget=900)
    assert manager.budget_for("deepseek-chat") == 900


def test_zero_explicit_budget_remains_an_explicit_minimum():
    assert ContextWindowManager(token_budget=0).budget_for("gpt-4o") == 1


@pytest.mark.asyncio
async def test_small_model_rejects_indivisible_input_before_provider_io(monkeypatch):
    from unittest.mock import AsyncMock

    from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded

    monkeypatch.setattr(windows, "load_catalog", lambda: {"models": {"tiny": 100}})
    provider = AsyncMock()
    messages = [{"role": "system", "content": "rule"}, {"role": "user", "content": "x" * 400}]
    with pytest.raises(ContextWindowExceeded):
        await ContextWindowManager().compress(
            messages, model="tiny", reserved_tokens=30, provider=provider
        )
    provider.chat_completion.assert_not_called()


@pytest.mark.asyncio
async def test_summary_uses_the_same_model_as_the_budget():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    provider = SimpleNamespace(
        provider_id="test",
        chat_completion=AsyncMock(
            return_value={
                "choices": [{"message": {"content": "summary"}}],
            }
        ),
    )
    await ContextWindowManager()._summarize_messages(
        to_summarize=[{"role": "user", "content": "old turn"}],
        user_id="u",
        trace_id=None,
        provider=provider,
        budget=2000,
        model="selected-model",
    )
    assert provider.chat_completion.call_args.kwargs["model"] == "selected-model"
