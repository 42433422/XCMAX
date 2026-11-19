"""链接页正文抓取（mock，不访问外网）。"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import httpx
import pytest

from modstore_server import openapi_connector_runtime as outbound


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


@pytest.fixture
def outbound_page_http(monkeypatch: pytest.MonkeyPatch):
    """Exercise the production HTTP request with a network-free transport."""
    state = SimpleNamespace(requests=[], options=[], respond=None)
    original_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        if state.respond is not None:
            return state.respond(request)
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, content=b"<html><body>public page</body></html>"
        )

    def client(**options):
        state.options.append(options)
        return original_client(transport=httpx.MockTransport(respond), **options)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ],
    )
    return state


@pytest.mark.asyncio
async def test_fetch_page_pins_public_dns_and_disables_ambient_proxy(outbound_page_http) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    text, error = await fetch_page_text("https://public.example:8443/page")
    assert error is None
    assert text == "public page"
    assert len(outbound_page_http.requests) == 1
    request = outbound_page_http.requests[0]
    assert str(request.url) == "https://93.184.216.34:8443/page"
    assert request.headers["Host"] == "public.example:8443"
    assert request.extensions["sni_hostname"] == "public.example"
    assert outbound_page_http.options[0]["trust_env"] is False
    assert outbound_page_http.options[0]["follow_redirects"] is False


@pytest.mark.asyncio
async def test_fetch_page_rejects_private_dns_without_request(outbound_page_http, monkeypatch) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.4", 443))
        ],
    )
    text, error = await fetch_page_text("https://private-dns.example/data")
    assert text == ""
    assert error is not None
    assert outbound_page_http.requests == []


@pytest.mark.asyncio
async def test_fetch_page_never_follows_redirect_to_private_network(outbound_page_http) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    outbound_page_http.respond = lambda _: httpx.Response(
        302, headers={"Location": "http://127.0.0.1/admin"}
    )
    text, error = await fetch_page_text("https://public.example/redirect")
    assert text == ""
    assert error == "重定向目标不可抓取"
    assert len(outbound_page_http.requests) == 1


@pytest.mark.asyncio
async def test_fetch_page_revalidates_each_public_redirect(outbound_page_http, monkeypatch) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    names = []

    def dns(host, port, **kwargs):
        names.append(host)
        ip = "93.184.216.34" if host == "first.example" else "93.184.216.35"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    monkeypatch.setattr(outbound.socket, "getaddrinfo", dns)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(301, headers={"Location": "https://second.example/final"})
        return httpx.Response(200, content=b"second page")

    outbound_page_http.respond = respond
    text, error = await fetch_page_text("https://first.example/redirect")
    assert error is None
    assert text == "second page"
    assert names == ["first.example", "second.example"]
    assert [req.headers["Host"] for req in outbound_page_http.requests] == [
        "first.example", "second.example"
    ]
    assert outbound_page_http.requests[-1].url.host == "93.184.216.35"


@pytest.mark.asyncio
async def test_fetch_page_rejects_oversized_stream(outbound_page_http) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    class Oversized(httpx.AsyncByteStream):
        chunks_read = 0
        closed = False

        async def __aiter__(self):
            for _ in range(3):
                self.chunks_read += 1
                yield b"x" * 600_000

        async def aclose(self) -> None:
            self.closed = True

    stream = Oversized()
    outbound_page_http.respond = lambda _: httpx.Response(200, stream=stream)
    text, error = await fetch_page_text("https://public.example/large")
    assert text == ""
    assert error == "响应过大"
    assert stream.chunks_read == 2
    assert stream.closed


@pytest.mark.asyncio
async def test_fetch_page_limits_redirect_hops(outbound_page_http) -> None:
    from modstore_server.web_page_fetch import fetch_page_text

    outbound_page_http.respond = lambda _: httpx.Response(302, headers={"Location": "/loop"})
    text, error = await fetch_page_text("https://public.example/loop")
    assert text == ""
    assert error == "跳转次数过多"
    assert len(outbound_page_http.requests) == 4


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@public.example/path",
        "https://public.example:99999/path",
        "https://public.example/path#fragment",
    ],
)
def test_url_prefilter_rejects_credentials_and_malformed_ports(url: str) -> None:
    from modstore_server.web_page_fetch import is_fetchable_http_url

    assert not is_fetchable_http_url(url)
