"""Bing 爬虫 + web_search_with_fallback（fixture，不访问真实搜索引擎）。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest


def test_bing_full_query_relevance_filter() -> None:
    from modstore_server.bing_web_search import filter_results_by_full_query

    astronomy = [
        {"title": "太阳_百度百科", "url": "https://baike.baidu.com/item/太阳", "content": "恒星"},
    ]
    assert filter_results_by_full_query("太阳鸟包装有限公司", astronomy) == []
    good = [
        {
            "title": "深圳市太阳鸟展示包装有限公司",
            "url": "https://example.com",
            "content": "包装",
        }
    ]
    assert len(filter_results_by_full_query("太阳鸟包装有限公司", good)) == 1


def test_contact_company_web_search_queries() -> None:
    from modstore_server.research_tools import contact_company_web_search_queries

    short = contact_company_web_search_queries("成都修茈科技")
    assert short[0] == "成都修茈科技"
    assert "成都修茈科技 有限公司" in short
    assert any("aiqicha.baidu.com" in q for q in short)
    assert any("qcc.com" in q for q in short)
    full = contact_company_web_search_queries("成都修茈科技有限公司")
    assert full[0] == "成都修茈科技有限公司"
    assert any("企查查" in q for q in full)


def test_rank_contact_serp_rows_prefers_query_hit() -> None:
    from modstore_server.research_tools import rank_contact_serp_rows

    rows = [
        {"title": "成都市_百度百科", "url": "https://baike.baidu.com", "content": ""},
        {"title": "成都修茈科技有限公司 | 官网", "url": "https://xiu-ci.com", "content": ""},
    ]
    ranked = rank_contact_serp_rows("成都修茈科技", rows)
    assert "修茈" in ranked[0]["title"]


def test_web_search_result_titles() -> None:
    from modstore_server.research_tools import clean_web_company_candidate, web_search_result_titles

    titles = web_search_result_titles(
        [
            {"title": "深圳市太阳鸟展示包装有限公司 - 爱企查", "url": "https://a.test"},
            {"title": "深圳市太阳鸟展示包装有限公司 - 水滴信用", "url": "https://b.test"},
            {"title": "其他公司有限责任公司", "url": "https://c.test"},
        ],
        limit=5,
        query="深圳太阳鸟",
    )
    assert titles == ["深圳市太阳鸟展示包装有限公司"]
    assert clean_web_company_candidate("某某贸易有限公司_百度百科", "某某") == "某某贸易有限公司"


def test_parse_bing_serp() -> None:
    from pathlib import Path

    from modstore_server.bing_web_search import parse_bing_serp_html

    html = (Path(__file__).parent / "fixtures" / "bing_serp_sample.html").read_text(
        encoding="utf-8"
    )
    out = parse_bing_serp_html(html, max_results=5)
    assert out and out[0]["url"] == "https://www.example.com/corp"


@pytest.mark.asyncio
async def test_web_search_fallback_uses_tavily_when_crawler_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modstore_server import research_tools as rt

    async def _empty_crawl(q: str, max_results: int = 10, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("captcha")

    async def _fake_tavily(q: str, max_results: int = 10):
        return [{"title": "T", "url": "https://example.com", "content": "ok"}]

    monkeypatch.setenv("MODSTORE_WEB_SEARCH_USE_TAVILY", "1")
    monkeypatch.setattr(rt, "web_crawl_engines_from_env", lambda: ["bing"])
    monkeypatch.setattr("modstore_server.bing_web_search.bing_html_search", _empty_crawl)
    monkeypatch.setattr(rt, "tavily_api_key", lambda: "k")
    monkeypatch.setattr(rt, "tavily_search", _fake_tavily)

    results, via, err = await rt.web_search_with_fallback("test", max_results=5)
    assert via == "tavily"
    assert results and results[0]["url"] == "https://example.com"
    assert err is None


@pytest.mark.asyncio
async def test_parallel_crawl_bing_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server import research_tools as rt

    async def _bing(q: str, max_results: int = 10, **kwargs):  # type: ignore[no-untyped-def]
        return [
            {"title": "A", "url": "https://a.test", "content": "1"},
            {"title": "B", "url": "https://b.test", "content": "2"},
        ]

    monkeypatch.setattr(rt, "web_crawl_engines_from_env", lambda: ["bing"])
    monkeypatch.setattr("modstore_server.bing_web_search.bing_html_search", _bing)

    results, via, errs = await rt.web_search_crawl_parallel("测试", max_results=10)
    assert not errs
    assert via == "bing"
    assert len(results) == 2


def test_web_crawl_engines_skips_baidu() -> None:
    import os

    from modstore_server import research_tools as rt

    old = os.environ.get("MODSTORE_WEB_CRAWL_ENGINES")
    try:
        os.environ["MODSTORE_WEB_CRAWL_ENGINES"] = "baidu,bing"
        assert rt.web_crawl_engines_from_env() == ["bing"]
    finally:
        if old is None:
            os.environ.pop("MODSTORE_WEB_CRAWL_ENGINES", None)
        else:
            os.environ["MODSTORE_WEB_CRAWL_ENGINES"] = old


def test_format_web_results_combined_groups_by_engine() -> None:
    from modstore_server.research_tools import format_web_results_combined

    text = format_web_results_combined(
        [
            {"title": "B", "url": "https://b.test", "content": "y", "crawl_engine": "bing"},
        ]
    )
    assert "Bing" in text
    assert "https://b.test" in text


@pytest.mark.asyncio
async def test_web_search_fallback_crawler_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server import research_tools as rt

    async def _bing(q: str, max_results: int = 10, **kwargs):  # type: ignore[no-untyped-def]
        return [{"title": "A", "url": "https://a.test", "content": ""}]

    monkeypatch.setattr(rt, "web_crawl_engines_from_env", lambda: ["bing"])
    monkeypatch.setattr("modstore_server.bing_web_search.bing_html_search", _bing)
    monkeypatch.setattr(rt, "tavily_api_key", lambda: "")

    results, via, err = await rt.web_search_with_fallback("测试", max_results=3)
    assert via == "bing"
    assert results[0]["url"] == "https://a.test"
    assert err is None
