"""引用回链测试：回答中的引用必须能定位到原文文档与字符区间。"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_TEXT = "退款政策：签收后七天内可以申请退款，审核通过后原路退回。" * 6


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def test_answer_citations_carry_document_identity(tmp_path) -> None:
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
        document_id="doc-refund",
        chunk_strategy="fixed",
        access_context=_ctx(),
    )

    result = service.answer(
        dataset_id="kb-refund",
        query="退款政策",
        top_k=3,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=lambda _question, _prompt: "签收后七天内可退款 [1]。",
    )

    citation = result["citations"][0]
    assert citation["document_id"] == "doc-refund"
    assert citation["source_url"] == "退款.md"
    assert isinstance(citation["char_range"], list) and len(citation["char_range"]) == 2
    assert citation["char_range"][0] <= citation["char_range"][1]
