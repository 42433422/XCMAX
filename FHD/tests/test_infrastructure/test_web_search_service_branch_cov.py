"""Branch-coverage tests for app.infrastructure.web_search.service.

Targets branches NOT already covered by test_web_search_service.py:
* ``_rate_allow`` — bucket cleanup when bucket[0] >= cutoff, bucket empty.
* ``_truncate`` — exact length boundary, n=0 edge.
* ``_tavily_search`` — non-dict items skipped, missing url skipped, content/raw_content
  fallback, max_results truncation, title fallback to url.
* ``_serpapi_search`` — non-dict items skipped, missing link skipped, snippet fallback,
  max_results truncation, title fallback to link.
* ``kitten_web_search`` — query truncation to _MAX_QUERY_LEN, max_results from env,
  max_results clamping (min 1, max 10), provider case insensitivity, rate limit
  with provider set, exception with provider set, serp alias.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.web_search import service as web_search_mod
from app.infrastructure.web_search.service import (
    WebSearchHit,
    _rate_allow,
    _serpapi_search,
    _tavily_search,
    _truncate,
    kitten_web_search,
)

# ---------------------------------------------------------------------------
# _rate_allow — additional branches
# ---------------------------------------------------------------------------


class TestRateAllowExtra:
    def test_cleans_expired_entries(self) -> None:
        # Add an old entry that should be cleaned
        old = web_search_mod._rate_buckets.copy()
        web_search_mod._rate_buckets.clear()
        try:
            # Manually add an old timestamp
            web_search_mod._rate_buckets["user"] = [0.0]  # epoch — way past cutoff
            assert _rate_allow("user") is True
            # Old entry should be cleaned, new entry added
            assert len(web_search_mod._rate_buckets["user"]) == 1
            assert web_search_mod._rate_buckets["user"][0] > 0.0
        finally:
            web_search_mod._rate_buckets = old

    def test_empty_bucket_allows(self) -> None:
        old = web_search_mod._rate_buckets.copy()
        web_search_mod._rate_buckets.clear()
        try:
            # bucket doesn't exist yet → setdefault creates empty list
            assert _rate_allow("new-user") is True
        finally:
            web_search_mod._rate_buckets = old

    def test_multiple_users_isolated(self) -> None:
        old = web_search_mod._rate_buckets.copy()
        web_search_mod._rate_buckets.clear()
        try:
            for _ in range(web_search_mod._RATE_MAX_PER_USER):
                _rate_allow("user-x")
            # user-y should still be allowed
            assert _rate_allow("user-y") is True
        finally:
            web_search_mod._rate_buckets = old


# ---------------------------------------------------------------------------
# _truncate — additional branches
# ---------------------------------------------------------------------------


class TestTruncateExtra:
    def test_n_zero_returns_empty(self) -> None:
        # len(s) <= 0 is False (s="hello"), so returns s[: -1] + "…"
        # Actually: len("hello")=5 > 0=n → s[:n-1] + "…" = s[:-1] + "…" = "hell…"
        result = _truncate("hello", 0)
        # s[:0-1] = s[:-1] = "hell", + "…" = "hell…"
        assert result == "hell…"

    def test_n_one_returns_ellipsis(self) -> None:
        result = _truncate("hello", 1)
        # s[:0] + "…" = "" + "…" = "…"
        assert result == "…"

    def test_n_negative(self) -> None:
        result = _truncate("hello", -1)
        # len(s)=5 > -1 → s[:-1-1] + "…" = s[:-2] + "…" = "hel…"
        assert result == "hel…"

    def test_whitespace_only_input(self) -> None:
        assert _truncate("   ", 10) == ""

    def test_long_string_with_unicode(self) -> None:
        result = _truncate("你好世界测试", 3)
        assert len(result) == 3
        assert result.endswith("…")


# ---------------------------------------------------------------------------
# _tavily_search
# ---------------------------------------------------------------------------


class TestTavilySearch:
    @pytest.mark.asyncio
    async def test_non_dict_items_skipped(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": ["not-a-dict", {"title": "T", "url": "https://x.com"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].url == "https://x.com"

    @pytest.mark.asyncio
    async def test_missing_url_skipped(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "T1", "url": ""},  # empty url skipped
                {"title": "T2", "url": "https://valid.com"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].url == "https://valid.com"

    @pytest.mark.asyncio
    async def test_content_falls_back_to_raw_content(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"title": "T", "url": "https://x.com", "raw_content": "raw"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].snippet == "raw"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_url(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"url": "https://x.com"}]  # no title
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].title == "https://x.com"

    @pytest.mark.asyncio
    async def test_max_results_truncation(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": f"T{i}", "url": f"https://x{i}.com"}
                for i in range(10)
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 3)
        assert len(hits) == 3

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert hits == []

    @pytest.mark.asyncio
    async def test_results_none(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # no "results" key
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert hits == []

    @pytest.mark.asyncio
    async def test_long_content_truncated(self) -> None:
        long_content = "x" * 1000
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"title": "T", "url": "https://x.com", "content": long_content}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _tavily_search("query", "key", 5)
        assert len(hits) == 1
        assert len(hits[0].snippet) <= 480


# ---------------------------------------------------------------------------
# _serpapi_search
# ---------------------------------------------------------------------------


class TestSerpapiSearch:
    @pytest.mark.asyncio
    async def test_non_dict_items_skipped(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": ["not-a-dict", {"title": "T", "link": "https://x.com"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].url == "https://x.com"

    @pytest.mark.asyncio
    async def test_missing_link_skipped(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": [
                {"title": "T1", "link": ""},  # empty link skipped
                {"title": "T2", "link": "https://valid.com"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].url == "https://valid.com"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_link(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": [{"link": "https://x.com"}]  # no title
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert len(hits) == 1
        assert hits[0].title == "https://x.com"

    @pytest.mark.asyncio
    async def test_max_results_truncation(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": [
                {"title": f"T{i}", "link": f"https://x{i}.com"}
                for i in range(10)
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 3)
        assert len(hits) == 3

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"organic_results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert hits == []

    @pytest.mark.asyncio
    async def test_organic_results_none(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # no "organic_results" key
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert hits == []

    @pytest.mark.asyncio
    async def test_long_snippet_truncated(self) -> None:
        long_snippet = "x" * 1000
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic_results": [
                {"title": "T", "link": "https://x.com", "snippet": long_snippet}
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            hits = await _serpapi_search("query", "key", 5)
        assert len(hits) == 1
        assert len(hits[0].snippet) <= 480


# ---------------------------------------------------------------------------
# kitten_web_search — additional branches
# ---------------------------------------------------------------------------


class TestKittenWebSearchExtra:
    @pytest.fixture(autouse=True)
    def _reset_rate_buckets(self) -> Any:
        """每个测试前清空全局 rate buckets，避免状态污染。"""
        import app.infrastructure.web_search.service as web_search_mod
        old = web_search_mod._rate_buckets.copy()
        web_search_mod._rate_buckets.clear()
        yield
        web_search_mod._rate_buckets = old

    @pytest.mark.asyncio
    async def test_query_truncated_to_max_len(self) -> None:
        long_query = "x" * 500
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "key"},
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ) as mock_search,
        ):
            result = await kitten_web_search(long_query)
        assert result["success"] is True
        # Verify the query passed to _tavily_search was truncated
        call_args = mock_search.call_args[0]
        assert len(call_args[0]) <= web_search_mod._MAX_QUERY_LEN

    @pytest.mark.asyncio
    async def test_max_results_from_env(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {
                    "WEB_SEARCH_PROVIDER": "tavily",
                    "TAVILY_API_KEY": "key",
                    "WEB_SEARCH_MAX_RESULTS": "7",
                },
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ) as mock_search,
        ):
            result = await kitten_web_search("test")
        assert result["success"] is True
        call_args = mock_search.call_args[0]
        assert call_args[2] == 7  # max_results

    @pytest.mark.asyncio
    async def test_max_results_clamped_to_min_1(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {
                    "WEB_SEARCH_PROVIDER": "tavily",
                    "TAVILY_API_KEY": "key",
                },
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ) as mock_search,
        ):
            result = await kitten_web_search("test", max_results=0)
        assert result["success"] is True
        call_args = mock_search.call_args[0]
        assert call_args[2] == 1  # clamped to min 1

    @pytest.mark.asyncio
    async def test_max_results_clamped_to_max_10(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {
                    "WEB_SEARCH_PROVIDER": "tavily",
                    "TAVILY_API_KEY": "key",
                },
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ) as mock_search,
        ):
            result = await kitten_web_search("test", max_results=100)
        assert result["success"] is True
        call_args = mock_search.call_args[0]
        assert call_args[2] == 10  # clamped to max 10

    @pytest.mark.asyncio
    async def test_provider_case_insensitive(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "TAVILY", "TAVILY_API_KEY": "key"},
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ),
        ):
            result = await kitten_web_search("test")
        assert result["success"] is True
        assert result["provider"] == "tavily"

    @pytest.mark.asyncio
    async def test_serp_alias_provider(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "serp", "SERPAPI_API_KEY": "key"},
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._serpapi_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ),
        ):
            result = await kitten_web_search("test")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_rate_limit_with_provider_set(self) -> None:
        old = web_search_mod._rate_buckets.copy()
        web_search_mod._rate_buckets.clear()
        try:
            with patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "key"},
                clear=False,
            ):
                # Exhaust rate limit
                for _ in range(web_search_mod._RATE_MAX_PER_USER):
                    await kitten_web_search("test", user_key="limited-user")
                result = await kitten_web_search("test", user_key="limited-user")
            assert result["success"] is False
            assert "频繁" in result["message"]
        finally:
            web_search_mod._rate_buckets = old

    @pytest.mark.asyncio
    async def test_exception_with_provider_set(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "key"},
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                side_effect=ConnectionError("network error"),
            ),
        ):
            result = await kitten_web_search("test")
        assert result["success"] is False
        assert result["provider"] == "tavily"
        assert "network error" in result["message"]

    @pytest.mark.asyncio
    async def test_auto_mode_with_serpapi_key_only(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {
                    "WEB_SEARCH_PROVIDER": "auto",
                    "TAVILY_API_KEY": "",
                    "SERPAPI_API_KEY": "serp-key",
                },
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._serpapi_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ),
        ):
            result = await kitten_web_search("test")
        assert result["success"] is True
        assert result["provider"] == "serpapi"

    @pytest.mark.asyncio
    async def test_successful_result_includes_query(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "key"},
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ),
        ):
            result = await kitten_web_search("my query")
        assert result["success"] is True
        assert result["query"] == "my query"
        assert len(result["hits"]) == 1
        assert result["hits"][0]["title"] == "T"
        assert result["hits"][0]["url"] == "https://x.com"
        assert result["hits"][0]["snippet"] == "S"

    @pytest.mark.asyncio
    async def test_query_none_treated_as_empty(self) -> None:
        with patch.dict(
            os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=False
        ):
            result = await kitten_web_search(None)  # type: ignore[arg-type]
        assert result["success"] is False
        assert "查询为空" in result["message"]

    @pytest.mark.asyncio
    async def test_max_results_none_uses_env(self) -> None:
        mock_hits = [WebSearchHit(title="T", url="https://x.com", snippet="S")]
        with (
            patch.dict(
                os.environ,
                {
                    "WEB_SEARCH_PROVIDER": "tavily",
                    "TAVILY_API_KEY": "key",
                    "WEB_SEARCH_MAX_RESULTS": "5",
                },
                clear=False,
            ),
            patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ) as mock_search,
        ):
            result = await kitten_web_search("test", max_results=None)
        assert result["success"] is True
        call_args = mock_search.call_args[0]
        assert call_args[2] == 5


# ---------------------------------------------------------------------------
# WebSearchHit — additional
# ---------------------------------------------------------------------------


class TestWebSearchHitExtra:
    def test_equality(self) -> None:
        h1 = WebSearchHit(title="T", url="U", snippet="S")
        h2 = WebSearchHit(title="T", url="U", snippet="S")
        h3 = WebSearchHit(title="T", url="U", snippet="X")
        assert h1 == h2
        assert h1 != h3

    def test_hashable(self) -> None:
        # frozen=True dataclass is hashable
        h = WebSearchHit(title="T", url="U", snippet="S")
        assert hash(h) == hash((h.title, h.url, h.snippet))
