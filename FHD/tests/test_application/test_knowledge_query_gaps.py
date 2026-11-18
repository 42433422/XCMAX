"""知识库知识缺口（未命中问题）记录测试。

覆盖：
- 空结果记录并按问题合并计数
- 命中问题不记录
- 租户隔离与清理
- 权限：读取需 dataset.read，清理需 dataset.write
"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_POLICY = "退货政策：签收后七天内可以申请无理由退货，审核通过后原路退回。" * 6


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


def _seed(service: DatasetRagApplicationService) -> None:
    service.ingest_document(
        dataset_id="kb-policy",
        source="退货.md",
        text=_POLICY,
        tenant_id="t1",
        chunk_strategy="fixed",
        access_context=_ctx(),
    )


def _query(service: DatasetRagApplicationService, text: str, tenant: str = "t1") -> dict:
    return service.query(
        dataset_id="kb-policy",
        query=text,
        top_k=3,
        retrieval_mode="keyword",
        access_context=_ctx(tenant),
    )


def test_empty_result_records_and_merges_gap(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    _query(service, "报价单模板")
    _query(service, "  报价单模板  ")

    gaps = service.query_gaps("kb-policy", access_context=_ctx())

    assert gaps["success"] is True
    assert gaps["total"] == 1
    assert gaps["gaps"][0]["query"] == "报价单模板"
    assert gaps["gaps"][0]["count"] == 2


def test_hit_does_not_record_gap(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    _query(service, "退货")

    assert service.query_gaps("kb-policy", access_context=_ctx())["total"] == 0


def test_gaps_are_tenant_scoped_and_clearable(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    _query(service, "报价单模板", tenant="t1")
    _query(service, "发票模板", tenant="t2")

    t1 = service.query_gaps("kb-policy", access_context=_ctx("t1"))
    t2 = service.query_gaps("kb-policy", access_context=_ctx("t2"))
    cleared = service.clear_query_gaps("kb-policy", access_context=_ctx("t1"))

    assert [row["query"] for row in t1["gaps"]] == ["报价单模板"]
    assert [row["query"] for row in t2["gaps"]] == ["发票模板"]
    assert cleared["removed"] == 1
    assert service.query_gaps("kb-policy", access_context=_ctx("t1"))["total"] == 0
    assert service.query_gaps("kb-policy", access_context=_ctx("t2"))["total"] == 1


def test_gap_permissions(tmp_path) -> None:
    service = _service(tmp_path)
    denied_read = service.query_gaps("kb-policy", access_context=_ctx(permissions=frozenset()))
    denied_clear = service.clear_query_gaps(
        "kb-policy", access_context=_ctx(permissions=frozenset({"dataset.read"}))
    )

    assert denied_read["success"] is False
    assert denied_read["error_code"] == "dataset_permission_denied"
    assert denied_clear["success"] is False
    assert denied_clear["error_code"] == "dataset_permission_denied"
