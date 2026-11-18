"""URL 导入连接器的安全边界与正文抽取。"""

from __future__ import annotations

import sys
import types

import pytest

from app.infrastructure.document_parsing import web_fetch


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes = b"<html><body>hello</body></html>",
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.status = status_code
        self._body = body
        self.headers = {"content-type": f"text/html; charset={encoding}", **(headers or {})}
        self.closed = False
        self.bytes_read = 0

    def stream(self, chunk_size: int, *, decode_content: bool):
        assert decode_content is True
        for start in range(0, len(self._body), chunk_size):
            chunk = self._body[start : start + chunk_size]
            self.bytes_read += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.delenv("XCAGI_KB_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )


def _transport(monkeypatch, *responses):
    pools = []
    pending = iter(responses)

    class Pool:
        def __init__(self, address, **options):
            self.address, self.options = address, options
            self.calls, self.closed = [], False
            pools.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def request(self, method, target, **options):
            self.calls.append((method, target, options))
            return next(pending)

    monkeypatch.setattr(web_fetch.urllib3, "HTTPConnectionPool", Pool)
    monkeypatch.setattr(web_fetch.urllib3, "HTTPSConnectionPool", Pool)
    return pools


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
    response = _Response(body="<html><body>正文内容</body></html>".encode())
    pools = _transport(monkeypatch, response)
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("正文内容", "示例标题"))

    page = web_fetch.fetch_url_text("https://example.com/read")

    assert page.text == "正文内容"
    assert page.title == "示例标题"
    assert page.url == "https://example.com/read"
    assert response.closed and pools[0].closed


def test_fetch_url_text_validates_each_redirect_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ALLOW_PRIVATE_URLS", raising=False)
    resolved: list[str] = []

    def _resolve(host, *_a, **_k):
        resolved.append(host)
        ip = "127.0.0.1" if host == "internal.example.com" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", _resolve)
    redirect = _Response(
        status_code=302, headers={"location": "http://internal.example.com/secret"}
    )
    pools = _transport(monkeypatch, redirect)

    with pytest.raises(ValueError, match="内网"):
        web_fetch.fetch_url_text("https://example.com/start")

    assert resolved == ["example.com", "internal.example.com"]
    assert len(pools) == 1 and pools[0].closed and redirect.closed


def test_fetch_url_text_rejects_empty_article(monkeypatch: pytest.MonkeyPatch) -> None:
    _transport(monkeypatch, _Response())
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura(None))

    with pytest.raises(ValueError, match="未提取到正文"):
        web_fetch.fetch_url_text("https://example.com/empty")


def test_fetch_url_text_rejects_oversize_body(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(body=b"x" * (web_fetch.MAX_BYTES * 2))
    pools = _transport(monkeypatch, response)

    with pytest.raises(ValueError, match="体积超过限制"):
        web_fetch.fetch_url_text("https://example.com/huge")
    assert response.bytes_read <= web_fetch.MAX_BYTES + 64 * 1024
    assert response.closed and pools[0].closed


@pytest.mark.parametrize(
    "address", ["0.0.0.0", "100.64.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "224.0.0.1"]
)
def test_url_rejects_nonpublic_and_mixed_dns_answers(monkeypatch, address):
    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", (address, 0))],
    )
    pools = _transport(monkeypatch)
    with pytest.raises(ValueError, match="内网"):
        web_fetch.fetch_url_text("http://example.com/")
    assert pools == []


@pytest.mark.parametrize(
    "url",
    ["https://user:secret@example.com/", "https://example.com:65536/", "https://example.com:bad/"],
)
def test_url_rejects_credentials_and_invalid_ports(monkeypatch, url):
    pools = _transport(monkeypatch)
    with pytest.raises(ValueError):
        web_fetch.fetch_url_text(url)
    assert pools == []


def test_url_pins_checked_ip_against_dns_rebinding_and_preserves_tls_identity(monkeypatch):
    resolved = []

    def rebinding(host, *_a, **_k):
        resolved.append(host)
        address = "93.184.216.34" if len(resolved) == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (address, 0))]

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", rebinding)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8080")
    pools = _transport(monkeypatch, _Response())
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("正文"))
    web_fetch.fetch_url_text("https://example.com:8443/read?q=1#fragment")
    assert resolved == ["example.com"] and pools[0].address == "93.184.216.34"
    assert pools[0].options == {
        "port": 8443,
        "server_hostname": "example.com",
        "assert_hostname": "example.com",
        "cert_reqs": "CERT_REQUIRED",
    }
    method, target, options = pools[0].calls[0]
    assert (method, target) == ("GET", "/read?q=1")
    assert options["headers"]["Host"] == "example.com:8443"
    assert options["preload_content"] is False and options["redirect"] is False
    assert options["retries"] is False


def test_url_allows_explicit_private_override_but_still_pins_ip(monkeypatch):
    monkeypatch.setenv("XCAGI_KB_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo", lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 0))]
    )
    pools = _transport(monkeypatch, _Response())
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("正文"))
    web_fetch.fetch_url_text("http://internal.example.com/")
    assert pools[0].address == "127.0.0.1"


def test_url_closes_all_redirects_and_enforces_hop_limit(monkeypatch):
    responses = [_Response(status_code=302, headers={"location": "/next"}) for _ in range(4)]
    pools = _transport(monkeypatch, *responses)
    with pytest.raises(ValueError, match="次数过多"):
        web_fetch.fetch_url_text("https://example.com/start")
    assert all(response.closed for response in responses)
    assert all(pool.closed for pool in pools)


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


def test_extract_html_text_returns_body_and_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("本地正文", "本地标题"))
    text, title = web_fetch.extract_html_text("<html><body>本地正文</body></html>")
    assert (text, title) == ("本地正文", "本地标题")


def test_extract_html_text_rejects_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura(None))
    with pytest.raises(ValueError, match="未提取到正文"):
        web_fetch.extract_html_text("<html></html>")


def test_html_file_ingest_uses_trafilatura_parser(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    page = tmp_path / "saved.html"
    page.write_text("<html><body>保存的网页正文</body></html>", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("保存的网页正文", "保存页"))
    service = DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=lambda text: [float(len(text)), 1.0],
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )

    result = service.ingest_document(
        dataset_id="kb", source="saved.html", file_path=str(page), tenant_id="t1"
    )

    assert result["success"] is True
    assert result["document"]["parser"] == "trafilatura_html"
    assert result["document"]["metadata"]["title"] == "保存页"


def test_upload_extensions_include_saved_pages() -> None:
    from app.fastapi_routes.knowledge.schemas import _DATASET_UPLOAD_EXTENSIONS

    assert {".html", ".htm"} <= _DATASET_UPLOAD_EXTENSIONS
