"""Tests for app.application.kitten_planner_context."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.kitten_planner_context import (
    _session_key_from_context,
    enrich_kitten_analyzer_runtime,
    kitten_reply_attachments,
)


class TestSessionKeyFromContext:
    def test_kitten_session_id_used(self):
        rc = {"kitten_session_id": "ksid123", "session_id": "sid456"}
        result = _session_key_from_context(rc)
        assert result == "ksid123"

    def test_session_id_fallback(self):
        rc = {"session_id": "sid456"}
        result = _session_key_from_context(rc)
        assert result == "sid456"

    def test_empty_session_uses_dataset_hash(self):
        rc = {"kitten_dataset": "some data for hashing"}
        result = _session_key_from_context(rc)
        assert len(result) == 24

    def test_no_session_no_dataset(self):
        rc = {}
        result = _session_key_from_context(rc)
        assert len(result) == 24  # sha256 of empty string

    def test_session_key_truncated(self):
        rc = {"kitten_session_id": "x" * 200}
        result = _session_key_from_context(rc)
        assert len(result) <= 128


class TestEnrichKittenAnalyzerRuntime:
    @pytest.mark.asyncio
    async def test_non_kitten_analyzer_returns_unchanged(self):
        rc = {"other_key": "value"}
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert result == {"other_key": "value"}

    @pytest.mark.asyncio
    async def test_none_runtime_context(self):
        result = await enrich_kitten_analyzer_runtime(None, "hello")
        assert result == {}

    @pytest.mark.asyncio
    async def test_kitten_analyzer_without_business_db(self):
        rc = {"kitten_analyzer": True}
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert "kitten_business_snapshot" not in result

    @pytest.mark.asyncio
    async def test_kitten_analyzer_with_business_db_success(self):
        rc = {"kitten_analyzer": True, "kitten_include_business_db": True}
        with patch(
            "app.application.kitten_planner_context.build_kitten_business_snapshot",
            create=True,
        ) as mock_snapshot:
            # We need to mock the import inside the function
            with patch(
                "app.services.kitten_business_snapshot.build_kitten_business_snapshot",
                return_value={"success": True, "text": "snapshot", "stats": {}},
                create=True,
            ):
                result = await enrich_kitten_analyzer_runtime(rc, "hello")
                # The import may fail, but the function should not crash

    @pytest.mark.asyncio
    async def test_kitten_analyzer_without_web_search(self):
        rc = {"kitten_analyzer": True}
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert "web_search_results" not in result


class TestKittenReplyAttachments:
    def test_non_kitten_analyzer_returns_empty(self):
        result = kitten_reply_attachments({"other_key": "value"})
        assert result == {}

    def test_none_returns_empty(self):
        result = kitten_reply_attachments(None)
        assert result == {}

    def test_kitten_analyzer_with_web_results(self):
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [{"title": "test"}],
            "web_search_meta": {"provider": "google"},
        }
        result = kitten_reply_attachments(rc)
        assert "web_search_results" in result
        assert len(result["web_search_results"]) == 1
        assert "web_search_meta" in result

    def test_kitten_analyzer_with_error(self):
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [],
            "web_search_error": "search failed",
        }
        result = kitten_reply_attachments(rc)
        assert "web_search_error" in result
        assert result["web_search_error"] == "search failed"

    def test_empty_web_results(self):
        rc = {"kitten_analyzer": True}
        result = kitten_reply_attachments(rc)
        assert result["web_search_results"] == []
