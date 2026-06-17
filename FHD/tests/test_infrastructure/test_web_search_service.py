"""测试 web_search/service 模块 - 联网搜索服务。"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.infrastructure.web_search.service import (
    WebSearchHit,
    _rate_allow,
    _truncate,
    kitten_web_search,
)


class TestWebSearchHit:
    """测试 WebSearchHit 数据类。"""

    def test_create_hit(self):
        hit = WebSearchHit(title="Test", url="https://example.com", snippet="A snippet")
        assert hit.title == "Test"
        assert hit.url == "https://example.com"
        assert hit.snippet == "A snippet"

    def test_frozen(self):
        hit = WebSearchHit(title="T", url="U", snippet="S")
        with pytest.raises(AttributeError):
            hit.title = "new"


class TestTruncate:
    """测试 _truncate 辅助函数。"""

    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert _truncate("12345", 5) == "12345"

    def test_long_string_truncated(self):
        result = _truncate("1234567890", 5)
        assert len(result) == 5
        assert result.endswith("…")

    def test_none_input(self):
        assert _truncate(None, 10) == ""

    def test_empty_string(self):
        assert _truncate("", 10) == ""

    def test_strips_whitespace(self):
        assert _truncate("  hello  ", 10) == "hello"

    def test_truncate_after_strip(self):
        assert _truncate("  hello world  ", 6) == "hello…"


class TestRateAllow:
    """测试速率限制。"""

    def test_first_request_allowed(self):
        from app.infrastructure.web_search import service as mod

        old = mod._rate_buckets.copy()
        mod._rate_buckets.clear()
        try:
            assert _rate_allow("user1") is True
        finally:
            mod._rate_buckets = old

    def test_rate_limit_enforced(self):
        from app.infrastructure.web_search import service as mod

        old = mod._rate_buckets.copy()
        mod._rate_buckets.clear()
        try:
            for _ in range(mod._RATE_MAX_PER_USER):
                assert _rate_allow("user2") is True
            assert _rate_allow("user2") is False
        finally:
            mod._rate_buckets = old

    def test_different_users_independent(self):
        from app.infrastructure.web_search import service as mod

        old = mod._rate_buckets.copy()
        mod._rate_buckets.clear()
        try:
            for _ in range(mod._RATE_MAX_PER_USER):
                _rate_allow("user_a")
            assert _rate_allow("user_b") is True
        finally:
            mod._rate_buckets = old


class TestKittenWebSearch:
    """测试 kitten_web_search 主函数。"""

    @pytest.mark.asyncio
    async def test_unconfigured_provider(self):
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": ""}, clear=False):
            result = await kitten_web_search("test query")
            assert result["success"] is False
            assert "未配置" in result["message"]

    @pytest.mark.asyncio
    async def test_disabled_provider(self):
        for val in ("none", "off", "0", "false"):
            with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": val}, clear=False):
                result = await kitten_web_search("test query")
                assert result["success"] is False

    @pytest.mark.asyncio
    async def test_empty_query(self):
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=False):
            result = await kitten_web_search("")
            assert result["success"] is False
            assert "查询为空" in result["message"]

    @pytest.mark.asyncio
    async def test_blank_query(self):
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "tavily"}, clear=False):
            result = await kitten_web_search("   ")
            assert result["success"] is False
            assert "查询为空" in result["message"]

    @pytest.mark.asyncio
    async def test_tavily_missing_key(self):
        with patch.dict(
            os.environ, {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": ""}, clear=False
        ):
            result = await kitten_web_search("test")
            assert result["success"] is False
            assert "TAVILY_API_KEY" in result["message"]

    @pytest.mark.asyncio
    async def test_serpapi_missing_key(self):
        with patch.dict(
            os.environ, {"WEB_SEARCH_PROVIDER": "serpapi", "SERPAPI_API_KEY": ""}, clear=False
        ):
            result = await kitten_web_search("test")
            assert result["success"] is False
            assert "SERPAPI_API_KEY" in result["message"]

    @pytest.mark.asyncio
    async def test_auto_mode_no_keys(self):
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "auto", "TAVILY_API_KEY": "", "SERPAPI_API_KEY": ""},
            clear=False,
        ):
            result = await kitten_web_search("test")
            assert result["success"] is False
            assert "auto" in result["message"]

    @pytest.mark.asyncio
    async def test_unknown_provider(self):
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "bing"}, clear=False):
            result = await kitten_web_search("test")
            assert result["success"] is False
            assert "未知" in result["message"]

    @pytest.mark.asyncio
    async def test_query_truncation(self):
        long_query = "x" * 500
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": ""}, clear=False):
            result = await kitten_web_search(long_query)
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_tavily_search_success(self):
        mock_hits = [WebSearchHit(title="T", url="https://example.com", snippet="S")]
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "test-key"},
            clear=False,
        ):
            with patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ):
                result = await kitten_web_search("test query")
                assert result["success"] is True
                assert len(result["hits"]) == 1
                assert result["provider"] == "tavily"

    @pytest.mark.asyncio
    async def test_serpapi_search_success(self):
        mock_hits = [WebSearchHit(title="T", url="https://example.com", snippet="S")]
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "serpapi", "SERPAPI_API_KEY": "test-key"},
            clear=False,
        ):
            with patch(
                "app.infrastructure.web_search.service._serpapi_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ):
                result = await kitten_web_search("test query")
                assert result["success"] is True
                assert result["provider"] == "serpapi"

    @pytest.mark.asyncio
    async def test_auto_prefers_tavily(self):
        mock_hits = [WebSearchHit(title="T", url="https://example.com", snippet="S")]
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "auto", "TAVILY_API_KEY": "key", "SERPAPI_API_KEY": "key"},
            clear=False,
        ):
            with patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ):
                result = await kitten_web_search("test")
                assert result["success"] is True
                assert result["provider"] == "tavily"

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_serpapi(self):
        mock_hits = [WebSearchHit(title="T", url="https://example.com", snippet="S")]
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "auto", "TAVILY_API_KEY": "", "SERPAPI_API_KEY": "key"},
            clear=False,
        ):
            with patch(
                "app.infrastructure.web_search.service._serpapi_search",
                new_callable=AsyncMock,
                return_value=mock_hits,
            ):
                result = await kitten_web_search("test")
                assert result["success"] is True
                assert result["provider"] == "serpapi"

    @pytest.mark.asyncio
    async def test_max_results_clamped(self):
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": ""}, clear=False):
            result = await kitten_web_search("test", max_results=100)
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_search_exception_handled(self):
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "key"},
            clear=False,
        ):
            with patch(
                "app.infrastructure.web_search.service._tavily_search",
                new_callable=AsyncMock,
                side_effect=ConnectionError("network error"),
            ):
                result = await kitten_web_search("test")
                assert result["success"] is False
                assert "network error" in result["message"]
