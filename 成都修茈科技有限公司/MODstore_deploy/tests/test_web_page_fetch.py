"""链接页正文抓取（mock，不访问外网）。"""

from __future__ import annotations

import pytest


def test_html_to_plain_text_strips_tags() -> None:
    from modstore_server.web_page_fetch import html_to_plain_text

    text = html_to_plain_text(
        "<html><body><p>太阳鸟<strong>包装</strong></p></body></html>", max_chars=500
    )
    assert "太阳鸟" in text and "包装" in text
    assert "<p>" not in text


def test_is_fetchable_http_url_blocks_localhost() -> None:
    from modstore_server.web_page_fetch import is_fetchable_http_url

    assert not is_fetchable_http_url("http://127.0.0.1/foo")
    assert is_fetchable_http_url("https://www.example.com/foo")


@pytest.mark.asyncio
async def test_enrich_web_results_with_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server.web_page_fetch import enrich_web_results_with_pages

    async def _fake_fetch(url: str, **kwargs):  # type: ignore[no-untyped-def]
        return f"正文来自 {url}", None

    monkeypatch.setenv("MODSTORE_WEB_FETCH_PAGES", "1")
    monkeypatch.setattr("modstore_server.web_page_fetch.fetch_page_text", _fake_fetch)

    rows = await enrich_web_results_with_pages(
        [
            {"title": "A", "url": "https://a.test/1", "content": "摘要"},
            {"title": "B", "url": "https://b.test/2", "content": ""},
        ],
        max_pages=2,
    )
    assert rows[0]["page_fetched"] is True
    assert "正文来自" in rows[0]["page_content"]
    assert rows[1]["page_fetched"] is True


def test_format_web_result_item_includes_page_body() -> None:
    from modstore_server.research_tools import format_web_result_item

    text = format_web_result_item(
        "标题",
        "https://example.com",
        "搜索摘要",
        page_content="链接页正文段落",
    )
    assert "摘要:" in text
    assert "正文:" in text
    assert "链接页正文" in text
