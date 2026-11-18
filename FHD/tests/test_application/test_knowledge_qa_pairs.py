"""知识库问答对（FAQ 模式）测试。

覆盖：
- 列表 / CSV / JSON 归一化与去重、非法输入
- 问答对写入、覆盖与按租户隔离
- 问答对参与检索：问题命中、答案作为证据、元数据可追溯
- 删除只影响当前租户
- 随数据集快照持久化
- 导出/导入携带问答对
"""

from __future__ import annotations

import pytest

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag.qa_pairs import normalize_qa_pairs
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_PAIRS = [
    {"question": "退款多久到账？", "answer": "审核通过后 1-3 个工作日原路退回。"},
    {"question": "如何开发票？", "answer": "在订单详情页点击「申请发票」。"},
]


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(tenant: str = "t1", *, write: bool = True) -> DatasetAccessContext:
    permissions = {"dataset.read"}
    if write:
        permissions.add("dataset.write")
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id=tenant,
        permissions=frozenset(permissions),
        is_admin=False,
    )


def _query(service: DatasetRagApplicationService, question: str, *, tenant: str = "t1") -> dict:
    return service.query(
        dataset_id="kb-faq",
        query=question,
        top_k=3,
        retrieval_mode="keyword",
        access_context=_ctx(tenant),
    )


def test_normalize_accepts_list_csv_and_json() -> None:
    assert len(normalize_qa_pairs(_PAIRS)) == 2
    assert len(normalize_qa_pairs([["问：退款？", "答：三天"], ["问：发票？", "答：订单页"]])) == 2
    csv_text = "question,answer\n退款多久到账？,1-3 个工作日\n"
    assert normalize_qa_pairs(csv_text)[0]["answer"] == "1-3 个工作日"
    tsv_text = "问题\t答案\n退款多久到账？\t1-3 个工作日\n"
    assert normalize_qa_pairs(tsv_text)[0]["question"] == "退款多久到账？"
    json_text = '[{"q": "退款多久到账？", "a": "1-3 个工作日"}]'
    assert normalize_qa_pairs(json_text)[0]["answer"] == "1-3 个工作日"
    assert normalize_qa_pairs("") == []
    assert normalize_qa_pairs(None) == []


def test_normalize_dedupes_and_rejects_unknown_shape() -> None:
    duplicated = [_PAIRS[0], dict(_PAIRS[0]), _PAIRS[1]]
    pairs = normalize_qa_pairs(duplicated)
    assert len(pairs) == 2
    assert pairs[0]["qa_id"].startswith("qa_")
    with pytest.raises(ValueError):
        normalize_qa_pairs(42)


def test_pairs_roundtrip_replace_and_append(tmp_path) -> None:
    service = _service(tmp_path)
    saved = service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx())
    assert saved["success"] is True and saved["count"] == 2

    listed = service.qa_pairs("kb-faq", tenant_id="t1", access_context=_ctx())
    assert [row["question"] for row in listed["pairs"]] == ["退款多久到账？", "如何开发票？"]

    appended = service.set_qa_pairs(
        "kb-faq",
        [{"question": "支持换货吗？", "answer": "支持，七天内。"}],
        replace=False,
        access_context=_ctx(),
    )
    assert appended["total"] == 3

    replaced = service.set_qa_pairs("kb-faq", _PAIRS[:1], access_context=_ctx())
    assert replaced["total"] == 1


def test_pairs_are_isolated_per_tenant(tmp_path) -> None:
    service = _service(tmp_path)
    service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx("t1"))
    assert service.qa_pairs("kb-faq", tenant_id="t1", access_context=_ctx("t1"))["total"] == 2
    assert service.qa_pairs("kb-faq", tenant_id="t2", access_context=_ctx("t2"))["total"] == 0
    assert _query(service, "退款多久到账？", tenant="t2")["chunks"] == []


def test_pairs_participate_in_retrieval_without_documents(tmp_path) -> None:
    service = _service(tmp_path)
    service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx())

    result = _query(service, "退款多久到账？")

    assert result["success"] is True
    assert result["chunks"], "问答对应在无文档时也能命中"
    top = result["chunks"][0]
    assert "1-3 个工作日原路退回" in top["text"]
    assert top["metadata"]["type"] == "qa"
    assert top["metadata"]["question"] == "退款多久到账？"
    assert result["grounding"] > 0.5


def test_pairs_skip_when_metadata_filter_present(tmp_path) -> None:
    service = _service(tmp_path)
    service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx())

    result = service.query(
        dataset_id="kb-faq",
        query="退款多久到账？",
        top_k=3,
        retrieval_mode="keyword",
        metadata_filter={"tag": "faq"},
        access_context=_ctx(),
    )

    assert result["success"] is True
    assert result["chunks"] == []


def test_delete_clears_only_current_tenant(tmp_path) -> None:
    service = _service(tmp_path)
    service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx("t1"))
    service.set_qa_pairs(
        "kb-faq",
        [{"question": "t2 的问题", "answer": "t2 的答案"}],
        access_context=_ctx("t2"),
    )

    removed = service.delete_qa_pairs("kb-faq", tenant_id="t1", access_context=_ctx("t1"))

    assert removed == {"success": True, "dataset_id": "kb-faq", "removed": 2}
    assert service.qa_pairs("kb-faq", tenant_id="t1", access_context=_ctx("t1"))["total"] == 0
    assert service.qa_pairs("kb-faq", tenant_id="t2", access_context=_ctx("t2"))["total"] == 1


def test_pairs_persist_across_service_instances(tmp_path) -> None:
    _service(tmp_path).set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx())
    reopened = _service(tmp_path)

    assert reopened.qa_pairs("kb-faq", tenant_id="t1", access_context=_ctx())["total"] == 2
    assert _query(reopened, "如何开发票？")["chunks"]


def test_export_import_carries_pairs(tmp_path) -> None:
    service = _service(tmp_path)
    service.set_qa_pairs("kb-faq", _PAIRS, access_context=_ctx())
    exported = service.export_dataset("kb-faq", tenant_id="t1", access_context=_ctx())
    assert exported["qa_pair_count"] == 2

    other = _service(tmp_path / "restored")
    restored = other.import_dataset(
        "kb-restored", exported, overwrite=True, access_context=_ctx("t1")
    )

    assert restored["success"] is True and restored["qa_pair_count"] == 2
    assert other.qa_pairs("kb-restored", tenant_id="t1", access_context=_ctx())["total"] == 2
