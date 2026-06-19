"""Tests for app.services.conversation.api (ApiMixin)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.api import (
    ApiMixin,
    _make_ai_response_cache_key,
)
from app.services.conversation.context import ConversationContext


# ---------------------------------------------------------------------------
# Helper: concrete subclass since ApiMixin is abstract-ish
# ---------------------------------------------------------------------------
class _ConcreteApi(ApiMixin):
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
# _make_ai_response_cache_key
# ---------------------------------------------------------------------------
class TestMakeAiResponseCacheKey:
    def test_deterministic_key(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx1")
        assert key1 == key2

    def test_different_messages_different_keys(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("world", "ctx1")
        assert key1 != key2

    def test_different_contexts_different_keys(self):
        key1 = _make_ai_response_cache_key("hello", "ctx1")
        key2 = _make_ai_response_cache_key("hello", "ctx2")
        assert key1 != key2

    def test_case_insensitive(self):
        key1 = _make_ai_response_cache_key("Hello", "")
        key2 = _make_ai_response_cache_key("hello", "")
        assert key1 == key2

    def test_whitespace_stripped(self):
        key1 = _make_ai_response_cache_key("  hello  ", "")
        key2 = _make_ai_response_cache_key("hello", "")
        assert key1 == key2


# ---------------------------------------------------------------------------
# _call_ai_offline
# ---------------------------------------------------------------------------
class TestCallAiOffline:
    @pytest.mark.asyncio
    async def test_with_known_intent(self):
        svc = _ConcreteApi()
        svc.add_to_history = MagicMock()
        ctx = ConversationContext(user_id="u1", metadata={})

        result = await svc._call_ai_offline(
            "hello", ctx, {"final_intent": "create_order"}
        )
        assert result["action"] == "offline_response"
        assert "create_order" in result["text"]

    @pytest.mark.asyncio
    async def test_with_unknown_intent(self):
        svc = _ConcreteApi()
        svc.add_to_history = MagicMock()
        ctx = ConversationContext(user_id="u1", metadata={})

        result = await svc._call_ai_offline(
            "hello", ctx, {"final_intent": "unk"}
        )
        assert result["action"] == "offline_response"
        assert "离线模式" in result["text"]

    @pytest.mark.asyncio
    async def test_with_primary_intent_fallback(self):
        svc = _ConcreteApi()
        svc.add_to_history = MagicMock()
        ctx = ConversationContext(user_id="u1", metadata={})

        result = await svc._call_ai_offline(
            "hello", ctx, {"primary_intent": "query_products"}
        )
        assert result["action"] == "offline_response"
        assert "query_products" in result["text"]


# ---------------------------------------------------------------------------
# _maybe_attach_kitten_web
# ---------------------------------------------------------------------------
class TestMaybeAttachKittenWeb:
    def test_no_kitten_analyzer_returns_unchanged(self):
        svc = _ConcreteApi()
        ctx = ConversationContext(
            user_id="u1",
            metadata={"request_context": {}},
        )
        result = {"text": "hello", "data": {}}
        out = svc._maybe_attach_kitten_web(ctx, result)
        assert "web_search_results" not in out.get("data", {})

    def test_attaches_web_search_results(self):
        svc = _ConcreteApi()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [{"title": "test"}],
                    "web_search_meta": {"count": 1},
                    "web_search_error": None,
                }
            },
        )
        result = {"text": "hello", "data": {}}
        out = svc._maybe_attach_kitten_web(ctx, result)
        assert out["data"]["web_search_results"] == [{"title": "test"}]
        assert out["data"]["web_search_meta"] == {"count": 1}

    def test_attaches_web_search_error(self):
        svc = _ConcreteApi()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [],
                    "web_search_error": "timeout",
                }
            },
        )
        result = {"text": "hello", "data": {}}
        out = svc._maybe_attach_kitten_web(ctx, result)
        assert out["data"]["web_search_error"] == "timeout"

    def test_creates_data_dict_if_missing(self):
        svc = _ConcreteApi()
        ctx = ConversationContext(
            user_id="u1",
            metadata={
                "request_context": {
                    "kitten_analyzer": True,
                    "kitten_web_search": True,
                    "web_search_results": [{"title": "test"}],
                }
            },
        )
        result = {"text": "hello"}
        out = svc._maybe_attach_kitten_web(ctx, result)
        assert "data" in out
        assert out["data"]["web_search_results"] == [{"title": "test"}]


# ---------------------------------------------------------------------------
# _execute_or_generate_response
# ---------------------------------------------------------------------------
class TestExecuteOrGenerateResponse:
    @pytest.mark.asyncio
    async def test_missing_slots_returns_slot_fill(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = None
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "missing_slots",
            "question": "请提供客户名称",
            "missing_slots": ["customer_name"],
            "pending_data": {"intent": "create_order"},
        }

        ctx = ConversationContext(user_id="u1", metadata={})
        result = await svc._execute_or_generate_response(
            "下单", {"final_intent": "create_order", "slots": {}}, ctx, "u1"
        )
        assert result["action"] == "slot_fill"
        assert "missing_slots" in result["data"]

    @pytest.mark.asyncio
    async def test_tool_key_returns_tool_call(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = None
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }
        svc._check_habit_suggestion = MagicMock(return_value=None)

        ctx = ConversationContext(user_id="u1", metadata={})
        result = await svc._execute_or_generate_response(
            "查询产品",
            {"final_intent": "query_products", "slots": {}, "tool_key": "products"},
            ctx,
            "u1",
        )
        assert result["action"] == "tool_call"
        assert result["data"]["tool_key"] == "products"

    @pytest.mark.asyncio
    async def test_offline_mode_calls_offline(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = None
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }
        svc.add_to_history = MagicMock()

        ctx = ConversationContext(user_id="u1", metadata={})
        result = await svc._execute_or_generate_response(
            "你好",
            {"final_intent": "greeting", "slots": {}, "ai_mode": "offline"},
            ctx,
            "u1",
        )
        assert result["action"] == "offline_response"

    @pytest.mark.asyncio
    async def test_online_mode_calls_ai(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = None
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }
        svc.add_to_history = MagicMock()
        svc._metadata_cache_hash = MagicMock(return_value="hash")
        svc._build_context_prompt = MagicMock(return_value="")

        with patch.object(svc, "call_llm_api", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "choices": [{"message": {"content": "AI reply"}}],
                "usage": {"total_tokens": 10},
                "_xcagi_trace": {
                    "provider_id": "openai_compatible",
                    "provider": "xcauto",
                    "model": "xcauto-account",
                    "total_tokens": 10,
                    "latency_ms": 12.0,
                },
            }
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._execute_or_generate_response(
                "你好",
                {"final_intent": "greeting", "slots": {}},
                ctx,
                "u1",
            )
        assert result["action"] == "ai_response"
        assert result["text"] == "AI reply"
        assert result["data"]["provider"] == "xcauto"
        assert result["data"]["model"] == "xcauto-account"
        assert result["data"]["llm_trace"]["provider_id"] == "openai_compatible"

    @pytest.mark.asyncio
    async def test_online_mode_fallback_on_empty_response(self):
        svc = _ConcreteApi()
        svc.confirmation_service.get_pending_intent.return_value = None
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "ok",
            "missing_slots": [],
        }
        svc.add_to_history = MagicMock()
        svc._metadata_cache_hash = MagicMock(return_value="hash")
        svc._build_context_prompt = MagicMock(return_value="")

        with (
            patch(
                "app.services.conversation.api._ai_response_cache"
            ) as mock_cache,
            patch.object(svc, "call_llm_api", new_callable=AsyncMock, return_value={"choices": []}),
        ):
            mock_cache.get.return_value = None
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._execute_or_generate_response(
                "你好",
                {"final_intent": "greeting", "slots": {}},
                ctx,
                "u1",
            )
        assert result["action"] == "fallback"


# ---------------------------------------------------------------------------
# _build_tool_call_response
# ---------------------------------------------------------------------------
class TestBuildToolCallResponse:
    def test_known_tool_key(self):
        svc = _ConcreteApi()
        svc._check_habit_suggestion = MagicMock(return_value=None)
        result = svc._build_tool_call_response(
            "products",
            {"unit_name": "TestCo"},
            {"final_intent": "query_products"},
            "u1",
            {"status": "ok", "missing_slots": []},
        )
        assert result["action"] == "tool_call"
        assert "查询" in result["text"]

    def test_unknown_tool_key(self):
        svc = _ConcreteApi()
        svc._check_habit_suggestion = MagicMock(return_value=None)
        result = svc._build_tool_call_response(
            "custom_tool",
            {},
            {"final_intent": "custom"},
            "u1",
            {"status": "ok", "missing_slots": []},
        )
        assert result["action"] == "tool_call"
        assert "custom_tool" in result["text"]

    def test_habit_suggestion_appended(self):
        svc = _ConcreteApi()
        svc._check_habit_suggestion = MagicMock(return_value="建议：上次您查询了产品A")
        result = svc._build_tool_call_response(
            "products",
            {},
            {"final_intent": "query_products"},
            "u1",
            {"status": "ok", "missing_slots": []},
        )
        assert "建议" in result["text"]


# ---------------------------------------------------------------------------
# call_llm_api
# ---------------------------------------------------------------------------
class TestCallLlmApi:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_provider(self):
        svc = _ConcreteApi()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=None,
        ):
            result = await svc.call_llm_api([{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_result_from_provider(self):
        svc = _ConcreteApi()
        mock_provider = MagicMock()
        mock_provider.provider_id = "openai_compatible"
        mock_provider._adapter = SimpleNamespace(provider_name="xcauto", model_name="xcauto-account")
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "hi"}}],
                "model": "xcauto-account",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        )

        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider,
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"
            ) as notify,
        ):
            result = await svc.call_llm_api([{"role": "user", "content": "hi"}])
        assert result is not None
        assert result["choices"][0]["message"]["content"] == "hi"
        assert result["_xcagi_trace"]["provider_id"] == "openai_compatible"
        assert result["_xcagi_trace"]["provider"] == "xcauto"
        assert result["_xcagi_trace"]["model"] == "xcauto-account"
        assert result["_xcagi_trace"]["total_tokens"] == 5
        assert svc._last_llm_trace == result["_xcagi_trace"]
        notify.assert_called_once()
        assert notify.call_args.kwargs["model"] == "xcauto-account"
        assert notify.call_args.kwargs["token_count"] == 5

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        svc = _ConcreteApi()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            side_effect=RuntimeError("provider error"),
        ):
            result = await svc.call_llm_api([{"role": "user", "content": "hi"}])
        assert result is None


# ---------------------------------------------------------------------------
# _call_deepseek_legacy
# ---------------------------------------------------------------------------
class TestCallDeepseekLegacy:
    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self):
        svc = _ConcreteApi()
        svc.api_key = ""
        result = await svc._call_deepseek_legacy(
            [{"role": "user", "content": "hi"}]
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        svc = _ConcreteApi()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch.object(svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client):
            result = await svc._call_deepseek_legacy(
                [{"role": "user", "content": "hi"}]
            )
        assert result is not None
        assert result["choices"][0]["message"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_choices(self):
        svc = _ConcreteApi()
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch.object(svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client):
            result = await svc._call_deepseek_legacy(
                [{"role": "user", "content": "hi"}]
            )
        assert result is None


# ---------------------------------------------------------------------------
# token 用量持久化到本地账本（record_model_usage）
# ---------------------------------------------------------------------------
class TestTokenUsagePersisted:
    """验证 call_llm_api 和 _call_deepseek_legacy 会把 token 用量写入账本。"""

    @pytest.mark.asyncio
    async def test_call_llm_api_persists_token_usage(self):
        """call_llm_api 调用后 record_model_usage 被调用，参数含真实 token。"""
        svc = _ConcreteApi()
        mock_provider = MagicMock()
        mock_provider.provider_id = "openai_compatible"
        mock_provider._adapter = SimpleNamespace(provider_name="b.ai", model_name="MiniMax-M3")
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "hi"}}],
                "model": "MiniMax-M3",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        )

        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider,
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"
            ),
            patch(
                "app.infrastructure.billing.model_usage.record_model_usage"
            ) as mock_record,
        ):
            await svc.call_llm_api([{"role": "user", "content": "hi"}])

        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["prompt_tokens"] == 10
        assert kwargs["completion_tokens"] == 20
        assert kwargs["total_tokens"] == 30
        assert kwargs["model"] == "MiniMax-M3"
        assert kwargs["provider"] == "b.ai"
        assert kwargs["source"] == "conversation_service"

    @pytest.mark.asyncio
    async def test_call_llm_api_record_failure_does_not_break(self):
        """record_model_usage 抛异常不影响主流程。"""
        svc = _ConcreteApi()
        mock_provider = MagicMock()
        mock_provider.provider_id = "openai_compatible"
        mock_provider._adapter = SimpleNamespace(provider_name="b.ai", model_name="MiniMax-M3")
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "hi"}}],
                "model": "MiniMax-M3",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }
        )

        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider,
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"
            ),
            patch(
                "app.infrastructure.billing.model_usage.record_model_usage",
                side_effect=RuntimeError("ledger write failed"),
            ),
        ):
            result = await svc.call_llm_api([{"role": "user", "content": "hi"}])

        # 主流程不受影响，result 正常返回
        assert result is not None
        assert result["choices"][0]["message"]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_deepseek_legacy_persists_token_usage(self):
        """_call_deepseek_legacy 调用后 record_model_usage 被调用，参数含真实 token。"""
        svc = _ConcreteApi()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with (
            patch.object(svc, "_get_deepseek_async_client", new_callable=AsyncMock, return_value=mock_client),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"
            ),
            patch(
                "app.infrastructure.billing.model_usage.record_model_usage"
            ) as mock_record,
        ):
            await svc._call_deepseek_legacy([{"role": "user", "content": "hi"}])

        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["prompt_tokens"] == 8
        assert kwargs["completion_tokens"] == 12
        assert kwargs["total_tokens"] == 20
        assert kwargs["provider"] == "deepseek"
        assert kwargs["source"] == "conversation_service.deepseek_legacy"

    @pytest.mark.asyncio
    async def test_end_to_end_token_usage_queryable(self, tmp_path, monkeypatch):
        """端到端：call_llm_api 写入账本 → query_local_token_usage 能查到。"""
        # 用临时账本路径，避免污染真实账本
        ledger = tmp_path / "test_ledger.json"
        monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger))

        svc = _ConcreteApi()
        mock_provider = MagicMock()
        mock_provider.provider_id = "openai_compatible"
        mock_provider._adapter = SimpleNamespace(provider_name="b.ai", model_name="MiniMax-M3")
        mock_provider.chat_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "hi"}}],
                "model": "MiniMax-M3",
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            }
        )

        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider,
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_ai_model_roundtrip"
            ),
        ):
            await svc.call_llm_api([{"role": "user", "content": "hi"}])

        # 用 query_local_token_usage 查询（直接 await，已在 event loop 中）
        from app.mod_sdk.employee_specialized_tools import TOOL_REGISTRY

        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = await fn({}, {})

        assert result["ok"] is True
        assert result["usage_summary"]["total_tokens"] == 300
        assert result["usage_summary"]["prompt_tokens"] == 100
        assert result["usage_summary"]["completion_tokens"] == 200
        assert result["usage_summary"]["total_calls"] == 1
        # 按 model 分组应有 MiniMax-M3
        assert "MiniMax-M3" in result["groups"]
        assert result["groups"]["MiniMax-M3"]["total_tokens"] == 300


# ---------------------------------------------------------------------------
# _call_ai (cached + LLM integration)
# ---------------------------------------------------------------------------
class TestCallAi:
    @pytest.mark.asyncio
    async def test_returns_cached_response(self):
        svc = _ConcreteApi()
        svc.add_to_history = MagicMock()
        svc._metadata_cache_hash = MagicMock(return_value="hash")
        svc.model = "test-model"

        with patch(
            "app.services.conversation.api._ai_response_cache"
        ) as mock_cache:
            mock_cache.get.return_value = "cached reply"
            ctx = ConversationContext(user_id="u1", metadata={})
            result = await svc._call_ai("hello", ctx, {"final_intent": "greeting"})
        assert result["action"] == "ai_response"
        assert result["text"] == "cached reply"
        assert result["data"]["cached"] is True

    @pytest.mark.asyncio
    async def test_returns_fallback_on_no_choices(self):
        svc = _ConcreteApi()
        svc.add_to_history = MagicMock()
        svc._metadata_cache_hash = MagicMock(return_value="hash")
        svc._build_context_prompt = MagicMock(return_value="")
        svc.model = "test-model"

        with (
            patch(
                "app.services.conversation.api._ai_response_cache"
            ) as mock_cache,
            patch.object(svc, "call_llm_api", new_callable=AsyncMock, return_value=None),
        ):
            mock_cache.get.return_value = None
            ctx = ConversationContext(user_id="u1", metadata={}, conversation_history=[])
            result = await svc._call_ai("hello", ctx, {"final_intent": "greeting"})
        assert result["action"] == "fallback"
