"""Confluence 页面导入：配置校验、认证方式、正文抽取与路由接线。"""

from __future__ import annotations

import json
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.application.document_parsing import confluence
from app.application.document_parsing.confluence import FetchedConfluencePage, fetch_page


class _Response:
    def __init__(
        self, payload: dict | None = None, *, status_code: int = 200, raw: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = raw or json.dumps(self._payload).encode("utf-8")

    def json(self):
        return self._payload


def _fake_trafilatura(text: str | None, title: str = ""):
    module = types.ModuleType("trafilatura")

    def extract(_html, **_kwargs):
        return text

    def extract_metadata(_html, default_url=""):
        return types.SimpleNamespace(title=title)

    module.extract = extract
    module.extract_metadata = extract_metadata
    return module


def _configure(monkeypatch: pytest.MonkeyPatch, *, email: str = "") -> None:
    monkeypatch.setenv("XCAGI_CONFLUENCE_BASE_URL", "https://example.atlassian.net/wiki")
    monkeypatch.setenv("XCAGI_CONFLUENCE_API_TOKEN", "token-123")
    if email:
        monkeypatch.setenv("XCAGI_CONFLUENCE_EMAIL", email)
    else:
        monkeypatch.delenv("XCAGI_CONFLUENCE_EMAIL", raising=False)


def test_missing_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_CONFLUENCE_BASE_URL", raising=False)
    monkeypatch.setenv("XCAGI_CONFLUENCE_API_TOKEN", "t")
    with pytest.raises(ValueError, match="XCAGI_CONFLUENCE_BASE_URL"):
        fetch_page("123", getter=lambda *_a, **_k: _Response())
    monkeypatch.setenv("XCAGI_CONFLUENCE_BASE_URL", "https://example.atlassian.net/wiki")
    monkeypatch.delenv("XCAGI_CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.delenv("XCAGI_CONFLUENCE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="XCAGI_CONFLUENCE_API_TOKEN"):
        fetch_page("123", getter=lambda *_a, **_k: _Response())


@pytest.mark.parametrize("page_id", ["", "../etc", "a" * 65, "has space"])
def test_invalid_page_id_is_rejected(page_id: str) -> None:
    with pytest.raises(ValueError, match="页面 ID"):
        fetch_page(page_id, getter=lambda *_a, **_k: _Response())


def test_bearer_auth_and_body_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("页面正文", ""))
    seen: dict = {}

    def _get(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _Response(
            {
                "title": "发布规范",
                "body": {"storage": {"value": "<p>页面正文</p>"}},
            }
        )

    page = fetch_page("12345", getter=_get)

    assert page.text == "页面正文"
    assert page.title == "发布规范"
    assert page.url.endswith("/wiki/pages/12345")
    assert seen["url"].endswith("/rest/api/content/12345?expand=body.storage")
    assert seen["kwargs"]["headers"]["Authorization"] == "Bearer token-123"
    assert seen["kwargs"]["auth"] is None


def test_basic_auth_when_email_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, email="ops@example.com")
    monkeypatch.setitem(sys.modules, "trafilatura", _fake_trafilatura("正文"))
    seen: dict = {}

    def _get(url, **kwargs):
        seen["kwargs"] = kwargs
        return _Response({"title": "T", "body": {"storage": {"value": "<p>x</p>"}}})

    fetch_page("9", getter=_get)

    assert seen["kwargs"]["auth"] == ("ops@example.com", "token-123")
    assert "Authorization" not in seen["kwargs"]["headers"]


def test_http_error_and_oversize_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    with pytest.raises(ValueError, match="HTTP 404"):
        fetch_page("1", getter=lambda *_a, **_k: _Response(status_code=404))
    huge = b"x" * (confluence.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="大小限制"):
        fetch_page("1", getter=lambda *_a, **_k: _Response(raw=huge))


def test_route_ingests_confluence_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    page = FetchedConfluencePage(
        page_id="12345",
        url="https://example.atlassian.net/wiki/pages/12345",
        title="发布规范",
        text="页面正文",
    )
    monkeypatch.setattr(confluence, "fetch_page", lambda _pid: page)
    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/documents", json={"confluence_page_id": "12345"})

    assert response.status_code == 200
    params = calls[0]["params"]
    assert params["text"] == "页面正文"
    assert params["source"] == "发布规范"
    assert params["document_id"] == page.url
    assert params["metadata"]["confluence_page_id"] == "12345"
    assert params["metadata"]["source_url"] == page.url


def test_route_maps_confluence_failure_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    def _boom(_pid):
        raise ValueError("未配置 XCAGI_CONFLUENCE_API_TOKEN")

    monkeypatch.setattr(confluence, "fetch_page", _boom)
    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/documents", json={"confluence_page_id": "1"})

    assert response.status_code == 400
    assert "XCAGI_CONFLUENCE_API_TOKEN" in response.json()["detail"]
    assert calls == []


def test_confluence_source_cannot_be_combined() -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []
    routes = DocumentRoutes(
        dispatch=lambda: lambda **kwargs: calls.append(kwargs) or JSONResponse({"success": True}),
        uploads=lambda _get: None,
    )
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/datasets/kb/documents", json={"confluence_page_id": "1", "text": "inline"}
    )

    assert response.status_code == 422
    assert calls == []
