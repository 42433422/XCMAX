"""语雀文档导入：配置校验、正文解析、错误映射、路由接线与来源刷新。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.application.document_parsing.yuque import fetch_document


class _Response:
    def __init__(self, payload: dict | None = None, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload).encode("utf-8")

    def json(self):
        return self._payload


def _configure(monkeypatch: pytest.MonkeyPatch, *, base: str = "https://www.yuque.com") -> None:
    monkeypatch.setenv("XCAGI_YUQUE_TOKEN", "token-123")
    monkeypatch.setenv("XCAGI_YUQUE_BASE_URL", base)


def test_fetch_document_reads_markdown_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    calls: list[tuple[str, dict]] = []

    def _getter(url: str, **kwargs):
        calls.append((url, kwargs))
        return _Response(
            {"data": {"title": "退款规则", "body": "七天内可以退款。", "slug": "refund"}}
        )

    doc = fetch_document("team/docs/refund", getter=_getter)

    assert doc.text == "# 退款规则\n\n七天内可以退款。"
    assert doc.title == "退款规则"
    assert doc.url == "https://www.yuque.com/team/docs/refund"
    assert calls[0][0] == "https://www.yuque.com/api/v2/repos/team/docs/docs/refund"
    assert calls[0][1]["headers"]["X-Auth-Token"] == "token-123"


def test_fetch_document_falls_back_to_html(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def _getter(_url: str, **_kwargs):
        return _Response(
            {"data": {"title": "权限", "body": "", "body_html": "<p>仅管理员<b>可编辑</b></p>"}}
        )

    doc = fetch_document("team/docs/permissions", getter=_getter)

    assert "仅管理员" in doc.text
    assert "可编辑" in doc.text


def test_fetch_document_rejects_bad_ref_and_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_YUQUE_TOKEN", "token-123")
    with pytest.raises(ValueError, match="引用不合法"):
        fetch_document("only-two-parts/doc", getter=lambda *_a, **_k: _Response())

    monkeypatch.delenv("XCAGI_YUQUE_TOKEN")
    with pytest.raises(ValueError, match="XCAGI_YUQUE_TOKEN"):
        fetch_document("team/docs/refund", getter=lambda *_a, **_k: _Response())


def test_fetch_document_maps_auth_and_missing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    with pytest.raises(ValueError, match="鉴权失败"):
        fetch_document("team/docs/refund", getter=lambda *_a, **_k: _Response(status_code=401))
    with pytest.raises(ValueError, match="不存在"):
        fetch_document("team/docs/refund", getter=lambda *_a, **_k: _Response(status_code=404))
    with pytest.raises(ValueError, match="没有可导入"):
        fetch_document(
            "team/docs/refund", getter=lambda *_a, **_k: _Response({"data": {"title": "空"}})
        )


def test_ingest_route_records_yuque_coordinates() -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    doc = SimpleNamespace(
        text="# 退款规则\n\n七天内可以退款。",
        title="退款规则",
        url="https://www.yuque.com/team/docs/refund",
    )
    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("app.application.document_parsing.yuque.fetch_document", return_value=doc):
        response = client.post(
            "/datasets/kb/documents",
            json={"yuque_document_ref": "team/docs/refund", "tenant_id": "t1"},
        )
    rejected = client.post(
        "/datasets/kb/documents",
        json={"yuque_document_ref": "team/docs/refund", "text": "重复来源"},
    )

    assert response.status_code == 200
    params = calls[0]["params"]
    assert params["text"].startswith("# 退款规则")
    assert params["metadata"]["source_kind"] == "yuque"
    assert params["metadata"]["source_ref"] == "team/docs/refund"
    assert params["metadata"]["yuque_document_ref"] == "team/docs/refund"
    assert rejected.status_code == 422


def test_refresh_reuses_yuque_connector(tmp_path) -> None:
    service = DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    context = DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )
    ingested = service.ingest_document(
        dataset_id="kb",
        source="语雀页面",
        text="七天内可以退款。",
        tenant_id="t1",
        metadata={"source_kind": "yuque", "source_ref": "team/docs/refund"},
        access_context=context,
    )
    refreshed = SimpleNamespace(
        text="# 退款规则\n\n十五天内可以退款。",
        title="退款规则",
        url="https://www.yuque.com/team/docs/refund",
    )

    with patch("app.application.document_parsing.yuque.fetch_document", return_value=refreshed):
        result = service.refresh_document(
            "kb",
            ingested["document"]["document_id"],
            tenant_id="t1",
            access_context=context,
        )

    assert result["changed"] is True
    assert result["source_kind"] == "yuque"
    assert result["document"]["metadata"]["yuque_document_ref"] == "team/docs/refund"
    assert result["document"]["version"] == 2
