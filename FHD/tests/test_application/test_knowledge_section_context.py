"""章节父块扩展（small-to-big）：同章节片段合并、跨章节隔离、预算与透传。"""

from __future__ import annotations

from unittest.mock import patch

from app.application.dataset_rag.chunk_context import section_context
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.rag import RetrievedChunk


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
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


def _chunk(text: str, *, section: str, index: int, start: int, version: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        score=0.0,
        chunk_index=index,
        char_start=start,
        char_end=start + len(text),
        metadata={"document_id": "doc1", "document_version": version, "section": section},
    )


def test_section_context_merges_same_section_only() -> None:
    first = _chunk("退款申请需要审核。", section="退款", index=0, start=0)
    second = _chunk("审核通过后原路退回。", section="退款", index=1, start=20)
    other = _chunk("发票需要税号。", section="发票", index=2, start=40)

    expanded = section_context(second, [first, second, other])

    assert expanded == "退款申请需要审核。\n审核通过后原路退回。"
    assert "发票" not in expanded


def test_section_context_without_section_returns_own_text() -> None:
    chunk = _chunk("无标题段落。", section="", index=0, start=0)

    assert section_context(chunk, [chunk]) == "无标题段落。"


def test_section_context_respects_budget() -> None:
    chunks = [
        _chunk("片段" * 30, section="退款", index=index, start=index * 100) for index in range(5)
    ]

    expanded = section_context(chunks[2], chunks, max_chars=200)

    assert len(expanded) <= 200
    assert chunks[2].text in expanded


def test_query_expand_section_returns_section_body(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款政策.md",
        text=(
            "## 退款\n退款申请需要审核退款金额并核对订单信息是否完整。\n"
            "审核通过后原路退回，三到五个工作日到账。\n"
        ),
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=40,
        chunk_overlap=0,
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb",
        source="发票.md",
        text="## 发票\n发票需要客户提供税号和开户行。\n",
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=40,
        chunk_overlap=0,
        access_context=_ctx(),
    )

    result = service.query(
        dataset_id="kb",
        query="退款",
        top_k=3,
        tenant_id="t1",
        access_context=_ctx(),
        expand_section=True,
    )

    contexts = [
        (row.get("metadata") or {}).get("context")
        for row in result["chunks"]
        if (row.get("metadata") or {}).get("context_mode") == "section"
    ]
    assert contexts
    assert any("三到五个工作日" in str(text) for text in contexts)
    assert all("税号" not in str(text) for text in contexts)


def test_dispatcher_passes_expand_section() -> None:
    from app.domain.shared_services.tools_workflow_memory_rag import (
        _registered_router_dataset_rag,
    )

    with patch("app.application.dataset_rag_app_service.get_dataset_rag_app_service") as mock_get:
        mock_get.return_value.query.return_value = {"success": True, "chunks": []}
        _registered_router_dataset_rag(
            "query",
            {
                "dataset_id": "ds1",
                "query": "退款",
                "include_answer": "false",
                "expand_section": "true",
            },
            {},
            "admin",
            "",
        )

    assert mock_get.return_value.query.call_args.kwargs["expand_section"] is True
