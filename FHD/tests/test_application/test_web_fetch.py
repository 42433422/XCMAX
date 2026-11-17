"""URL 导入连接器的安全边界与正文抽取。"""

from __future__ import annotations

import sys
import types

import pytest

from app.application.document_parsing import web_fetch


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes = b"<html><body>hello</body></html>",
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.encoding = encoding
        self.apparent_encoding = encoding

    @property
    def is_redirect(self) -> bool:
        return self.status_code in {301, 302, 303, 307, 308}

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]


def _fake_trafilatura(text: str | None, title: str = ""):
    module = types.ModuleType("trafilatura")

    def extract(html, **_kwargs):
        return text

    def extract_metadata(_html, default_url=""):
        return types.SimpleNamespace(title=title)

    module.extract = extract
    module.extract_metadata = extract_metadata
    return module


def test_assert_public_http_url_rejects_private_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="内网"):
        web_fetch.assert_public_http_url("http://internal.example.com/page")


def test_assert_public_http_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="http"):
        web_fetch.assert_public_http_url("file:///etc/passwd")


def test_assert_public_http_url_rejects_unresolved_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ALLOW_PRIVATE_URLS", raising=False)

    def _boom(*_a, **_k):
        raise OSError("dns failure")

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError, match="无法解析"):
        web_fetch.assert_public_http_url("http://missing.example.com/")


def test_fetch_url_text_extracts_article(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setattr(
        "requests.get",
        lambda *_a, **_k: _Response(body="<html><body>正文内容</body></html>".encode()),
    )
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("正文内容", "示例标题"))

    page = web_fetch.fetch_url_text("https://example.com/read")

    assert page.text == "正文内容"
    assert page.title == "示例标题"
    assert page.url == "https://example.com/read"


def test_fetch_url_text_validates_each_redirect_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ALLOW_PRIVATE_URLS", raising=False)
    resolved: list[str] = []

    def _resolve(host, *_a, **_k):
        resolved.append(host)
        ip = "127.0.0.1" if host == "internal.example.com" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", _resolve)
    monkeypatch.setattr(
        "requests.get",
        lambda *_a, **_k: _Response(
            status_code=302, headers={"location": "http://internal.example.com/secret"}
        ),
    )

    with pytest.raises(ValueError, match="内网"):
        web_fetch.fetch_url_text("https://example.com/start")

    assert resolved == ["example.com", "internal.example.com"]


def test_fetch_url_text_rejects_empty_article(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setattr("requests.get", lambda *_a, **_k: _Response())
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura(None))

    with pytest.raises(ValueError, match="未提取到正文"):
        web_fetch.fetch_url_text("https://example.com/empty")


def test_fetch_url_text_rejects_oversize_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setattr(
        "requests.get", lambda *_a, **_k: _Response(body=b"x" * (web_fetch.MAX_BYTES + 1))
    )

    with pytest.raises(ValueError, match="体积超过限制"):
        web_fetch.fetch_url_text("https://example.com/huge")


def _route_client(calls: list[dict]):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    def _dispatch(**_kwargs):
        from fastapi.responses import JSONResponse

        calls.append(_kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    return TestClient(app, raise_server_exceptions=False)


def test_ingest_route_uses_fetched_page_for_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    page = web_fetch.FetchedPage(url="https://example.com/a", title="页面标题", text="正文")
    monkeypatch.setattr(web_fetch, "fetch_url_text", lambda _url: page)

    response = _route_client(calls).post(
        "/datasets/kb/documents", json={"url": "https://example.com/a", "tenant_id": "t1"}
    )

    assert response.status_code == 200
    params = calls[0]["params"]
    assert params["text"] == "正文"
    assert params["source"] == "页面标题"
    assert params["document_id"] == "https://example.com/a"


def test_ingest_route_maps_fetch_failure_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _boom(_url):
        raise ValueError("禁止抓取内网地址")

    monkeypatch.setattr(web_fetch, "fetch_url_text", _boom)

    response = _route_client(calls).post(
        "/datasets/kb/documents", json={"url": "http://127.0.0.1/x"}
    )

    assert response.status_code == 400
    assert "内网" in response.json()["detail"]
    assert calls == []
