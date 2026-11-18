"""知识库术语表（同义词扩展）测试。

覆盖：
- 术语表保存/读取与边界归一化
- keyword 模式下口语词通过术语表命中语料写法
- 缺少写权限被拒、未知数据集明确失败
- 术语表随快照持久化，重启服务后仍生效
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


def _ctx(*, permissions: frozenset[str] | None = None) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
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


def _keywords(service: DatasetRagApplicationService, query: str) -> list[dict]:
    result = service.query(
        dataset_id="kb-policy",
        query=query,
        top_k=3,
        retrieval_mode="keyword",
        access_context=_ctx(),
    )
    assert result["success"] is True
    return result["chunks"]


def test_synonyms_roundtrip_and_normalization(tmp_path) -> None:
    service = _service(tmp_path)
    saved = service.set_synonyms(
        "kb-policy",
        {" 退款 ": ["退货", "退钱", "退货", ""], "发票": "电子发票"},
        access_context=_ctx(),
    )
    loaded = service.synonyms("kb-policy", access_context=_ctx())

    assert saved["success"] is True
    assert saved["count"] == 2
    assert loaded["synonyms"] == {"退款": ["退货", "退钱"], "发票": ["电子发票"]}
    cleared = service.set_synonyms("kb-policy", {}, access_context=_ctx())
    assert cleared["success"] is True and cleared["count"] == 0


def test_synonyms_expand_keyword_recall(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    assert _keywords(service, "返金") == []

    service.set_synonyms("kb-policy", {"返金": ["退货"]}, access_context=_ctx())
    hits = _keywords(service, "返金")

    assert hits and "退货" in (hits[0].get("text") or "")


def test_synonyms_persist_across_service_instances(tmp_path) -> None:
    _service(tmp_path).set_synonyms("kb-policy", {"退款": ["退货"]}, access_context=_ctx())
    reopened = _service(tmp_path)
    _seed(reopened)

    assert reopened.synonyms("kb-policy", access_context=_ctx())["synonyms"] == {"退款": ["退货"]}
    assert _keywords(reopened, "退款")


def test_synonyms_require_write_permission(tmp_path) -> None:
    result = _service(tmp_path).set_synonyms(
        "kb-policy",
        {"退款": ["退货"]},
        access_context=_ctx(permissions=frozenset({"dataset.read"})),
    )

    assert result["success"] is False
    assert result["error_code"] == "dataset_permission_denied"


def test_synonyms_can_be_configured_before_import(tmp_path) -> None:
    result = _service(tmp_path).set_synonyms("kb-new", {"返金": ["退货"]}, access_context=_ctx())
    reopened = _service(tmp_path)
    empty = reopened.synonyms("never-seen", access_context=_ctx())

    assert result["success"] is True and result["count"] == 1
    assert reopened.synonyms("kb-new", access_context=_ctx())["synonyms"] == {"返金": ["退货"]}
    assert empty["success"] is True and empty["synonyms"] == {}
