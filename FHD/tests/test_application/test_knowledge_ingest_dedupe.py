"""入库内容去重（护栏）：跨来源相同正文复用已有文档，可显式关闭。"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService


def _ctx(tenant: str = "t1", *, actor: str = "alice") -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _doc_count(service: DatasetRagApplicationService) -> int:
    state = service._repository.datasets["kb"]
    return len(state.documents)


def test_identical_content_from_another_source_is_reused(tmp_path) -> None:
    service = _service(tmp_path)
    first = service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )
    second = service.ingest_document(
        dataset_id="kb",
        source="mirror.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert second["success"] is True
    assert second["duplicate"] is True
    assert second["duplicate_of"] == first["document"]["document_id"]
    assert _doc_count(service) == 1


def test_allow_duplicate_stores_a_second_copy(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )
    second = service.ingest_document(
        dataset_id="kb",
        source="mirror.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        allow_duplicate=True,
        access_context=_ctx(),
    )

    assert "duplicate" not in second
    assert _doc_count(service) == 2


def test_same_content_in_another_tenant_is_not_deduped(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx("t1"),
    )
    second = service.ingest_document(
        dataset_id="kb",
        source="mirror.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t2",
        access_context=_ctx("t2", actor="bob"),
    )

    assert "duplicate" not in second
    assert _doc_count(service) == 2


def test_explicit_document_id_bypasses_dedupe(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )
    second = service.ingest_document(
        dataset_id="kb",
        source="mirror.md",
        document_id="doc_explicit",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert "duplicate" not in second
    assert _doc_count(service) == 2


def test_same_source_still_versions_instead_of_deduping(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )
    second = service.ingest_document(
        dataset_id="kb",
        source="handbook.md",
        text="退款政策：签收后七天内可申请无理由退款。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert "duplicate" not in second
    assert second["document"]["version"] == 2
    assert _doc_count(service) == 2
