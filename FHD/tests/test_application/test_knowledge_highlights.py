"""检索命中高亮区间测试。"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag.retrieval_policy import highlight_spans
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_TEXT = "退款政策：签收后七天内可以申请退款，审核通过后原路退回。" * 6


def test_highlight_spans_merge_cjk_bigrams() -> None:
    text = "签收后七天内可以申请退款"
    spans = highlight_spans(text, "退款")

    assert spans
    assert all(0 <= span["start"] < span["end"] <= len(text) for span in spans)
    assert any(text[span["start"] : span["end"]] == "退款" for span in spans)


def test_highlight_spans_match_ascii_case_insensitively() -> None:
    text = "The Refund Policy applies."
    spans = highlight_spans(text, "refund policy")

    assert [text[span["start"] : span["end"]] for span in spans] == ["Refund", "Policy"]


def test_highlight_spans_empty_without_shared_terms() -> None:
    assert highlight_spans("发票规则", "退款流程") == []


def test_query_results_carry_highlight_ranges(tmp_path) -> None:
    service = DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    service.ingest_document(
        dataset_id="kb-refund",
        source="退款.md",
        text=_TEXT,
        tenant_id="t1",
        chunk_strategy="fixed",
        access_context=DatasetAccessContext(
            actor_id="alice",
            tenant_id="t1",
            permissions=frozenset({"dataset.read", "dataset.write"}),
            is_admin=False,
        ),
    )

    result = service.query(
        dataset_id="kb-refund",
        query="退款",
        top_k=3,
        tenant_id="t1",
        retrieval_mode="keyword",
        access_context=DatasetAccessContext(
            actor_id="alice",
            tenant_id="t1",
            permissions=frozenset({"dataset.read", "dataset.write"}),
            is_admin=False,
        ),
    )

    chunk = result["chunks"][0]
    spans = chunk["metadata"]["highlights"]
    assert spans
    assert all(0 <= span["start"] < span["end"] <= len(chunk["text"]) for span in spans)
    assert any(chunk["text"][span["start"] : span["end"]] == "退款" for span in spans)
