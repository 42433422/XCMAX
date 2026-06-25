"""Second-wave behavioral tests for app.services.conversation.api (ApiMixin).

Targets previously-uncovered lines/branches:
- _coerce_int except branch (TypeError/ValueError)
- _get_deepseek_async_client loop-cache create / reuse / recreate
- call_llm_api neuro_notify failure swallowed
- _call_deepseek_legacy: record_model_usage failure, neuro_notify failure,
  httpx.HTTPError branch, generic RECOVERABLE_ERRORS branch, empty-choices warning
- _execute_or_generate_response pending-intent merge_slots branch
- _build_system_prompt_with_persona fallback + persona path
- _call_ai persona build path, history truncation, modstore/llm_adapter mode tags,
  provider/model selection branches (modstore / llm_adapter / deepseek-legacy)

These avoid heavy ML deps and mock every external dependency (LLM provider, httpx,
billing ledger, neuro bus) at the in-function import site.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.conversation.api import (
    LEGACY_BASE_PROMPT,
    ApiMixin,
    _coerce_int,
)
from app.services.conversation.context import ConversationContext


class _ConcreteApi(ApiMixin):
    """Minimal concrete impl mirroring the existing test harness."""

    def __init__(self):
        self._deepseek_async_client = None
        self._deepseek_async_loop = None
        self.api_key = "test-key"
        self.api_url = "https://api.example.com/v1/chat/completions"
        self.model = "test-model"
        self.confirmation_service = MagicMock()
        self.confirmation_service.get_pending_intent.return_value = None
        self.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }


# ---------------------------------------------------------------------------
# _coerce_int — except (TypeError, ValueError) branch (lines 40-41)
# ---------------------------------------------------------------------------
class TestCoerceIntExceptBranch:
    def test_unconvertible_object_returns_zero(self):
        # int(object()) raises TypeError -> caught -> 0
        assert _coerce_int(object()) == 0

    def test_non_numeric_string_returns_zero(self):
        # int("abc") raises ValueError -> caught -> 0
        assert _coerce_int("abc") == 0

    def test_list_returns_zero(self):
        # truthy list bypasses `value or 0`, int([..]) raises TypeError -> 0
        assert _coerce_int([1, 2, 3]) == 0

    def test_valid_numeric_string_passes_through(self):
        assert _coerce_int("42") == 42

    def test_none_uses_or_default(self):
        assert _coerce_int(None) == 0

    def test_float_truncates(self):
        assert _coerce_int(3.9) == 3


# ---------------------------------------------------------------------------
# _get_deepseek_async_client — loop cache create/reuse/recreate (85-102)
# ---------------------------------------------------------------------------
class TestGetDeepseekAsyncClient:
    @pytest.mark.asyncio
    async def test_creates_client_when_none(self):
        svc = _ConcreteApi()
        assert svc._deepseek_async_client is None

        client = await svc._get_deepseek_async_client()
        try:
            assert client is not None
            assert isinstance(client, httpx.AsyncClient)
            # loop is now cached
            assert svc._deepseek_async_loop is not None
            assert svc._deepseek_async_client is client
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_reuses_client_on_same_loop(self):
        svc = _ConcreteApi()
        first = await svc._get_deepseek_async_client()
        try:
            second = await svc._get_deepseek_async_client()
            # Same running loop -> same client object reused (no recreate)
            assert second is first
        finally:
            await first.aclose()

    @pytest.mark.asyncio
    async def test_recreates_and_closes_stale_client_on_loop_change(self):
        """When cached loop differs, the stale client is aclose()'d then replaced."""
        svc = _ConcreteApi()
        stale_client = AsyncMock()
        stale_client.aclose = AsyncMock()
        svc._deepseek_async_client = stale_client
        # Sentinel loop object that is NOT the running loop -> triggers recreate path
        svc._deepseek_async_loop = object()

        new_client = await svc._get_deepseek_async_client()
        try:
            stale_client.aclose.assert_awaited_once()
            assert new_client is not stale_client
            assert isinstance(new_client, httpx.AsyncClient)
        finally:
            await new_client.aclose()

    @pytest.mark.asyncio
    async def test_recreate_swallows_aclose_error(self):
        """Stale client's aclose raising a RECOVERABLE error is suppressed (94-96)."""
        svc = _ConcreteApi()
        stale_client = AsyncMock()
        stale_client.aclose = AsyncMock(side_effect=httpx.ConnectError("boom"))
        svc._deepseek_async_client = stale_client
        svc._deepseek_async_loop = object()

        new_client = await svc._get_deepseek_async_client()
        try:
            stale_client.aclose.assert_awaited_once()
            assert isinstance(new_client, httpx.AsyncClient)
            # despite the suppressed error, a fresh client is installed
            assert svc._deepseek_async_client is new_client
        finally:
            await new_client.aclose()


# ---------------------------------------------------------------------------
# call_llm_api — neuro_notify failure swallowed (line 211)
# ---------------------------------------------------------------------------
class TestCallLlmApiNeuroNotifyFailure:
    @pytest.mark.asyncio
    async def test_neuro_notify_failure_does_not_break_result(self):
        svc = _ConcreteApi()
        mock_provider = MagicMock()
        mock_provider.provider_id = "openai_compatible"
        mock_provider._adapter = SimpleNamespace(provider_name="b.ai", model_name="MiniMax-M3")
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "hi"}}],
                "model": "MiniMax-M3",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        )

        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider,
            ),
            patch("app.infrastructure.billing.model_usage.record_model_usage"),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip",
                side_effect=RuntimeError("neuro bus down"),
            ) as notify,
        ):
            result = await svc.call_llm_api([{"role": "user", "content": "hi"}])

        # neuro failure (RECOVERABLE) is swallowed; result still returns intact
        notify.assert_called_once()
        assert result is not None
        assert result["choices"][0]["message"]["content"] == "hi"
        assert result["_xcagi_trace"]["total_tokens"] == 3


# ---------------------------------------------------------------------------
# _call_deepseek_legacy — error/edge branches (285-309, 301-302)
# ---------------------------------------------------------------------------
def _legacy_response(json_payload):
    resp = MagicMock()
    resp.json.return_value = json_payload
    resp.raise_for_status = MagicMock()
    return resp


class TestCallDeepseekLegacyBranches:
    @pytest.mark.asyncio
    async def test_record_failure_does_not_break(self):
        """record_model_usage raising RECOVERABLE is swallowed (285-286)."""
        svc = _ConcreteApi()
        resp = _legacy_response(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(
                svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client
            ),
            patch(
                "app.infrastructure.billing.model_usage.record_model_usage",
                side_effect=RuntimeError("ledger down"),
            ),
            patch("app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"),
        ):
            result = await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])

        assert result is not None
        assert result["choices"][0]["message"]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_neuro_notify_failure_does_not_break(self):
        """neuro_notify_ai_model_roundtrip raising RECOVERABLE is swallowed (298-299)."""
        svc = _ConcreteApi()
        resp = _legacy_response(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(
                svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client
            ),
            patch("app.infrastructure.billing.model_usage.record_model_usage"),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip",
                side_effect=RuntimeError("neuro down"),
            ) as notify,
        ):
            result = await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])

        notify.assert_called_once()
        assert result is not None
        assert result["choices"][0]["message"]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_choices_key_returns_none(self):
        """No 'choices' key -> warning path -> returns None (301-302)."""
        svc = _ConcreteApi()
        resp = _legacy_response({"id": "x", "usage": {}})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)

        with patch.object(
            svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """httpx.HTTPError from client.post -> dedicated except -> None (304-306)."""
        svc = _ConcreteApi()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch.object(
            svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_recoverable_non_http_error_returns_none(self):
        """A RECOVERABLE non-HTTP error (ValueError from json) -> None (307-309)."""
        svc = _ConcreteApi()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        # .json() raising ValueError is a RECOVERABLE_ERROR but not httpx.HTTPError
        resp.json.side_effect = ValueError("malformed json")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)

        with patch.object(
            svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])
        assert result is None


# ---------------------------------------------------------------------------
# _execute_or_generate_response — pending-intent merge_slots branch (347)
# ---------------------------------------------------------------------------
class TestExecuteOrGenerateResponsePendingMerge:
    @pytest.mark.asyncio
    async def test_pending_intent_merges_slots(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = {"intent": "create_order"}
        merged = {"customer": "ACME", "qty": 5}
        svc.confirmation_service.merge_slots.return_value = merged
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }
        svc._check_habit_suggestion = MagicMock(return_value=None)

        ctx = ConversationContext(user_id="u1", metadata={})
        result = await svc._execute_or_generate_response(
            "继续",
            {"final_intent": "create_order", "slots": {"qty": 5}, "tool_key": "shipment_generate"},
            ctx,
            "u1",
        )

        # merge_slots was consulted because a pending intent existed
        svc.confirmation_service.merge_slots.assert_called_once_with("u1", {"qty": 5})
        # the merged slots flow into the tool-call response
        assert result["action"] == "tool_call"
        assert result["data"]["slots"] == merged


# ---------------------------------------------------------------------------
# _build_system_prompt_with_persona — fallback + persona path (458-464)
# ---------------------------------------------------------------------------
class TestBuildSystemPromptWithPersona:
    def test_fallback_without_persona_service_no_context(self):
        svc = _ConcreteApi()
        svc.persona_service = None
        out = svc._build_system_prompt_with_persona("u1", "hi", [], "通用", "")
        assert out == LEGACY_BASE_PROMPT

    def test_fallback_without_persona_service_with_context(self):
        svc = _ConcreteApi()
        # attribute entirely absent -> getattr(..., None) is falsy
        out = svc._build_system_prompt_with_persona("u1", "hi", [], "通用", "EXTRA-CTX")
        assert out.startswith(LEGACY_BASE_PROMPT)
        assert out.endswith("EXTRA-CTX")
        assert "\n\n" in out

    def test_uses_persona_service_build_prompt(self):
        svc = _ConcreteApi()
        persona = MagicMock()
        persona.build_prompt.return_value = "PERSONA-PROMPT"
        svc.persona_service = persona
        out = svc._build_system_prompt_with_persona("u1", "hi", [], "通用", "CTX")
        assert out == "PERSONA-PROMPT"
        persona.build_prompt.assert_called_once_with(None, "CTX")


# ---------------------------------------------------------------------------
# _call_ai — persona/history/mode-tag/provider selection (488-557)
# ---------------------------------------------------------------------------
def _make_call_ai_svc():
    svc = _ConcreteApi()
    svc.add_to_history = MagicMock()
    svc._metadata_cache_hash = MagicMock(return_value="hash")
    svc._build_context_prompt = MagicMock(return_value="CTX-PROMPT")
    return svc


class TestCallAiBranches:
    @pytest.mark.asyncio
    async def test_persona_path_builds_system_prompt_and_truncates_history(self):
        """persona_service present -> build_prompt_from_message; >10 history truncated."""
        svc = _make_call_ai_svc()
        persona = MagicMock()
        persona.build_prompt_from_message = AsyncMock(
            return_value=("SYSTEM-FROM-PERSONA", {"temp": 0.5})
        )
        svc.persona_service = persona

        history = [{"role": "user", "content": f"m{i}"} for i in range(15)]
        ctx = ConversationContext(
            user_id="u1",
            metadata={"request_context": {"industry": "制造"}},
            conversation_history=history,
        )

        captured = {}

        async def fake_llm(messages):
            captured["messages"] = messages
            return {
                "choices": [{"message": {"content": "AI reply"}}],
                "usage": {"total_tokens": 7},
                "_xcagi_trace": {
                    "provider_id": "openai_compatible",
                    "provider": "b.ai",
                    "model": "MiniMax-M3",
                    "total_tokens": 7,
                },
            }

        with (
            patch("app.services.conversation.api._ai_response_cache") as mock_cache,
            patch.object(svc, "call_llm_api", side_effect=fake_llm),
        ):
            mock_cache.get.return_value = None
            result = await svc._call_ai("你好", ctx, {"final_intent": "greeting"})

        # persona path was taken with the industry from request_context
        persona.build_prompt_from_message.assert_awaited_once()
        kwargs = persona.build_prompt_from_message.call_args.kwargs
        assert kwargs["industry"] == "制造"
        assert kwargs["context_prompt"] == "CTX-PROMPT"

        msgs = captured["messages"]
        assert msgs[0] == {"role": "system", "content": "SYSTEM-FROM-PERSONA"}
        # only last 10 of history + final user message
        assert msgs[-1] == {"role": "user", "content": "你好"}
        history_msgs = msgs[1:-1]
        assert len(history_msgs) == 10
        assert history_msgs[0]["content"] == "m5"

        # trace present -> model/provider come from trace
        assert result["action"] == "ai_response"
        assert result["data"]["model"] == "MiniMax-M3"
        assert result["data"]["provider"] == "b.ai"
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_modstore_mode_tag_and_provider_when_no_trace(self):
        """modstore_adapter present + empty trace -> modstore model/provider (508-510, 547-549)."""
        svc = _make_call_ai_svc()
        svc.persona_service = None
        svc.modstore_adapter = SimpleNamespace(
            default_provider="b.ai",
            default_model="MiniMax-M3",
            user_id="user-42",
        )

        with (
            patch("app.services.conversation.api._ai_response_cache") as mock_cache,
            patch.object(
                svc,
                "call_llm_api",
                new_callable=AsyncMock,
                return_value={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 0},
                    # no _xcagi_trace -> falls into modstore branch
                },
            ),
        ):
            mock_cache.get.return_value = None
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._call_ai("hi", ctx, {"final_intent": "greeting"})

        assert result["action"] == "ai_response"
        assert result["data"]["model"] == "modstore:MiniMax-M3"
        assert result["data"]["provider"] == "modstore-platform"
        assert result["data"]["llm_trace"] == {}

    @pytest.mark.asyncio
    async def test_llm_adapter_mode_tag_and_provider_when_no_trace(self):
        """llm_adapter configured + empty trace -> adapter model/provider (514-516, 550-554)."""
        svc = _make_call_ai_svc()
        svc.persona_service = None
        # ensure modstore branch is skipped
        svc.modstore_adapter = None
        svc.llm_adapter = SimpleNamespace(
            is_configured=True,
            provider_name="qwen",
            model_name="qwen-max",
        )

        with (
            patch("app.services.conversation.api._ai_response_cache") as mock_cache,
            patch.object(
                svc,
                "call_llm_api",
                new_callable=AsyncMock,
                return_value={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 0},
                },
            ),
        ):
            mock_cache.get.return_value = None
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._call_ai("hi", ctx, {"final_intent": "greeting"})

        assert result["data"]["model"] == "qwen-max"
        assert result["data"]["provider"] == "qwen"

    @pytest.mark.asyncio
    async def test_deepseek_legacy_mode_tag_and_provider_when_no_trace(self):
        """No modstore, no configured llm_adapter -> deepseek-legacy fallback (518-519, 556-557)."""
        svc = _make_call_ai_svc()
        svc.persona_service = None
        svc.modstore_adapter = None
        svc.llm_adapter = None
        svc.model = "deepseek-chat"

        with (
            patch("app.services.conversation.api._ai_response_cache") as mock_cache,
            patch.object(
                svc,
                "call_llm_api",
                new_callable=AsyncMock,
                return_value={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 0},
                },
            ),
        ):
            mock_cache.get.return_value = None
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._call_ai("hi", ctx, {"final_intent": "greeting"})

        assert result["data"]["model"] == "deepseek-chat"
        assert result["data"]["provider"] == "deepseek-legacy"
