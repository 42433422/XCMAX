"""外部来源刷新（document refresh）测试。

覆盖：
- 来源内容未变化时不产生新版本
- 来源内容变化时生成新版本并复用原分块配置
- 无来源坐标 / 来源抓取失败 / 文档不存在 / ACL 不可见的错误分支
- HTTP 路由分发与入库时记录来源坐标
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_ORIGINAL = "退款政策：签收后七天内可以申请退款。" * 10
_UPDATED = "退款政策：签收后十五天内可以申请退款，并支持换货。" * 10


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(
    actor: str = "alice", *, permissions: frozenset[str] | None = None, tenant: str = "t1"
) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=(
            frozenset({"dataset.read", "dataset.write"}) if permissions is None else permissions
        ),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService, *, acl: dict | None = None) -> str:
    metadata: dict[str, object] = {
        "source_kind": "url",
        "source_ref": "https://docs.example.com/refund",
        "chunk_strategy": "fixed",
        "chunk_size": 120,
        "chunk_overlap": 0,
    }
    if acl:
        metadata["acl"] = acl
    result = service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text=_ORIGINAL,
        tenant_id="t1",
        metadata=metadata,
        access_context=_ctx(),
    )
    assert result["success"] is True
    return result["document"]["document_id"]


def _page(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, title="退款规则", url="https://docs.example.com/refund")


def test_refresh_returns_unchanged_without_new_version(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        result = service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx())

    assert result["success"] is True
    assert result["changed"] is False
    assert result["version"] == 1
    assert service.status("kb", tenant_id="t1", access_context=_ctx())["document_count"] == 1


def test_refresh_creates_new_version_when_content_changed(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_UPDATED),
    ):
        result = service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx())

    assert result["success"] is True
    assert result["changed"] is True
    assert result["previous_version"] == 1
    assert result["document"]["version"] == 2
    hits = service.query(
        dataset_id="kb", query="十五天内可以申请退款", tenant_id="t1", access_context=_ctx()
    )
    assert hits["chunks"]
    assert any("十五天" in str(chunk.get("text") or "") for chunk in hits["chunks"])


def test_refresh_rejects_sources_without_coordinates(tmp_path) -> None:
    service = _service(tmp_path)
    ingested = service.ingest_document(
        dataset_id="kb",
        source="inline.md",
        text=_ORIGINAL,
        tenant_id="t1",
        access_context=_ctx(),
    )

    result = service.refresh_document(
        "kb", ingested["document"]["document_id"], tenant_id="t1", access_context=_ctx()
    )

    assert result["success"] is False
    assert result["error_code"] == "dataset_refresh_unsupported"


def test_refresh_hides_documents_outside_acl(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service, acl={"allow_actors": ["alice"]})

    result = service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx("bob"))

    assert result["success"] is False
    assert result["error_code"] == "dataset_document_not_found"


def test_refresh_missing_document_and_fetch_failure(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service)

    missing = service.refresh_document("kb", "doc_missing", tenant_id="t1", access_context=_ctx())
    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        side_effect=ValueError("网页不可访问"),
    ):
        failed = service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx())

    assert missing["error_code"] == "dataset_document_not_found"
    assert failed["error_code"] == "dataset_refresh_failed"
    assert "网页不可访问" in failed["message"]


def test_refresh_reuses_connector_for_notion_sources(tmp_path) -> None:
    service = _service(tmp_path)
    ingested = service.ingest_document(
        dataset_id="kb",
        source="Notion 页面",
        text=_ORIGINAL,
        tenant_id="t1",
        metadata={"source_kind": "notion", "source_ref": "page-1"},
        access_context=_ctx(),
    )
    document_id = ingested["document"]["document_id"]
    page = SimpleNamespace(
        text=_UPDATED,
        title="Notion 页面",
        page_id="page-1",
        url="https://notion.so/page-1",
    )

    with patch("app.application.document_parsing.notion.fetch_page", return_value=page):
        result = service.refresh_document(
            "kb", document_id, tenant_id="t1", access_context=_ctx()
        )

    assert result["changed"] is True
    assert result["source_kind"] == "notion"
    assert result["document"]["metadata"]["notion_page_id"] == "page-1"
    assert result["document"]["version"] == 2


def test_refresh_route_dispatches_and_ingest_records_source_coordinates() -> None:
    from fastapi.responses import JSONResponse

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    app.include_router(routes.deletion)
    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        ingested = client.post(
            "/datasets/kb/documents",
            json={"url": "https://docs.example.com/refund", "tenant_id": "t1"},
        )
    refreshed = client.post("/datasets/kb/documents/doc_1/refresh")

    assert ingested.status_code == 200
    ingest_params = calls[0]["params"]
    assert ingest_params["metadata"]["source_kind"] == "url"
    assert ingest_params["metadata"]["source_ref"] == "https://docs.example.com/refund"
    assert ingest_params["metadata"]["chunk_strategy"] == "semantic"
    assert refreshed.status_code == 200
    assert calls[1]["action"] == "refresh_document"
    assert calls[1]["params"] == {"dataset_id": "kb", "document_id": "doc_1"}
