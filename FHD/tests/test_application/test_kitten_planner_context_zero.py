"""Tests for app.application.kitten_planner_context."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.kitten_planner_context import (
    enrich_kitten_analyzer_runtime,
    kitten_reply_attachments,
)


class TestEnrichKittenAnalyzerRuntime:
    """Tests for enrich_kitten_analyzer_runtime."""

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_not_kitten_analyzer(self) -> None:
        rc = {"some_key": "value"}
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert result == {"some_key": "value"}

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_none_context(self) -> None:
        result = await enrich_kitten_analyzer_runtime(None, "hello")
        assert result == {}

    @pytest.mark.asyncio
    async def test_kitten_analyzer_without_business_db_or_web_search(self) -> None:
        rc = {"kitten_analyzer": True}
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert result["kitten_analyzer"] is True
        assert "kitten_business_snapshot" not in result

    @pytest.mark.asyncio
    async def test_kitten_analyzer_with_business_db_success(self) -> None:
        rc = {"kitten_analyzer": True, "kitten_include_business_db": True}
        with patch(
            "app.services.kitten_business_snapshot.build_kitten_business_snapshot",
            return_value={"success": True, "text": "snapshot", "stats": {}},
        ):
            result = await enrich_kitten_analyzer_runtime(rc, "hello")
            assert result["kitten_business_snapshot"]["success"] is True

    @pytest.mark.asyncio
    async def test_kitten_analyzer_with_business_db_failure(self) -> None:
        rc = {"kitten_analyzer": True, "kitten_include_business_db": True}
        with patch(
            "app.services.kitten_business_snapshot.build_kitten_business_snapshot",
            side_effect=ImportError("no module"),
        ):
            result = await enrich_kitten_analyzer_runtime(rc, "hello")
            assert result["kitten_business_snapshot"]["success"] is False

    @pytest.mark.asyncio
    async def test_kitten_analyzer_without_business_db_removes_snapshot(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "kitten_include_business_db": False,
            "kitten_business_snapshot": {"old": "data"},
        }
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert "kitten_business_snapshot" not in result

    @pytest.mark.asyncio
    async def test_kitten_analyzer_with_web_search_success(self) -> None:
        rc = {"kitten_analyzer": True, "kitten_web_search": True, "session_id": "sess1"}
        with patch(
            "app.infrastructure.web_search.kitten_web_search",
            new_callable=AsyncMock,
            return_value={"success": True, "hits": [{"title": "result"}], "provider": "test", "query": "hello"},
        ):
            result = await enrich_kitten_analyzer_runtime(rc, "hello")
            assert result["web_search_results"] == [{"title": "result"}]
            assert result["web_search_meta"]["provider"] == "test"

    @pytest.mark.asyncio
    async def test_kitten_analyzer_with_web_search_failure(self) -> None:
        rc = {"kitten_analyzer": True, "kitten_web_search": True, "session_id": "sess1"}
        with patch(
            "app.infrastructure.web_search.kitten_web_search",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "search failed"},
        ):
            result = await enrich_kitten_analyzer_runtime(rc, "hello")
            assert result["web_search_results"] == []
            assert result["web_search_error"] == "search failed"

    @pytest.mark.asyncio
    async def test_kitten_analyzer_web_search_exception(self) -> None:
        rc = {"kitten_analyzer": True, "kitten_web_search": True, "session_id": "sess1"}
        with patch(
            "app.infrastructure.web_search.kitten_web_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await enrich_kitten_analyzer_runtime(rc, "hello")
            assert result["web_search_results"] == []
            assert "network error" in result["web_search_error"]

    @pytest.mark.asyncio
    async def test_kitten_analyzer_without_web_search_removes_keys(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "kitten_web_search": False,
            "web_search_results": ["old"],
            "web_search_meta": {"old": True},
            "web_search_error": "old error",
        }
        result = await enrich_kitten_analyzer_runtime(rc, "hello")
        assert "web_search_results" not in result
        assert "web_search_meta" not in result
        assert "web_search_error" not in result


class TestKittenReplyAttachments:
    """Tests for kitten_reply_attachments."""

    def test_returns_empty_when_not_kitten_analyzer(self) -> None:
        result = kitten_reply_attachments({"some_key": "value"})
        assert result == {}

    def test_returns_empty_when_none(self) -> None:
        result = kitten_reply_attachments(None)
        assert result == {}

    def test_returns_web_search_results(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [{"title": "r1"}],
        }
        result = kitten_reply_attachments(rc)
        assert result["web_search_results"] == [{"title": "r1"}]

    def test_includes_web_search_meta(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [],
            "web_search_meta": {"provider": "test"},
        }
        result = kitten_reply_attachments(rc)
        assert result["web_search_meta"]["provider"] == "test"

    def test_includes_web_search_error(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [],
            "web_search_error": "failed",
        }
        result = kitten_reply_attachments(rc)
        assert result["web_search_error"] == "failed"

    def test_truncates_long_error(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [],
            "web_search_error": "x" * 1000,
        }
        result = kitten_reply_attachments(rc)
        assert len(result["web_search_error"]) <= 500

    def test_empty_meta_excluded(self) -> None:
        rc = {
            "kitten_analyzer": True,
            "web_search_results": [],
            "web_search_meta": {},
        }
        result = kitten_reply_attachments(rc)
        assert "web_search_meta" not in result
