"""Model capability, route isolation and complete-request budget contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

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
    assert windows.context_window_for("xcmax-doubao-code") == 1024000
    assert windows.context_window_for("xcmax-kimi-code") == 1048576
    assert windows.context_window_for("xcmax-para-coding") == 200000
    assert windows.resolve_token_budget("xcmax-doubao-code") == 32000


def test_unknown_model_falls_back_to_default_window():
    assert windows.context_window_for("not-a-real-model") == 16384
    assert windows.context_window_for("claude-3-5-sonnet") == 16384
    assert windows.context_window_for("gateway/not-a-real-model") == 16384


@pytest.mark.asyncio
async def test_market_budget_follows_resolved_account_model():
    resolve = AsyncMock(return_value=("xiaomi", "mimo-v2.6-flash"))
    adapter = SimpleNamespace(model_name="fallback", resolve_chat_route=resolve)
    provider = SimpleNamespace(_inner=SimpleNamespace(provider_id="modstore", _adapter=adapter))

    assert windows.resolve_token_budget(await windows.model_for_budget(provider)) == 999744
    assert await windows.model_for_budget(provider, "account-alias") == "xiaomi/mimo-v2.6-flash"
    assert resolve.await_args_list == [call(None, None), call(None, "account-alias")]


def test_budget_reserves_only_margin_until_actual_request_is_known():
    assert windows.resolve_token_budget("deepseek-chat") == 130816
    assert windows.resolve_token_budget("unknown-small-model") == 16128
    assert windows.resolve_token_budget("deepseek-chat", window=4000) == 3744


def test_limits_distinguish_total_input_and_output_and_reserve_once():
    limits = windows.ModelLimits(
        model="route/alias", context_window=16000, max_input_tokens=14000, max_output_tokens=4096
    )
    assert limits.input_budget(output_tokens=4096, external_tokens=1000) == 10648
    assert limits.input_budget(output_tokens=1024, external_tokens=1000) == 12744
    input_only = windows.ModelLimits(max_input_tokens=14000, max_output_tokens=4096)
    assert input_only.input_budget(output_tokens=4096, external_tokens=1000) == 12744
    with pytest.raises(windows.ModelOutputLimitExceeded):
        limits.input_budget(output_tokens=4097)
    with pytest.raises(FrozenInstanceError):
        limits.max_input_tokens = 20000


def test_configurable_ceiling_cannot_create_capacity_or_revive_old_half_window():
    catalog = {
        "policy": {"reserve_ratio": 0.5, "floor": 8000, "ceiling": 32000},
        "models": {"tiny": 100, "large": 100000},
    }
    assert windows.resolve_token_budget("tiny", catalog=catalog) == 0
    assert windows.resolve_token_budget("large", catalog=catalog) == 32000
    limits = windows.ModelLimits(context_window=4000, input_ceiling=1000)
    assert limits.input_budget(output_tokens=3500) == 244
    assert limits.input_budget(external_tokens=1001) == 0


@pytest.mark.parametrize("value", [True, False, 1.5, float("nan"), float("inf"), -1, 0, "64000"])
@pytest.mark.parametrize("field", ["context_window", "max_input_tokens", "max_output_tokens"])
def test_malformed_capabilities_are_rejected_instead_of_coerced(field, value):
    with pytest.raises(ValueError, match="positive integer"):
        windows.ModelLimits(**{field: value})


@pytest.mark.parametrize("field", ["output_tokens", "external_tokens"])
@pytest.mark.parametrize("value", [True, 1.5, float("nan"), -1, "100"])
def test_request_reservations_require_non_negative_integers(field, value):
    with pytest.raises(ValueError, match="non-negative integer"):
        windows.ModelLimits(context_window=4000).input_budget(**{field: value})


def _platform(capabilities, route=("litellm", "xcmax-doubao-code")):
    adapter = SimpleNamespace(
        resolve_chat_route=AsyncMock(return_value=route),
        resolve_model_capabilities=AsyncMock(return_value=capabilities),
    )
    return SimpleNamespace(
        _inner=SimpleNamespace(provider_id="modstore", _adapter=adapter)
    ), adapter


@pytest.mark.asyncio
async def test_platform_alias_uses_current_account_limits_without_global_registration():
    first, adapter = _platform(
        {
            "max_input_tokens": 65536,
            "max_output_tokens": 8192,
            "source": "litellm_model_info",
            "resolved_model": "volcengine/verified-model",
        }
    )
    second, _ = _platform({"context_window": 8192, "max_output_tokens": 1024})
    before = windows.load_catalog().copy()
    large = await windows.resolve_model_limits(first, "account-alias", "litellm")
    small = await windows.resolve_model_limits(second)
    adapter.resolve_chat_route.assert_awaited_once_with("litellm", "account-alias")
    adapter.resolve_model_capabilities.assert_awaited_once_with("litellm", "xcmax-doubao-code")
    assert large.model == small.model == "litellm/xcmax-doubao-code"
    assert large.resolved_model == "volcengine/verified-model"
    assert large.source == "litellm_model_info"
    assert large.context_window is None
    assert large.input_budget(output_tokens=2000, external_tokens=1000) == 64280
    assert small.input_budget(output_tokens=1024, external_tokens=1000) == 5912
    assert windows.load_catalog() == before
    assert windows.context_window_for(large.model) == 16384


@pytest.mark.asyncio
async def test_nested_route_keeps_vendor_for_summary_and_final_request():
    provider, _ = _platform({"max_input_tokens": 128000}, ("openrouter", "anthropic/model"))
    assert await windows.model_for_budget(provider) == "openrouter/anthropic/model"
    assert (await windows.resolve_model_limits(provider)).model == "openrouter/anthropic/model"


@pytest.mark.asyncio
async def test_unknown_platform_capacity_stays_explicitly_conservative():
    provider, _ = _platform({})
    limits = await windows.resolve_model_limits(provider)
    assert limits.context_window == 16384
    assert limits.source == "catalog:default"
    assert limits.resolved_model is None
    assert limits.input_budget(output_tokens=2000, external_tokens=3000) == 11128


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["gpt-4o", "deepseek-chat"])
async def test_opaque_platform_alias_cannot_borrow_capacity_from_a_model_name(alias):
    provider, _ = _platform({}, ("litellm", alias))
    limits = await windows.resolve_model_limits(provider)
    assert limits.context_window == 16384
    assert limits.source == "catalog:default"
    assert limits.resolved_model is None
    assert windows.context_window_for(f"litellm/{alias}") == 16384


@pytest.mark.asyncio
async def test_genuine_provider_model_still_uses_catalog_and_alias_requires_exact_config():
    provider, _ = _platform({}, ("openai", "gpt-4o"))
    assert (await windows.resolve_model_limits(provider)).context_window == 128000
    catalog = {"models": {"gpt-4o": 128000, "litellm/gpt-4o": 32000}}
    assert windows.context_window_for("litellm/gpt-4o", catalog=catalog) == 32000


@pytest.mark.asyncio
async def test_verified_underlying_name_can_resolve_catalog_without_changing_route():
    provider, _ = _platform({"resolved_model": "gpt-4o"})
    limits = await windows.resolve_model_limits(provider)
    assert limits.context_window == 128000
    assert limits.model == "litellm/xcmax-doubao-code"
    assert limits.resolved_model == "gpt-4o"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_kind", ["direct", "factory_client", "factory_tuple"])
@pytest.mark.parametrize("explicit_model", [None, "litellm/override-alias"])
async def test_real_sdk_scopes_and_lazy_factories_use_route_capabilities(
    scope_kind, explicit_model
):
    from app.domain.shared_services.conversation.modstore_adapter import (
        ModstoreOpenAICompatibleClient,
    )
    from app.infrastructure.llm.client import llm_client_factory_scope, llm_client_scope
    from app.infrastructure.llm.providers.registry import LLMProviderRegistry

    _, adapter = _platform({"max_input_tokens": 64000, "max_output_tokens": 4096})
    adapter.resolve_default_route = lambda: ("litellm", "xcmax-doubao-code")
    client = ModstoreOpenAICompatibleClient(adapter)
    model = "litellm/xcmax-doubao-code"
    factory = Mock(return_value=(client, model) if scope_kind == "factory_tuple" else client)
    scope = (
        llm_client_scope(client, model)
        if scope_kind == "direct"
        else llm_client_factory_scope(factory)
    )
    with scope:
        provider = LLMProviderRegistry().resolve()
        limits = await windows.resolve_model_limits(provider, explicit_model)
        assert limits.max_input_tokens == 64000
        assert limits.model == model
        limits.assert_current()
        adapter.resolve_chat_route.assert_awaited_once_with(None, explicit_model or model)
        adapter.resolve_model_capabilities.assert_awaited_once_with("litellm", "xcmax-doubao-code")
        if scope_kind != "direct":
            factory.assert_called_once_with()


@pytest.mark.asyncio
async def test_scoped_sdk_guard_allows_same_client_but_rejects_replaced_scope():
    from app.domain.shared_services.conversation.modstore_adapter import (
        ModstoreOpenAICompatibleClient,
    )
    from app.infrastructure.llm.client import llm_client_scope
    from app.infrastructure.llm.providers.registry import LLMProviderRegistry
    from app.infrastructure.modstore_transport import MarketModelError

    _, adapter = _platform({"context_window": 64000})
    adapter._connection = lambda: "account-a"
    client = ModstoreOpenAICompatibleClient(adapter)
    model = "litellm/xcmax-doubao-code"
    with llm_client_scope(client, model):
        limits = await windows.resolve_model_limits(LLMProviderRegistry().resolve())
        with llm_client_scope(client, model):
            limits.assert_current()
        with llm_client_scope(ModstoreOpenAICompatibleClient(adapter), model):
            with pytest.raises(MarketModelError) as error:
                limits.assert_current()
            assert error.value.status_code == 409
        limits.assert_current()


@pytest.mark.asyncio
async def test_prepared_route_is_shared_by_capability_lookup_and_request_options():
    provider, adapter = _platform({"max_input_tokens": 48000})
    prepared = SimpleNamespace(route=("litellm", "vision-alias"))
    adapter.prepare_chat_route = AsyncMock(return_value=prepared)
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]
    limits = await windows.resolve_model_limits(provider, messages=messages)
    adapter.prepare_chat_route.assert_awaited_once_with(messages, None, None)
    adapter.resolve_chat_route.assert_not_called()
    adapter.resolve_model_capabilities.assert_awaited_once_with(
        "litellm", "vision-alias", prepared_route=prepared
    )
    assert limits.model == "litellm/vision-alias"
    assert limits.request_options == {"_prepared_chat_route": prepared, "model": limits.model}
    assert "request_options" not in repr(limits)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_model", [None, "litellm/explicit-alias"])
async def test_scoped_preparation_keeps_default_separate_from_explicit_model(explicit_model):
    from app.domain.shared_services.conversation.modstore_adapter import (
        ModstoreOpenAICompatibleClient,
    )
    from app.infrastructure.llm.client import llm_client_scope
    from app.infrastructure.llm.providers.registry import LLMProviderRegistry

    _, adapter = _platform({"context_window": 32000})
    prepared = SimpleNamespace(route=("litellm", "vision-alias"))
    adapter.prepare_chat_route = AsyncMock(return_value=prepared)
    model = "litellm/xcmax-doubao-code"
    messages = [{"role": "user", "content": "look at the attachment"}]
    with llm_client_scope(ModstoreOpenAICompatibleClient(adapter), model):
        limits = await windows.resolve_model_limits(
            LLMProviderRegistry().resolve(), explicit_model, messages=messages
        )
        adapter.prepare_chat_route.assert_awaited_once_with(
            messages, None, explicit_model, fallback_model=model
        )
        assert limits.request_options["model"] == "litellm/vision-alias"
        limits.assert_current()


@pytest.mark.asyncio
async def test_litellm_max_tokens_is_never_interpreted_as_context():
    provider, _ = _platform({"max_tokens": 1000000, "max_output_tokens": 4096})
    limits = await windows.resolve_model_limits(provider)
    assert limits.context_window == 16384
    assert "catalog:default" in limits.source
    assert limits.max_output_tokens == 4096


@pytest.mark.asyncio
async def test_provider_metadata_is_bound_to_its_selected_model():
    provider = SimpleNamespace(
        provider_id="test", model_name="first", model_info={"max_input_tokens": 64000}
    )
    assert (await windows.resolve_model_limits(provider)).max_input_tokens == 64000
    changed = await windows.resolve_model_limits(provider, "second")
    assert changed.context_window == 16384 and changed.source == "catalog:default"
    provider.model_info = {"second": {"context_window": 32000}}
    assert (await windows.resolve_model_limits(provider, "second")).context_window == 32000


@pytest.mark.asyncio
async def test_route_failure_is_not_disguised_as_missing_metadata():
    provider, adapter = _platform({})
    adapter.resolve_chat_route.side_effect = RuntimeError("route unavailable")
    with pytest.raises(RuntimeError, match="route unavailable"):
        await windows.resolve_model_limits(provider)
    adapter.resolve_model_capabilities.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_output_only_metadata_is_rejected():
    provider, _ = _platform({"max_output_tokens": 0})
    with pytest.raises(ValueError, match="max_output_tokens"):
        await windows.resolve_model_limits(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("during", ["route", "capabilities"])
async def test_account_switch_during_budget_resolution_rejects_stale_route(during):
    from app.infrastructure.modstore_transport import MarketModelError

    provider, adapter = _platform({"context_window": 64000})
    current = ["account-a"]
    adapter._connection = lambda: current[0]

    async def switched(*args):
        current[0] = "account-b"
        return ("litellm", "xcmax-doubao-code") if during == "route" else {"context_window": 64000}

    method = adapter.resolve_chat_route if during == "route" else adapter.resolve_model_capabilities
    method.side_effect = switched
    with pytest.raises(MarketModelError):
        await windows.resolve_model_limits(provider)
    if during == "route":
        adapter.resolve_model_capabilities.assert_not_called()


@pytest.mark.asyncio
async def test_resolved_limits_guard_rejects_account_switch_after_compression_await():
    from app.infrastructure.modstore_transport import MarketModelError

    provider, adapter = _platform({"context_window": 64000})
    current = ["credential-a"]
    adapter._connection = lambda: current[0]
    limits = await windows.resolve_model_limits(provider)
    limits.assert_current()
    assert "request_guard" not in repr(limits) and current[0] not in repr(limits)
    current[0] = "credential-b"
    with pytest.raises(MarketModelError) as error:
        limits.assert_current()
    assert error.value.status_code == 409


def test_missing_catalog_degrades_to_defaults(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(windows, "_CATALOG_PATH", missing)
    assert windows.load_catalog() == {}
    assert windows.resolve_token_budget("deepseek-chat") == 16128


def test_manager_resolves_budget_from_model_when_not_explicit():
    manager = ContextWindowManager()
    assert manager.budget_for("deepseek-chat") == 130816
    assert manager.budget_for("mimo-v2.6-flash") == 999744
    assert manager.budget_for("xiaomi/mimo-v2.6-flash") == 999744
    assert manager.budget_for(None) == 16128


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
