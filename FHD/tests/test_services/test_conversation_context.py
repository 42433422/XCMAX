"""Tests for app.services.conversation.context — ContextMixin & ConversationContext."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.context import ContextMixin, ConversationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyHost(ContextMixin):
    """Minimal class that provides the `contexts` dict required by ContextMixin."""

    def __init__(self):
        self.contexts: dict[str, ConversationContext] = {}

    # Stubs for sanitizers called inside _apply_request_context
    def _sanitize_kitten_dataset(self, ds):
        return ds

    def _sanitize_kitten_business_snapshot(self, snap):
        return snap

    def _sanitize_web_search_results(self, results):
        return results


@pytest.fixture
def host():
    return _DummyHost()


# ---------------------------------------------------------------------------
# ConversationContext dataclass
# ---------------------------------------------------------------------------


class TestConversationContext:
    def test_default_fields(self):
        ctx = ConversationContext(user_id="u1")
        assert ctx.user_id == "u1"
        assert ctx.conversation_history == []
        assert ctx.current_file is None
        assert ctx.last_action is None
        assert ctx.metadata == {}
        assert ctx.current_intent is None
        assert ctx.current_tool_key is None
        assert ctx.intent_hints == []
        assert ctx.pending_confirmation is None
        assert ctx.last_intent_result is None
        assert isinstance(ctx.created_at, float)
        assert isinstance(ctx.updated_at, float)

    def test_custom_fields(self):
        ctx = ConversationContext(
            user_id="u2",
            conversation_history=[{"role": "user", "content": "hi"}],
            current_file="test.xlsx",
            last_action="query",
            metadata={"key": "val"},
            current_intent="greet",
            current_tool_key="chat",
            intent_hints=["hint1"],
            pending_confirmation={"action": "delete"},
            last_intent_result={"final_intent": "greet"},
        )
        assert ctx.conversation_history == [{"role": "user", "content": "hi"}]
        assert ctx.current_file == "test.xlsx"
        assert ctx.current_intent == "greet"
        assert ctx.pending_confirmation == {"action": "delete"}


# ---------------------------------------------------------------------------
# ContextMixin — basic CRUD
# ---------------------------------------------------------------------------


class TestContextMixinGetCreate:
    def test_get_context_nonexistent(self, host):
        assert host.get_context("nobody") is None

    def test_create_context(self, host):
        ctx = host.create_context("u1")
        assert isinstance(ctx, ConversationContext)
        assert ctx.user_id == "u1"
        assert "u1" in host.contexts

    def test_get_context_after_create(self, host):
        host.create_context("u1")
        ctx = host.get_context("u1")
        assert ctx is not None
        assert ctx.user_id == "u1"

    def test_create_context_twice_overwrites(self, host):
        first = host.create_context("u1")
        first.current_intent = "old"
        second = host.create_context("u1")
        assert second.current_intent is None


class TestContextMixinUpdate:
    def test_update_existing_context(self, host):
        host.create_context("u1")
        result = host.update_context("u1", current_intent="greet", current_file="a.xlsx")
        assert result is not None
        assert result.current_intent == "greet"
        assert result.current_file == "a.xlsx"
        assert result.updated_at > 0

    def test_update_nonexistent_returns_none(self, host):
        result = host.update_context("nobody", current_intent="x")
        assert result is None

    def test_update_ignores_invalid_attrs(self, host):
        host.create_context("u1")
        result = host.update_context("u1", nonexistent_attr="val")
        assert result is not None
        assert not hasattr(result, "nonexistent_attr")


class TestContextMixinSetPendingConfirmation:
    def test_set_pending_existing_context(self, host):
        host.create_context("u1")
        ok = host.set_pending_confirmation("u1", {"action": "delete", "target": "file.xlsx"})
        assert ok is True
        ctx = host.get_context("u1")
        assert ctx.pending_confirmation == {"action": "delete", "target": "file.xlsx"}

    def test_set_pending_creates_context_if_missing(self, host):
        assert "u1" not in host.contexts
        ok = host.set_pending_confirmation("u1", {"action": "confirm"})
        assert ok is True
        assert "u1" in host.contexts
        ctx = host.get_context("u1")
        assert ctx.pending_confirmation == {"action": "confirm"}


class TestContextMixinClear:
    def test_clear_existing(self, host):
        host.create_context("u1")
        assert host.clear_context("u1") is True
        assert "u1" not in host.contexts

    def test_clear_nonexistent(self, host):
        assert host.clear_context("nobody") is False


class TestContextMixinGetAll:
    def test_get_all_empty(self, host):
        assert host.get_all_contexts() == {}

    def test_get_all_returns_copy(self, host):
        host.create_context("u1")
        host.create_context("u2")
        all_ctx = host.get_all_contexts()
        assert len(all_ctx) == 2
        # Mutating the copy should not affect the original
        all_ctx["u3"] = ConversationContext(user_id="u3")
        assert "u3" not in host.contexts


class TestContextMixinCleanup:
    def test_cleanup_removes_old(self, host):
        ctx = host.create_context("u1")
        ctx.updated_at = time.time() - 7200  # 2 hours ago
        removed = host.cleanup_old_contexts(max_age_seconds=3600)
        assert removed == 1
        assert "u1" not in host.contexts

    def test_cleanup_keeps_recent(self, host):
        host.create_context("u1")
        removed = host.cleanup_old_contexts(max_age_seconds=3600)
        assert removed == 0
        assert "u1" in host.contexts

    def test_cleanup_mixed(self, host):
        old = host.create_context("old")
        old.updated_at = time.time() - 7200
        host.create_context("recent")
        removed = host.cleanup_old_contexts(max_age_seconds=3600)
        assert removed == 1
        assert "old" not in host.contexts
        assert "recent" in host.contexts


# ---------------------------------------------------------------------------
# _get_or_create_context
# ---------------------------------------------------------------------------


class TestGetOrCreateContext:
    def test_creates_if_missing(self, host):
        ctx = host._get_or_create_context("u1", None)
        assert isinstance(ctx, ConversationContext)
        assert ctx.user_id == "u1"

    def test_reuses_existing(self, host):
        existing = host.create_context("u1")
        existing.current_intent = "old"
        ctx = host._get_or_create_context("u1", None)
        assert ctx.current_intent == "old"

    def test_applies_request_context(self, host):
        ctx = host._get_or_create_context("u1", {"kitten_analyzer": True, "has_dataset": True})
        assert "request_context" in ctx.metadata


# ---------------------------------------------------------------------------
# _get_or_create_context_async
# ---------------------------------------------------------------------------


class TestGetOrCreateContextAsync:
    @pytest.mark.asyncio
    async def test_creates_if_missing(self, host):
        ctx = await host._get_or_create_context_async("u1", None, "hello")
        assert isinstance(ctx, ConversationContext)
        assert ctx.user_id == "u1"

    @pytest.mark.asyncio
    async def test_reuses_existing(self, host):
        existing = host.create_context("u1")
        existing.current_intent = "old"
        ctx = await host._get_or_create_context_async("u1", None, "hello")
        assert ctx.current_intent == "old"

    @pytest.mark.asyncio
    async def test_enriches_with_web_search(self, host):
        ctx_input = {"kitten_analyzer": True, "kitten_web_search": True}
        with patch(
            "app.services.conversation.context.kitten_web_search",
            new_callable=AsyncMock,
            create=True,
        ) as mock_ws:
            # The import inside the method will try to import from app.infrastructure.web_search
            # We need to patch at the module level
            with patch.dict(
                "sys.modules",
                {
                    "app.infrastructure.web_search": MagicMock(
                        kitten_web_search=AsyncMock(
                            return_value={
                                "success": True,
                                "hits": [{"title": "t"}],
                                "provider": "p",
                                "query": "q",
                            }
                        )
                    )
                },
            ):
                ctx = await host._get_or_create_context_async("u1", ctx_input, "search query")
                assert isinstance(ctx, ConversationContext)


# ---------------------------------------------------------------------------
# _update_context_from_intent
# ---------------------------------------------------------------------------


class TestUpdateContextFromIntent:
    def test_updates_intent_fields(self, host):
        ctx = host.create_context("u1")
        intent_result = {
            "final_intent": "shipment_generate",
            "tool_key": "shipment_records",
            "intent_hints": ["hint_a"],
        }
        host._update_context_from_intent(ctx, intent_result)
        assert ctx.current_intent == "shipment_generate"
        assert ctx.current_tool_key == "shipment_records"
        assert ctx.intent_hints == ["hint_a"]
        assert ctx.last_intent_result == intent_result

    def test_falls_back_to_primary_intent(self, host):
        ctx = host.create_context("u1")
        intent_result = {"primary_intent": "greet", "tool_key": None, "intent_hints": []}
        host._update_context_from_intent(ctx, intent_result)
        assert ctx.current_intent == "greet"


# ---------------------------------------------------------------------------
# _enrich_context_with_kitten_business_snapshot
# ---------------------------------------------------------------------------


class TestEnrichContextWithKittenBusinessSnapshot:
    def test_non_dict_returns_as_is(self, host):
        assert host._enrich_context_with_kitten_business_snapshot(None) is None
        assert host._enrich_context_with_kitten_business_snapshot("string") == "string"

    def test_no_kitten_analyzer_returns_unchanged(self, host):
        ctx = {"other_key": "val"}
        result = host._enrich_context_with_kitten_business_snapshot(ctx)
        assert result == {"other_key": "val"}

    def test_with_kitten_analyzer_no_business_db(self, host):
        ctx = {"kitten_analyzer": True}
        result = host._enrich_context_with_kitten_business_snapshot(ctx)
        assert "kitten_business_snapshot" not in result

    def test_with_kitten_include_business_db_success(self, host):
        ctx = {"kitten_analyzer": True, "kitten_include_business_db": True}
        with patch.dict(
            "sys.modules",
            {
                "app.services.kitten_business_snapshot": MagicMock(
                    build_kitten_business_snapshot=MagicMock(return_value={"stats": {"orders": 10}})
                )
            },
        ):
            result = host._enrich_context_with_kitten_business_snapshot(ctx)
            assert result["kitten_business_snapshot"] == {"stats": {"orders": 10}}

    def test_with_kitten_include_business_db_failure(self, host):
        ctx = {"kitten_analyzer": True, "kitten_include_business_db": True}
        with patch.dict(
            "sys.modules",
            {
                "app.services.kitten_business_snapshot": MagicMock(
                    build_kitten_business_snapshot=MagicMock(side_effect=RuntimeError("db down"))
                )
            },
        ):
            result = host._enrich_context_with_kitten_business_snapshot(ctx)
            assert result["kitten_business_snapshot"]["success"] is False
            assert "db down" in result["kitten_business_snapshot"]["text"]


# ---------------------------------------------------------------------------
# _enrich_kitten_web_search_if_needed
# ---------------------------------------------------------------------------


class TestEnrichKittenWebSearchIfNeeded:
    @pytest.mark.asyncio
    async def test_non_dict_returns_as_is(self, host):
        assert await host._enrich_kitten_web_search_if_needed(None, "msg", "u1") is None
        assert await host._enrich_kitten_web_search_if_needed("string", "msg", "u1") == "string"

    @pytest.mark.asyncio
    async def test_no_kitten_analyzer_returns_unchanged(self, host):
        ctx = {"kitten_web_search": True}
        result = await host._enrich_kitten_web_search_if_needed(ctx, "msg", "u1")
        assert result == {"kitten_web_search": True}

    @pytest.mark.asyncio
    async def test_no_kitten_web_search_returns_unchanged(self, host):
        ctx = {"kitten_analyzer": True}
        result = await host._enrich_kitten_web_search_if_needed(ctx, "msg", "u1")
        assert result == {"kitten_analyzer": True}

    @pytest.mark.asyncio
    async def test_search_success(self, host):
        ctx = {"kitten_analyzer": True, "kitten_web_search": True}
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.web_search": MagicMock(
                    kitten_web_search=AsyncMock(
                        return_value={
                            "success": True,
                            "hits": [{"title": "result"}],
                            "provider": "p",
                            "query": "q",
                        }
                    )
                )
            },
        ):
            result = await host._enrich_kitten_web_search_if_needed(ctx, "search", "u1")
            assert result["web_search_results"] == [{"title": "result"}]
            assert "web_search_error" not in result
            assert result["web_search_meta"]["provider"] == "p"

    @pytest.mark.asyncio
    async def test_search_failure(self, host):
        ctx = {"kitten_analyzer": True, "kitten_web_search": True}
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.web_search": MagicMock(
                    kitten_web_search=AsyncMock(
                        return_value={
                            "success": False,
                            "message": "timeout",
                            "provider": None,
                            "query": "q",
                        }
                    )
                )
            },
        ):
            result = await host._enrich_kitten_web_search_if_needed(ctx, "search", "u1")
            assert result["web_search_results"] == []
            assert "web_search_error" in result

    @pytest.mark.asyncio
    async def test_search_exception(self, host):
        ctx = {"kitten_analyzer": True, "kitten_web_search": True}
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.web_search": MagicMock(
                    kitten_web_search=AsyncMock(side_effect=ConnectionError("network"))
                )
            },
        ):
            result = await host._enrich_kitten_web_search_if_needed(ctx, "search", "u1")
            assert result["web_search_results"] == []
            assert "network" in result.get("web_search_error", "")


# ---------------------------------------------------------------------------
# _apply_request_context
# ---------------------------------------------------------------------------


class TestApplyRequestContext:
    def test_none_context_noop(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(ctx, None)
        assert ctx.metadata == {}

    def test_empty_context_noop(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(ctx, {})
        assert ctx.metadata == {}

    def test_merges_into_request_context(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(ctx, {"key1": "val1"})
        assert ctx.metadata["request_context"]["key1"] == "val1"

    def test_merges_with_previous(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(ctx, {"key1": "val1"})
        host._apply_request_context(ctx, {"key2": "val2"})
        rc = ctx.metadata["request_context"]
        assert rc["key1"] == "val1"
        assert rc["key2"] == "val2"

    def test_kitten_analyzer_has_dataset_false_removes_dataset(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx, {"kitten_analyzer": True, "has_dataset": False, "kitten_dataset": {"rows": 5}}
        )
        rc = ctx.metadata["request_context"]
        assert "kitten_dataset" not in rc

    def test_kitten_dataset_present_and_truthy(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx, {"kitten_analyzer": True, "has_dataset": True, "kitten_dataset": {"rows": 5}}
        )
        rc = ctx.metadata["request_context"]
        assert rc["kitten_dataset"] == {"rows": 5}

    def test_kitten_dataset_empty_removed(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(ctx, {"kitten_analyzer": True, "kitten_dataset": ""})
        rc = ctx.metadata["request_context"]
        assert "kitten_dataset" not in rc

    def test_kitten_no_web_search_cleans_web_keys(self, host):
        ctx = host.create_context("u1")
        # First set web search results
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
                "web_search_results": [{"t": "r"}],
                "web_search_meta": {"provider": "p"},
            },
        )
        # Then apply without web search
        host._apply_request_context(ctx, {"kitten_analyzer": True, "kitten_web_search": False})
        rc = ctx.metadata["request_context"]
        assert "web_search_results" not in rc
        assert "web_search_error" not in rc
        assert "web_search_meta" not in rc

    def test_web_search_error_truncated(self, host):
        ctx = host.create_context("u1")
        long_err = "x" * 600
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
                "web_search_error": long_err,
            },
        )
        rc = ctx.metadata["request_context"]
        assert len(rc["web_search_error"]) <= 500

    def test_web_search_error_cleared_on_no_error(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
                "web_search_error": "some error",
            },
        )
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
            },
        )
        rc = ctx.metadata["request_context"]
        assert "web_search_error" not in rc

    def test_web_search_meta_dict(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
                "web_search_meta": {"provider": "p", "query": "q"},
            },
        )
        rc = ctx.metadata["request_context"]
        assert rc["web_search_meta"]["provider"] == "p"

    def test_web_search_meta_non_dict_removed(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_web_search": True,
                "web_search_meta": "not a dict",
            },
        )
        rc = ctx.metadata["request_context"]
        assert "web_search_meta" not in rc

    def test_kitten_business_snapshot_with_include(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_include_business_db": True,
                "kitten_business_snapshot": {"stats": {"orders": 5}},
            },
        )
        rc = ctx.metadata["request_context"]
        assert rc["kitten_business_snapshot"] == {"stats": {"orders": 5}}

    def test_kitten_business_snapshot_without_include_removed(self, host):
        ctx = host.create_context("u1")
        host._apply_request_context(
            ctx,
            {
                "kitten_analyzer": True,
                "kitten_include_business_db": False,
                "kitten_business_snapshot": {"stats": {}},
            },
        )
        rc = ctx.metadata["request_context"]
        assert "kitten_business_snapshot" not in rc

    def test_updated_at_refreshed(self, host):
        ctx = host.create_context("u1")
        old_updated = ctx.updated_at
        time.sleep(0.01)
        host._apply_request_context(ctx, {"key": "val"})
        assert ctx.updated_at >= old_updated
