"""文档分块预览/命中测试：分页、ACL 与路由参数。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_TEXT = "分块预览内容：" + "权限与退款规则说明。" * 30


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(actor: str = "alice", *, tenant: str = "t1", admin: bool = False) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=admin,
    )


def _ingest(service: DatasetRagApplicationService, *, metadata=None, ctx=None) -> str:
    result = service.ingest_document(
        dataset_id="kb",
        source="preview.md",
        text=_TEXT,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=50,
        chunk_overlap=0,
        metadata=metadata or {},
        access_context=ctx or _ctx(),
    )
    assert result["success"] is True
    return result["document"]["document_id"]


def test_chunks_are_paginated_in_document_order(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _ingest(service)

    first = service.document_chunks("kb", document_id, offset=0, limit=2, access_context=_ctx())
    second = service.document_chunks("kb", document_id, offset=2, limit=2, access_context=_ctx())

    assert first["success"] is True
    assert first["total"] > 4
    assert [row["chunk_index"] for row in first["chunks"]] == [0, 1]
    assert [row["chunk_index"] for row in second["chunks"]] == [2, 3]
    assert first["document"]["document_id"] == document_id


def test_missing_document_or_other_tenant_is_not_found(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _ingest(service)

    missing = service.document_chunks("kb", "doc_missing", access_context=_ctx())
    other_tenant = service.document_chunks("kb", document_id, access_context=_ctx(tenant="t2"))

    assert missing["error_code"] == "dataset_document_not_found"
    assert other_tenant["error_code"] == "dataset_document_not_found"


def test_acl_restricted_chunks_hidden_from_other_actors(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = _ingest(service, metadata={"acl": {"allow_actors": ["alice"]}}, ctx=_ctx("alice"))

    allowed = service.document_chunks("kb", document_id, access_context=_ctx("alice"))
    denied = service.document_chunks("kb", document_id, access_context=_ctx("bob"))
    admin = service.document_chunks("kb", document_id, access_context=_ctx("root", admin=True))

    assert allowed["success"] is True and allowed["chunks"]
    assert denied["error_code"] == "dataset_document_not_found"
    assert admin["success"] is True and admin["chunks"]


def test_route_passes_pagination_to_views() -> None:
    from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes

    seen: dict = {}
    views = type(
        "Views",
        (),
        {
            "document_chunks": lambda self, dataset_id, document_id, request, **kwargs: (
                seen.update(
                    {
                        "dataset_id": dataset_id,
                        "document_id": document_id,
                        "kwargs": kwargs,
                    }
                )
                or {"success": True}
            )
        },
    )()
    routes = DatasetViewRoutes(views=lambda: views)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.get("/datasets/kb/documents/doc_1/chunks?offset=4&limit=10")

    assert response.status_code == 200
    assert seen == {
        "dataset_id": "kb",
        "document_id": "doc_1",
        "kwargs": {"offset": 4, "limit": 10},
    }


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_route_rejects_out_of_range(query: str) -> None:
    from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes

    views = type("Views", (), {"document_chunks": lambda *_a, **_k: {"success": True}})()
    app = FastAPI()
    app.include_router(DatasetViewRoutes(views=lambda: views).router)
    client = TestClient(app)

    assert client.get(f"/datasets/kb/documents/doc_1/chunks?{query}").status_code == 422
