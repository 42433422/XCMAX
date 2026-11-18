"""知识库导出/导入（备份迁移）测试。

覆盖：
- 导出快照包含文档、分块、术语表，且不泄露内部字段（`_embedding`）
- 导入到新数据集后可正常检索，术语表随快照恢复
- 租户隔离：导出只包含本租户文档
- 非空数据集需显式 overwrite；导入强制使用操作者租户
- 缺少写权限被拒
"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_REFUND = "退货政策：签收后七天内可以申请无理由退货，审核通过后原路退回。" * 6


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(tenant: str = "t1", *, permissions: frozenset[str] | None = None) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id=tenant,
        permissions=(
            frozenset({"dataset.read", "dataset.write"}) if permissions is None else permissions
        ),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService, *, tenant: str = "t1") -> None:
    service.ingest_document(
        dataset_id="kb-src",
        source="退货.md",
        text=_REFUND,
        tenant_id=tenant,
        chunk_strategy="fixed",
        access_context=_ctx(tenant),
    )
    service.set_synonyms("kb-src", {"返金": ["退货"]}, access_context=_ctx(tenant))


def test_export_import_roundtrip_restores_search(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    exported = service.export_dataset("kb-src", access_context=_ctx())
    restored = service.import_dataset("kb-dst", exported, access_context=_ctx())
    result = service.query(
        dataset_id="kb-dst",
        query="返金",
        top_k=3,
        retrieval_mode="keyword",
        access_context=_ctx(),
    )

    assert exported["success"] is True
    assert exported["document_count"] == 1 and exported["chunk_count"] >= 1
    assert all("_embedding" not in chunk["metadata"] for chunk in exported["chunks"])
    assert restored["success"] is True
    assert restored["document_count"] == 1 and restored["synonym_count"] == 1
    assert result["success"] is True and result["chunks"]
    assert service.synonyms("kb-dst", access_context=_ctx())["synonyms"] == {"返金": ["退货"]}


def test_export_is_tenant_scoped(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service, tenant="t1")
    _seed(service, tenant="t2")

    exported = service.export_dataset("kb-src", access_context=_ctx("t1"))

    assert exported["document_count"] == 1
    assert {row["tenant_id"] for row in exported["documents"]} == {"t1"}


def test_import_requires_empty_target_or_overwrite(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    exported = service.export_dataset("kb-src", access_context=_ctx())

    rejected = service.import_dataset("kb-src", exported, access_context=_ctx())
    replaced = service.import_dataset("kb-src", exported, overwrite=True, access_context=_ctx())

    assert rejected["success"] is False
    assert rejected["error_code"] == "dataset_not_empty"
    assert replaced["success"] is True


def test_import_forces_actor_tenant_and_requires_write(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    exported = service.export_dataset("kb-src", access_context=_ctx())
    exported["documents"][0]["tenant_id"] = "evil"
    exported["documents"][0]["metadata"]["tenant_id"] = "evil"

    imported = service.import_dataset("kb-copy", exported, access_context=_ctx("t9"))
    denied = service.import_dataset(
        "kb-deny", exported, access_context=_ctx(permissions=frozenset({"dataset.read"}))
    )

    assert imported["success"] is True
    assert imported["document_count"] == 1
    assert service.status("kb-copy", access_context=_ctx("t9"))["document_count"] == 1
    assert denied["success"] is False
    assert denied["error_code"] == "dataset_permission_denied"
