"""第二波真实行为测试: app/infrastructure/web_search/service.py

覆盖既有测试未触及的行:
- _rate_allow 过期条目剔除 (line 34: bucket.pop(0))
- _tavily_search 真实函数体 (49,51,58-74): httpx 调用 + results 解析/过滤循环
- _serpapi_search 真实函数体 (78,80-97): httpx 调用 + organic_results 解析/过滤

策略: 用 httpx.MockTransport 驱动一个真实 httpx.AsyncClient，让被测函数的
``async with httpx.AsyncClient(...)`` / ``client.post`` / ``client.get`` 真正执行，
同时完全离线、确定性，无网络。_tavily_search/_serpapi_search 内部 ``import httpx``
绑定到全局 httpx 模块，故 patch ``httpx.AsyncClient`` 即可注入 transport。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.infrastructure.web_search import service as mod
from app.infrastructure.web_search.service import (
    _rate_allow,
    _serpapi_search,
    _tavily_search,
)


@contextmanager
def _patched_httpx(handler):
    """让 service 内的 httpx.AsyncClient 走 MockTransport(handler)。"""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    with patch.object(httpx, "AsyncClient", side_effect=factory):
        yield


@contextmanager
def _clean_rate_buckets():
    old = mod._rate_buckets
    mod._rate_buckets = {}
    try:
        yield mod._rate_buckets
    finally:
        mod._rate_buckets = old


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


# ---------------------------------------------------------------------------
# _rate_allow: 过期条目剔除分支 (line 33-34 while ... bucket.pop(0))
# ---------------------------------------------------------------------------


class TestRateAllowExpiry:
    def test_stale_entries_pruned_then_allowed(self):
        """桶里全是 > window 之前的旧时间戳 -> 被 pop 清空 -> 再次放行。"""
        with _clean_rate_buckets() as buckets:
            # 注入早于 cutoff 的旧时间戳 (远在 _RATE_WINDOW_SEC 之前)
            stale = 1.0  # epoch 起点附近, 必然 < now - window
            buckets["u"] = [stale] * mod._RATE_MAX_PER_USER
            # 此时桶已满, 但全过期; _rate_allow 应剔除全部并放行
            assert _rate_allow("u") is True
            # 剔除后桶里只剩本次新加入的 1 条 (新 now)
            assert len(buckets["u"]) == 1
            assert buckets["u"][0] > stale

    def test_partial_stale_pruned(self):
        """部分过期: 旧条目剔除, 新近条目保留, 仍在配额内 -> 放行。"""
        import time

        with _clean_rate_buckets() as buckets:
            now = time.time()
            stale = now - mod._RATE_WINDOW_SEC - 5  # 过期
            fresh = now - 1  # 仍在窗口内
            buckets["u"] = [stale, stale, fresh]
            assert _rate_allow("u") is True
            # 两条 stale 被 pop, 保留 fresh + 新加入 = 2 条
            assert len(buckets["u"]) == 2
            assert all(ts >= fresh for ts in buckets["u"])

    def test_no_prune_when_all_fresh(self):
        """全部新近 -> while 条件首轮即假, 不触发 pop, 正常累加。"""
        import time

        with _clean_rate_buckets() as buckets:
            fresh = time.time() - 1
            buckets["u"] = [fresh]
            assert _rate_allow("u") is True
            assert len(buckets["u"]) == 2


# ---------------------------------------------------------------------------
# _tavily_search: 真实函数体 (49,51,58-74)
# ---------------------------------------------------------------------------


class TestTavilySearch:
    @pytest.mark.asyncio
    async def test_parses_results_and_posts_payload(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["body"] = json.loads(request.content.decode())
            return _json_response(
                {
                    "results": [
                        {
                            "title": "Hello",
                            "url": "https://a.example",
                            "content": "body content",
                        }
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _tavily_search("q1", "tav-key", 5)

        # 真实发出的是 POST 到 tavily search 端点
        assert captured["method"] == "POST"
        assert captured["url"] == "https://api.tavily.com/search"
        # payload 携带 api_key/query/固定参数 (覆盖 51-57 payload 构造)
        assert captured["body"]["api_key"] == "tav-key"
        assert captured["body"]["query"] == "q1"
        assert captured["body"]["search_depth"] == "basic"
        assert captured["body"]["max_results"] == 5
        assert captured["body"]["include_answer"] is False
        # 解析结果
        assert len(hits) == 1
        assert hits[0].title == "Hello"
        assert hits[0].url == "https://a.example"
        assert hits[0].snippet == "body content"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_url_and_raw_content(self):
        """无 title -> 用 url; content 缺失 -> 用 raw_content (覆盖 66/68 的 or 链)。"""

        def handler(request):
            return _json_response(
                {
                    "results": [
                        {"url": "https://b.example", "raw_content": "raw text here"},
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _tavily_search("q", "k", 5)

        assert len(hits) == 1
        assert hits[0].title == "https://b.example"  # title 空 -> url
        assert hits[0].snippet == "raw text here"  # content 空 -> raw_content

    @pytest.mark.asyncio
    async def test_skips_non_dict_and_missing_url(self):
        """非 dict item (line 64-65) 与缺 url item (69-70) 都被跳过。"""

        def handler(request):
            return _json_response(
                {
                    "results": [
                        "i-am-a-string",  # 非 dict -> continue
                        {"title": "no url here"},  # 缺 url -> continue
                        {"title": "good", "url": "https://ok.example", "content": "c"},
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _tavily_search("q", "k", 5)

        assert len(hits) == 1
        assert hits[0].url == "https://ok.example"

    @pytest.mark.asyncio
    async def test_respects_max_results_break(self):
        """超过 max_results 后 break (line 72-73)。"""

        def handler(request):
            return _json_response(
                {
                    "results": [
                        {"url": f"https://x{i}.example", "title": f"t{i}", "content": "c"}
                        for i in range(10)
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _tavily_search("q", "k", 3)

        assert len(hits) == 3
        assert [h.url for h in hits] == [
            "https://x0.example",
            "https://x1.example",
            "https://x2.example",
        ]

    @pytest.mark.asyncio
    async def test_empty_results_key(self):
        """results 缺失 -> data.get('results') or [] 走空列表 (line 63)。"""

        def handler(request):
            return _json_response({})

        with _patched_httpx(handler):
            hits = await _tavily_search("q", "k", 5)

        assert hits == []

    @pytest.mark.asyncio
    async def test_long_snippet_truncated_to_480(self):
        """content 超长 -> snippet 走 _truncate(..., 480)。"""
        long_text = "z" * 1000

        def handler(request):
            return _json_response(
                {"results": [{"url": "https://t.example", "title": "t", "content": long_text}]}
            )

        with _patched_httpx(handler):
            hits = await _tavily_search("q", "k", 5)

        assert len(hits[0].snippet) == 480
        assert hits[0].snippet.endswith("…")

    @pytest.mark.asyncio
    async def test_raise_for_status_propagates(self):
        """HTTP 非 2xx -> raise_for_status 抛 HTTPStatusError (line 60)。"""

        def handler(request):
            return httpx.Response(500, json={"error": "boom"})

        with _patched_httpx(handler):
            with pytest.raises(httpx.HTTPStatusError):
                await _tavily_search("q", "k", 5)


# ---------------------------------------------------------------------------
# _serpapi_search: 真实函数体 (78,80-97)
# ---------------------------------------------------------------------------


class TestSerpapiSearch:
    @pytest.mark.asyncio
    async def test_parses_results_and_gets_params(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return _json_response(
                {
                    "organic_results": [
                        {
                            "title": "SerpTitle",
                            "link": "https://s.example",
                            "snippet": "serp snippet",
                        }
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _serpapi_search("serpq", "serp-key", 4)

        # 真实是 GET 到 serpapi 端点, 携带 engine/q/api_key/num 参数 (覆盖 80 params)
        assert captured["method"] == "GET"
        assert captured["path"] == "/search.json"
        assert captured["params"]["engine"] == "google"
        assert captured["params"]["q"] == "serpq"
        assert captured["params"]["api_key"] == "serp-key"
        assert captured["params"]["num"] == "4"
        # 解析
        assert len(hits) == 1
        assert hits[0].title == "SerpTitle"
        assert hits[0].url == "https://s.example"
        assert hits[0].snippet == "serp snippet"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_link(self):
        def handler(request):
            return _json_response({"organic_results": [{"link": "https://nolink-title.example"}]})

        with _patched_httpx(handler):
            hits = await _serpapi_search("q", "k", 5)

        assert len(hits) == 1
        assert hits[0].title == "https://nolink-title.example"
        assert hits[0].snippet == ""  # snippet 缺失 -> 空串

    @pytest.mark.asyncio
    async def test_skips_non_dict_and_missing_link(self):
        """非 dict (87-88) 与缺 link (92-93) 跳过。"""

        def handler(request):
            return _json_response(
                {
                    "organic_results": [
                        12345,  # 非 dict
                        {"title": "missing link"},  # 缺 link
                        {"title": "ok", "link": "https://ok.example", "snippet": "s"},
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _serpapi_search("q", "k", 5)

        assert len(hits) == 1
        assert hits[0].url == "https://ok.example"

    @pytest.mark.asyncio
    async def test_respects_max_results_break(self):
        """超过 max_results 后 break (95-96)。"""

        def handler(request):
            return _json_response(
                {
                    "organic_results": [
                        {"link": f"https://r{i}.example", "title": f"t{i}", "snippet": "s"}
                        for i in range(8)
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _serpapi_search("q", "k", 2)

        assert len(hits) == 2
        assert [h.url for h in hits] == ["https://r0.example", "https://r1.example"]

    @pytest.mark.asyncio
    async def test_empty_organic_results(self):
        def handler(request):
            return _json_response({"organic_results": None})

        with _patched_httpx(handler):
            hits = await _serpapi_search("q", "k", 5)

        assert hits == []

    @pytest.mark.asyncio
    async def test_long_snippet_truncated(self):
        def handler(request):
            return _json_response(
                {
                    "organic_results": [
                        {"link": "https://t.example", "title": "t", "snippet": "y" * 999}
                    ]
                }
            )

        with _patched_httpx(handler):
            hits = await _serpapi_search("q", "k", 5)

        assert len(hits[0].snippet) == 480
        assert hits[0].snippet.endswith("…")

    @pytest.mark.asyncio
    async def test_raise_for_status_propagates(self):
        def handler(request):
            return httpx.Response(429, json={"error": "rate"})

        with _patched_httpx(handler):
            with pytest.raises(httpx.HTTPStatusError):
                await _serpapi_search("q", "k", 5)


# ---------------------------------------------------------------------------
# 端到端: kitten_web_search 真正调用 _tavily_search/_serpapi_search 函数体
# (既有测试只 mock 这两个函数, 此处不 mock, 走真实解析 + httpx transport)
# ---------------------------------------------------------------------------


class TestKittenEndToEndRealBody:
    @pytest.mark.asyncio
    async def test_tavily_full_path(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "real-key")

        def handler(request):
            return _json_response(
                {"results": [{"title": "E2E", "url": "https://e.example", "content": "body"}]}
            )

        with _clean_rate_buckets():
            with _patched_httpx(handler):
                result = await mod.kitten_web_search("hello", user_key="e2e")

        assert result["success"] is True
        assert result["provider"] == "tavily"
        assert result["query"] == "hello"
        assert result["hits"] == [{"title": "E2E", "url": "https://e.example", "snippet": "body"}]

    @pytest.mark.asyncio
    async def test_serpapi_full_path(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
        monkeypatch.setenv("SERPAPI_API_KEY", "real-key")

        def handler(request):
            return _json_response(
                {
                    "organic_results": [
                        {"title": "E2E", "link": "https://e.example", "snippet": "snip"}
                    ]
                }
            )

        with _clean_rate_buckets():
            with _patched_httpx(handler):
                result = await mod.kitten_web_search("hello", user_key="e2e2")

        assert result["success"] is True
        assert result["provider"] == "serpapi"
        assert result["hits"][0]["snippet"] == "snip"

    @pytest.mark.asyncio
    async def test_http_error_caught_as_recoverable(self, monkeypatch):
        """真实 httpx.HTTPStatusError 是 RECOVERABLE_ERRORS, 被 except 兜底成 success=False。"""
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "real-key")

        def handler(request):
            return httpx.Response(503, json={"error": "down"})

        with _clean_rate_buckets():
            with _patched_httpx(handler):
                result = await mod.kitten_web_search("hello", user_key="e2e3")

        assert result["success"] is False
        assert result["provider"] == "tavily"
        assert result["hits"] == []
        assert result["message"]

    @pytest.mark.asyncio
    async def test_rate_limit_message_branch(self, monkeypatch):
        """桶已被预填满 -> kitten_web_search 命中 _rate_allow False 分支 (line 135-141)。"""
        import time

        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "real-key")

        now = time.time()
        with _clean_rate_buckets() as buckets:
            # 预填满 fresh 时间戳 -> _rate_allow 立刻拒绝, 不触发任何 httpx
            buckets["limited"] = [now] * mod._RATE_MAX_PER_USER
            result = await mod.kitten_web_search("hello", user_key="limited")

        assert result["success"] is False
        assert result["provider"] == "tavily"
        assert result["hits"] == []
        assert "频繁" in result["message"]
