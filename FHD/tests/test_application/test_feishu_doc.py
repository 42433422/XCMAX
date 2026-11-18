"""飞书云文档导入：鉴权缓存、正文读取、错误归一化与路由接线。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.infrastructure.document_parsing import feishu_doc
from app.infrastructure.document_parsing.feishu_doc import FetchedFeishuDoc, fetch_document


class _Response:
    def __init__(
        self, payload: dict | None = None, *, status_code: int = 200, raw: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = raw or json.dumps(self._payload).encode("utf-8")

    def json(self):
        return self._payload


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_FEISHU_APP_ID", "cli_app")
    monkeypatch.setenv("XCAGI_FEISHU_APP_SECRET", "secret")
    monkeypatch.delenv("XCAGI_FEISHU_BASE_URL", raising=False)
    feishu_doc.reset_token_cache_for_tests()


def _poster(token: str = "tenant-token"):
    calls: list[dict] = []

    def _post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return _Response({"code": 0, "tenant_access_token": token, "expire": 3600})

    return _post, calls


def test_missing_credentials_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("XCAGI_FEISHU_APP_SECRET", raising=False)
    with pytest.raises(ValueError, match="XCAGI_FEISHU_APP_ID"):
        fetch_document("docx12345678")


@pytest.mark.parametrize("doc_id", ["", "abc", "has space", "a" * 65])
def test_invalid_document_id_is_rejected(doc_id: str) -> None:
    with pytest.raises(ValueError, match="文档 ID"):
        fetch_document(doc_id)


def test_fetch_reads_raw_content_and_caches_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    poster, post_calls = _poster("tok")
    seen: list[dict] = []

    def _get(url, **kwargs):
        seen.append({"url": url, "kwargs": kwargs})
        return _Response({"code": 0, "data": {"content": "发布规范\n第一段正文"}})

    first = fetch_document("docx12345678", getter=_get, poster=poster)
    second = fetch_document("docx12345678", getter=_get, poster=poster)

    assert first.text == "发布规范\n第一段正文"
    assert first.title == "发布规范"
    assert first.url == "feishu://docx/docx12345678"
    assert second.document_id == "docx12345678"
    assert len(post_calls) == 1  # token 复用
    assert seen[0]["url"].endswith("/open-apis/docx/v1/documents/docx12345678/raw_content")
    assert seen[0]["kwargs"]["headers"]["Authorization"] == "Bearer tok"


def test_auth_and_document_errors_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def _bad_post(url, **kwargs):
        return _Response({"code": 10003, "msg": "invalid param"})

    with pytest.raises(ValueError, match="飞书鉴权失败"):
        fetch_document("docx12345678", getter=lambda *_a, **_k: _Response(), poster=_bad_post)

    poster, _ = _poster()
    with pytest.raises(ValueError, match="飞书文档读取失败"):
        fetch_document(
            "docx12345678",
            getter=lambda *_a, **_k: _Response({"code": 1770002, "msg": "not found"}),
            poster=poster,
        )
    with pytest.raises(ValueError, match="飞书文档返回 HTTP 500"):
        fetch_document(
            "docx12345678", getter=lambda *_a, **_k: _Response(status_code=500), poster=poster
        )
    huge = b"x" * (feishu_doc.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="大小限制"):
        fetch_document(
            "docx12345678",
            getter=lambda *_a, **_k: _Response(raw=huge),
            poster=poster,
        )
    with pytest.raises(ValueError, match="内容为空"):
        fetch_document(
            "docx12345678",
            getter=lambda *_a, **_k: _Response({"code": 0, "data": {"content": "  "}}),
            poster=poster,
        )


def _route_client(calls: list[dict]) -> TestClient:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    return TestClient(app, raise_server_exceptions=False)


def test_route_ingests_feishu_document(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    doc = FetchedFeishuDoc(
        document_id="docx12345678",
        url="feishu://docx/docx12345678",
        title="发布规范",
        text="发布规范\n第一段正文",
    )
    monkeypatch.setattr(feishu_doc, "fetch_document", lambda _doc_id: doc)

    response = _route_client(calls).post(
        "/datasets/kb/documents", json={"feishu_document_id": "docx12345678"}
    )

    assert response.status_code == 200
    params = calls[0]["params"]
    assert params["text"] == doc.text
    assert params["source"] == "发布规范"
    assert params["document_id"] == doc.url
    assert params["metadata"]["feishu_document_id"] == "docx12345678"


def test_route_maps_feishu_failure_and_exclusivity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _boom(_doc_id):
        raise ValueError("未配置 XCAGI_FEISHU_APP_SECRET")

    monkeypatch.setattr(feishu_doc, "fetch_document", _boom)
    client = _route_client(calls)

    failed = client.post("/datasets/kb/documents", json={"feishu_document_id": "docx12345678"})
    mixed = client.post(
        "/datasets/kb/documents", json={"feishu_document_id": "docx12345678", "text": "inline"}
    )

    assert failed.status_code == 400
    assert "XCAGI_FEISHU_APP_SECRET" in failed.json()["detail"]
    assert mixed.status_code == 422
    assert calls == []
