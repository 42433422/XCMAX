"""Second-wave behavioral tests for app.services.conversation.manager.

Targets previously-uncovered lines/branches without pulling in heavy ML deps:
- _check_habit_suggestion: habit-match return, low-confidence skip, except branch
  (lines 285-292)
- chat(): full happy path through intent recognition / context update /
  execute-or-generate, plus special-intent and pending-intent short-circuit
  branches and the top-level RECOVERABLE_ERRORS handler
  (lines 306-332, and error path)
- _InMemoryPersonaRepository: every async method (find/save/delete/append/list),
  including the limit slicing (lines 354-371)
- _build_persona_repository: success path + import-failure fallback to the
  in-memory repository (lines 384-386)

Every external dependency (LLM, DB, network, helper mixins) is mocked at the
in-function import site or stubbed directly on a bare instance built via
``__new__`` so ``AIConversationService.__init__`` (which wires real services) is
never executed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.context import ConversationContext
from app.services.conversation.manager import (
    AIConversationService,
    _build_persona_repository,
    _InMemoryPersonaRepository,
)


def _bare_service() -> AIConversationService:
    """Construct an AIConversationService without running its heavy __init__."""
    return AIConversationService.__new__(AIConversationService)


# ---------------------------------------------------------------------------
# _check_habit_suggestion (lines 285-292)
# ---------------------------------------------------------------------------
class TestCheckHabitSuggestion:
    def test_returns_suggestion_when_high_confidence_intent_matches(self):
        svc = _bare_service()
        svc.get_habit_suggestions = MagicMock(
            return_value=[
                {
                    "confidence": 0.95,
                    "actions": [
                        {"intent": "create_order", "description": "生成发货单"},
                    ],
                }
            ]
        )

        out = svc._check_habit_suggestion("u1", "create_order", {})

        assert out is not None
        assert "生成发货单" in out
        assert out.startswith("💡")

    def test_skips_low_confidence_habits(self):
        # confidence < 0.8 -> `continue` (line 286), no match returned
        svc = _bare_service()
        svc.get_habit_suggestions = MagicMock(
            return_value=[
                {
                    "confidence": 0.5,
                    "actions": [{"intent": "create_order", "description": "x"}],
                }
            ]
        )

        assert svc._check_habit_suggestion("u1", "create_order", {}) is None

    def test_no_matching_intent_returns_none(self):
        # high confidence but the action intent differs from current_intent
        svc = _bare_service()
        svc.get_habit_suggestions = MagicMock(
            return_value=[
                {
                    "confidence": 0.9,
                    "actions": [{"intent": "other_intent", "description": "x"}],
                }
            ]
        )

        assert svc._check_habit_suggestion("u1", "create_order", {}) is None

    def test_recoverable_error_is_swallowed_and_returns_none(self):
        # get_habit_suggestions raising a recoverable error -> except branch (291-292)
        svc = _bare_service()
        svc.get_habit_suggestions = MagicMock(side_effect=RuntimeError("boom"))

        assert svc._check_habit_suggestion("u1", "create_order", {}) is None


# ---------------------------------------------------------------------------
# chat() (lines 306-332 + error path)
# ---------------------------------------------------------------------------
def _wire_chat_service(intent_result=None):
    """Build a service with all chat() helper mixins stubbed."""
    svc = _bare_service()
    ctx = ConversationContext(user_id="u1")

    svc._get_or_create_context_async = AsyncMock(return_value=ctx)
    svc._recognize_intent = AsyncMock(
        return_value=intent_result
        if intent_result is not None
        else {
            "final_intent": "create_order",
            "primary_intent": "create_order",
            "tool_key": "order_tool",
            "slots": {},
            "intent_source": "rule",
        }
    )
    svc._enhance_intent_slots = MagicMock(side_effect=lambda _m, ir, _u: ir)
    svc._update_context_from_intent = MagicMock()
    svc._handle_special_intents = AsyncMock(return_value=None)
    svc._handle_pending_intent = AsyncMock(return_value=None)
    svc._execute_or_generate_response = AsyncMock(return_value={"text": "ok", "action": "respond"})
    # identity passthrough so we can assert the wrapper is invoked
    svc._maybe_attach_kitten_web = MagicMock(side_effect=lambda _c, r: r)
    return svc, ctx


class TestChat:
    async def test_happy_path_reaches_execute_or_generate(self):
        svc, ctx = _wire_chat_service()

        out = await svc.chat("u1", "帮我生成发货单")

        assert out == {"text": "ok", "action": "respond"}
        svc._get_or_create_context_async.assert_awaited_once()
        svc._recognize_intent.assert_awaited_once()
        svc._update_context_from_intent.assert_called_once()
        svc._handle_special_intents.assert_awaited_once()
        svc._handle_pending_intent.assert_awaited_once()
        svc._execute_or_generate_response.assert_awaited_once()
        # final result passed through the kitten-web wrapper
        svc._maybe_attach_kitten_web.assert_called_once_with(
            ctx, {"text": "ok", "action": "respond"}
        )

    async def test_special_intent_short_circuits(self):
        # _handle_special_intents returns truthy -> early return (lines 319-322),
        # pending + execute never run
        svc, ctx = _wire_chat_service()
        special = {"text": "special", "action": "special"}
        svc._handle_special_intents = AsyncMock(return_value=special)

        out = await svc.chat("u1", "x")

        assert out == special
        svc._handle_pending_intent.assert_not_awaited()
        svc._execute_or_generate_response.assert_not_awaited()
        svc._maybe_attach_kitten_web.assert_called_once_with(ctx, special)

    async def test_pending_intent_short_circuits(self):
        # special returns None, pending returns truthy -> return (lines 324-327)
        svc, ctx = _wire_chat_service()
        pending = {"text": "pending", "action": "confirm"}
        svc._handle_pending_intent = AsyncMock(return_value=pending)

        out = await svc.chat("u1", "x")

        assert out == pending
        svc._execute_or_generate_response.assert_not_awaited()
        svc._maybe_attach_kitten_web.assert_called_once_with(ctx, pending)

    async def test_recoverable_error_returns_error_envelope(self):
        # a recoverable error anywhere in the body -> except branch (334-340)
        svc, _ctx = _wire_chat_service()
        svc._recognize_intent = AsyncMock(side_effect=ValueError("bad intent"))

        out = await svc.chat("u1", "x")

        assert out["action"] == "error"
        assert "bad intent" in out["text"]
        assert out["data"] == {"message": "bad intent"}


# ---------------------------------------------------------------------------
# _InMemoryPersonaRepository (lines 353-371)
# ---------------------------------------------------------------------------
class TestInMemoryPersonaRepository:
    async def test_save_then_find_round_trips(self):
        repo = _InMemoryPersonaRepository()
        profile = MagicMock()
        profile.user_id = "u1"

        # not present yet
        assert await repo.find_by_user_id("u1") is None

        saved = await repo.save(profile)
        assert saved is profile
        assert await repo.find_by_user_id("u1") is profile

    async def test_delete_returns_true_then_false(self):
        repo = _InMemoryPersonaRepository()
        profile = MagicMock()
        profile.user_id = "u2"
        await repo.save(profile)

        assert await repo.delete("u2") is True
        # already gone -> pop returns None -> False
        assert await repo.delete("u2") is False
        assert await repo.find_by_user_id("u2") is None

    async def test_events_append_and_list_with_limit(self):
        repo = _InMemoryPersonaRepository()

        # empty before any append
        assert await repo.list_recent_events("u3") == []

        for i in range(5):
            await repo.append_event("u3", f"type{i}", {"i": i})

        all_events = await repo.list_recent_events("u3", limit=20)
        assert len(all_events) == 5
        assert all_events[0] == {"type": "type0", "data": {"i": 0}}

        # limit slices to the most-recent N (line 371)
        last_two = await repo.list_recent_events("u3", limit=2)
        assert [e["type"] for e in last_two] == ["type3", "type4"]


# ---------------------------------------------------------------------------
# _build_persona_repository (lines 380-386)
# ---------------------------------------------------------------------------
class TestBuildPersonaRepository:
    def test_returns_impl_on_success(self):
        sentinel = object()
        impl_module = MagicMock()
        impl_module.PersonaRepositoryImpl = MagicMock(return_value=sentinel)

        with patch.dict(
            "sys.modules",
            {"app.infrastructure.persona.persona_repository_impl": impl_module},
        ):
            assert _build_persona_repository() is sentinel
        impl_module.PersonaRepositoryImpl.assert_called_once_with()

    def test_falls_back_to_inmemory_on_construction_failure(self):
        # PersonaRepositoryImpl() raising -> except branch (384-386) -> in-memory repo
        impl_module = MagicMock()
        impl_module.PersonaRepositoryImpl = MagicMock(side_effect=RuntimeError("no redis"))

        with patch.dict(
            "sys.modules",
            {"app.infrastructure.persona.persona_repository_impl": impl_module},
        ):
            repo = _build_persona_repository()

        assert isinstance(repo, _InMemoryPersonaRepository)
