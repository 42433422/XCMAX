"""知识库标签（tags）：入库记录、检索按标签过滤、跨库过滤与参数校验。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

_REFUND = "退款政策：签收后七天内可申请退款。" * 8
_INVOICE = "发票规则：支持开具电子发票。" * 8


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService) -> None:
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text=_REFUND,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata={"tags": ["售后", "财务"]},
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb",
        source="发票.md",
        text=_INVOICE,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata={"tags": ["财务"]},
        access_context=_ctx(),
    )


def test_query_filters_by_any_requested_tag(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    after_sales = service.query(
        dataset_id="kb",
        query="退款 发票",
        top_k=5,
        tenant_id="t1",
        metadata_filter={"tags": ["售后"]},
        access_context=_ctx(),
    )
    finance = service.query(
        dataset_id="kb",
        query="退款 发票",
        top_k=5,
        tenant_id="t1",
        metadata_filter={"tags": ["财务"]},
        access_context=_ctx(),
    )

    assert {str((chunk["metadata"] or {}).get("source")) for chunk in after_sales["chunks"]} == {
        "退款.md"
    }
    assert {str((chunk["metadata"] or {}).get("source")) for chunk in finance["chunks"]} == {
        "退款.md",
        "发票.md",
    }


def test_scalar_filter_matches_multi_value_metadata(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.query(
        dataset_id="kb",
        query="退款 发票",
        top_k=5,
        tenant_id="t1",
        metadata_filter={"tags": "售后"},
        access_context=_ctx(),
    )

    assert result["chunks"]
    assert all("售后" in (chunk["metadata"] or {}).get("tags", []) for chunk in result["chunks"])


def test_untagged_documents_are_excluded_by_tag_filter(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    service.ingest_document(
        dataset_id="kb",
        source="其他.md",
        text="公司团建安排。" * 10,
        tenant_id="t1",
        chunk_strategy="fixed",
        access_context=_ctx(),
    )

    result = service.query(
        dataset_id="kb",
        query="公司团建",
        top_k=5,
        tenant_id="t1",
        metadata_filter={"tags": ["财务"]},
        access_context=_ctx(),
    )

    assert all((chunk["metadata"] or {}).get("source") != "其他.md" for chunk in result["chunks"])


def test_multi_query_applies_tags_to_each_dataset(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    service.ingest_document(
        dataset_id="kb-2",
        source="权限.md",
        text="权限说明：管理员可以分配模块。" * 8,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata={"tags": ["权限"]},
        access_context=_ctx(),
    )

    result = service.multi_query(
        dataset_ids=["kb", "kb-2"],
        query="退款 发票 权限",
        top_k=5,
        tenant_id="t1",
        metadata_filter={"tags": ["财务"]},
        access_context=_ctx(),
    )

    sources = {str((chunk["metadata"] or {}).get("source")) for chunk in result["chunks"]}
    assert "权限.md" not in sources
    assert {"退款.md", "发票.md"} <= sources


def test_routes_record_tags_and_forward_query_filter() -> None:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    ingested = client.post(
        "/datasets/kb/documents",
        json={"text": "退款政策七天内。", "tags": [" 售后 ", "售后", "财务"]},
    )
    queried = client.post(
        "/datasets/kb/query",
        json={"query": "退款", "tags": ["售后"]},
    )
    too_many = client.post(
        "/datasets/kb/query",
        json={"query": "退款", "tags": [f"t{index}" for index in range(21)]},
    )
    too_long = client.post(
        "/datasets/kb/documents",
        json={"text": "退款", "tags": ["x" * 40]},
    )

    assert ingested.status_code == 200
    assert calls[0]["params"]["metadata"]["tags"] == ["售后", "财务"]
    assert queried.status_code == 200
    assert calls[1]["params"]["tags"] == ["售后"]
    assert too_many.status_code == 422
    assert too_long.status_code == 422
