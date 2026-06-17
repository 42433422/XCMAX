"""Tests for app.fastapi_routes.domains.conversation.compat_extra — conversation compat routes."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.conversation.compat_extra import (
    _conversation_lock,
    _xcagi_evict_oldest_session_if_needed,
    _xcagi_iso_from_ts,
    _xcagi_normalize_chat_role,
    _xcagi_resolve_session_scope,
    _xcagi_strip_html,
    _xcagi_summary_from_messages,
    _xcagi_title_from_messages,
    _xcagi_user_sessions,
    router,
)

# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestXcagiResolveSessionScope:
    def test_default_user_id(self):
        scope = _xcagi_resolve_session_scope(None, None)
        assert scope[0] == "default"
        assert scope[1] == ""

    def test_explicit_user_and_mod(self):
        scope = _xcagi_resolve_session_scope("user1", "mod1")
        assert scope[0] == "user1"
        assert scope[1] == "mod1"

    def test_empty_string_user_becomes_default(self):
        scope = _xcagi_resolve_session_scope("", None)
        assert scope[0] == "default"

    def test_mod_from_request_context(self):
        with patch(
            "app.fastapi_routes.domains.conversation.compat_extra.get_request_active_mod_id",
            return_value="auto_mod",
        ):
            scope = _xcagi_resolve_session_scope("u1", None)
        assert scope[1] == "auto_mod"

    def test_mod_request_context_error_falls_back(self):
        with patch(
            "app.fastapi_routes.domains.conversation.compat_extra.get_request_active_mod_id",
            side_effect=RuntimeError("no ctx"),
        ):
            scope = _xcagi_resolve_session_scope("u1", None)
        assert scope[1] == ""


class TestXcagiStripHtml:
    def test_strips_tags(self):
        assert _xcagi_strip_html("<b>hello</b>") == "hello"

    def test_no_tags(self):
        assert _xcagi_strip_html("plain text") == "plain text"

    def test_none_returns_empty(self):
        assert _xcagi_strip_html(None) == ""

    def test_nested_tags(self):
        assert _xcagi_strip_html("<div><p>hi</p></div>") == "hi"


class TestXcagiIsoFromTs:
    def test_known_timestamp(self):
        result = _xcagi_iso_from_ts(0.0)
        assert result.endswith("Z")

    def test_float_timestamp(self):
        result = _xcagi_iso_from_ts(1700000000.0)
        assert "T" in result or result.endswith("Z")


class TestXcagiNormalizeChatRole:
    def test_assistant_becomes_ai(self):
        assert _xcagi_normalize_chat_role("assistant") == "ai"

    def test_model_becomes_ai(self):
        assert _xcagi_normalize_chat_role("model") == "ai"

    def test_user_stays(self):
        assert _xcagi_normalize_chat_role("user") == "user"

    def test_ai_stays(self):
        assert _xcagi_normalize_chat_role("ai") == "ai"

    def test_task_stays(self):
        assert _xcagi_normalize_chat_role("task") == "task"

    def test_unknown_becomes_ai(self):
        assert _xcagi_normalize_chat_role("system") == "ai"

    def test_none_becomes_user(self):
        # str(None or "user") => "user"
        assert _xcagi_normalize_chat_role(None) == "user"

    def test_empty_becomes_user(self):
        # str("" or "user") => "user"
        assert _xcagi_normalize_chat_role("") == "user"


class TestXcagiTitleFromMessages:
    def test_extracts_first_user_content(self):
        msgs = [{"role": "user", "content": "Hello world"}]
        assert _xcagi_title_from_messages(msgs) == "Hello world"

    def test_truncates_long_content(self):
        long_text = "x" * 100
        msgs = [{"role": "user", "content": long_text}]
        title = _xcagi_title_from_messages(msgs)
        assert len(title) <= 50
        assert title.endswith("…")

    def test_skips_non_user(self):
        msgs = [{"role": "ai", "content": "response"}]
        assert _xcagi_title_from_messages(msgs) is None

    def test_empty_messages(self):
        assert _xcagi_title_from_messages([]) is None

    def test_empty_content_skipped(self):
        msgs = [{"role": "user", "content": ""}]
        assert _xcagi_title_from_messages(msgs) is None


class TestXcagiSummaryFromMessages:
    def test_last_message_content(self):
        msgs = [{"role": "user", "content": "first"}, {"role": "ai", "content": "last reply"}]
        assert _xcagi_summary_from_messages(msgs) == "last reply"

    def test_empty_messages(self):
        assert _xcagi_summary_from_messages([]) == ""

    def test_truncates_long_content(self):
        long_text = "a" * 200
        msgs = [{"role": "ai", "content": long_text}]
        summary = _xcagi_summary_from_messages(msgs)
        assert len(summary) <= 123


class TestXcagiEvictOldestSession:
    def test_no_eviction_when_below_limit(self):
        bucket = {"s1": {"updated_ts": 1.0}}
        _xcagi_evict_oldest_session_if_needed(bucket, "s2")
        assert "s1" in bucket

    def test_eviction_removes_oldest(self):
        bucket = {}
        for i in range(200):
            bucket[f"s{i}"] = {"updated_ts": float(i)}
        # s0 has the lowest updated_ts, should be evicted
        _xcagi_evict_oldest_session_if_needed(bucket, "s_new")
        assert "s0" not in bucket
        assert "s_new" not in bucket  # s_new was not added, just evicted oldest

    def test_no_eviction_when_key_exists(self):
        bucket = {"s1": {"updated_ts": 1.0}}
        _xcagi_evict_oldest_session_if_needed(bucket, "s1")
        assert "s1" in bucket


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


class TestConversationsSaveMessage:
    def test_empty_session_id_returns_saved_false(self):
        client = TestClient(_make_app())
        with (
            patch(
                "app.fastapi_routes.domains.conversation.compat_extra.publish_simple_event",
                create=True,
            ),
            patch(
                "app.neuro_bus.route_event_publisher.publish_simple_event",
            ),
        ):
            resp = client.post("/conversations/message", json={"session_id": "", "content": "hi"})
        data = resp.json()
        assert data["saved"] is False

    def test_empty_content_returns_saved_false(self):
        client = TestClient(_make_app())
        with (
            patch(
                "app.fastapi_routes.domains.conversation.compat_extra.publish_simple_event",
                create=True,
            ),
            patch(
                "app.neuro_bus.route_event_publisher.publish_simple_event",
            ),
        ):
            resp = client.post("/conversations/message", json={"session_id": "s1", "content": ""})
        data = resp.json()
        assert data["saved"] is False

    def test_valid_message_saved(self):
        client = TestClient(_make_app())
        with patch(
            "app.neuro_bus.route_event_publisher.publish_simple_event",
        ):
            resp = client.post(
                "/conversations/message",
                json={"session_id": "s1", "content": "hello", "user_id": "u1"},
            )
        data = resp.json()
        assert data["saved"] is True


class TestConversationsSessionsList:
    def test_empty_sessions(self):
        client = TestClient(_make_app())
        resp = client.get("/conversations/sessions")
        data = resp.json()
        assert data["success"] is True
        assert data["sessions"] == []


class TestConversationsSessionsClear:
    def test_clear_empty(self):
        client = TestClient(_make_app())
        with patch(
            "app.neuro_bus.route_event_publisher.publish_simple_event",
        ):
            # First save a message to ensure there's data
            client.post(
                "/conversations/message",
                json={"session_id": "s1", "content": "hi", "user_id": "u_clear"},
            )
        resp = client.post(
            "/conversations/sessions/clear",
            json={"user_id": "u_clear"},
        )
        data = resp.json()
        assert data["success"] is True

    def test_clear_all_mods(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/conversations/sessions/clear",
            json={"user_id": "nobody", "all_mods": True},
        )
        data = resp.json()
        assert data["success"] is True


class TestAiConversationNew:
    def test_new_with_session_id(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/ai/conversation/new",
            json={"session_id": "my-session"},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["session_id"] == "my-session"

    def test_new_without_session_id_generates_one(self):
        client = TestClient(_make_app())
        resp = client.post("/ai/conversation/new", json={})
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]["session_id"]) > 0


class TestConversationsGet:
    def test_nonexistent_conversation(self):
        client = TestClient(_make_app())
        resp = client.get("/conversations/nonexistent-id")
        data = resp.json()
        assert data["success"] is True
        assert data["messages"] == []
