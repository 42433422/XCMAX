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


def _seed(
    service: DatasetRagApplicationService,
    *,
    acl: dict | None = None,
    source: str = "退款.md",
    allow_duplicate: bool = False,
) -> str:
    metadata: dict[str, object] = {
        "source_kind": "url",
        "source_ref": f"https://docs.example.com/{source}",
        "chunk_strategy": "fixed",
        "chunk_size": 120,
        "chunk_overlap": 0,
    }
    if acl:
        metadata["acl"] = acl
    result = service.ingest_document(
        dataset_id="kb",
        source=source,
        text=_ORIGINAL,
        tenant_id="t1",
        metadata=metadata,
        allow_duplicate=allow_duplicate,
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


def test_batch_refresh_summarizes_changed_unchanged_and_skipped(tmp_path) -> None:
    service = _service(tmp_path)
    changed_doc = _seed(service)
    unchanged = service.ingest_document(
        dataset_id="kb",
        source="发票.md",
        text=_ORIGINAL,
        tenant_id="t1",
        metadata={"source_kind": "url", "source_ref": "https://docs.example.com/invoice"},
        allow_duplicate=True,
        access_context=_ctx(),
    )
    inline = service.ingest_document(
        dataset_id="kb",
        source="内联.md",
        text="内联说明：没有外部来源坐标。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    def _fetch(url: str) -> SimpleNamespace:
        text = _UPDATED if url.endswith("退款.md") else _ORIGINAL
        return SimpleNamespace(text=text, title="页面", url=url)

    with patch("app.application.document_parsing.web_fetch.fetch_url_text", side_effect=_fetch):
        result = service.refresh_documents("kb", tenant_id="t1", access_context=_ctx())

    assert result["success"] is True
    assert result["total"] == 2
    assert result["changed"] == 1
    assert result["unchanged"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 1
    assert result["truncated"] is False
    statuses = {item["document_id"]: item["status"] for item in result["documents"]}
    assert statuses[changed_doc] == "changed"
    assert statuses[unchanged["document"]["document_id"]] == "unchanged"
    assert inline["document"]["document_id"] not in statuses


def test_batch_refresh_respects_limit_and_acl(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    _seed(service, acl={"allow_actors": ["alice"]}, source="秘密.md", allow_duplicate=True)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        limited = service.refresh_documents("kb", tenant_id="t1", access_context=_ctx(), limit=1)
        hidden = service.refresh_documents(
            "kb", tenant_id="t1", access_context=_ctx("bob"), limit=50
        )

    assert limited["processed"] == 1
    assert limited["truncated"] is True
    # bob 看不到 ACL 受限的「秘密.md」，只同步租户内可见文档。
    assert hidden["total"] == 1
    assert [item["source"] for item in hidden["documents"]] == ["退款.md"]


def test_batch_refresh_route_dispatches() -> None:
    from fastapi.responses import JSONResponse

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/documents/refresh?limit=500")

    assert response.status_code == 200
    assert calls[0]["action"] == "refresh_documents"
    assert calls[0]["params"] == {"dataset_id": "kb", "limit": 200, "max_age_hours": 0.0}


def test_batch_refresh_route_passes_max_age_hours() -> None:
    from fastapi.responses import JSONResponse

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/documents/refresh?max_age_hours=24")

    assert response.status_code == 200
    assert calls[0]["params"]["max_age_hours"] == 24.0


def test_refresh_records_last_source_sync_at(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx())

    state = service._repository.datasets["kb"]
    metadata = state.documents[document_id].metadata
    assert metadata["last_source_sync_at"]


def test_batch_refresh_skips_sources_synced_within_max_age(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _seed(service)

    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        first = service.refresh_documents(
            "kb", tenant_id="t1", access_context=_ctx(), max_age_hours=24
        )
        second = service.refresh_documents(
            "kb", tenant_id="t1", access_context=_ctx(), max_age_hours=24
        )

    assert first["processed"] == 1
    assert first["fresh"] == 0
    assert second["processed"] == 0
    assert second["fresh"] == 1

    state = service._repository.datasets["kb"]
    state.documents[document_id].metadata["last_source_sync_at"] = "2020-01-01T00:00:00Z"
    with patch(
        "app.application.document_parsing.web_fetch.fetch_url_text",
        return_value=_page(_ORIGINAL),
    ):
        third = service.refresh_documents(
            "kb", tenant_id="t1", access_context=_ctx(), max_age_hours=24
        )
    assert third["processed"] == 1
    assert third["unchanged"] == 1


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
        result = service.refresh_document("kb", document_id, tenant_id="t1", access_context=_ctx())

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
