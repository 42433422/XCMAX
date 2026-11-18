"""检索多样性 MMR：单元选择、关闭保持原序、长尾拼接、HTTP 校验与分发透传。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag.retrieval_policy import mmr_rerank, resolve_mmr_lambda
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes.knowledge.schemas import DatasetQueryRequest
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


def _chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            text="退款流程需要审核退款申请并核对退款金额，退款流程说明如下。",
            score=1.0,
            chunk_index=0,
        ),
        RetrievedChunk(
            text="退款流程需要审核退款申请并核对退款金额，退款流程说明如下（重复段）。",
            score=0.99,
            chunk_index=1,
        ),
        RetrievedChunk(text="退款流程的发票开具说明。", score=0.8, chunk_index=2),
    ]


def test_mmr_prefers_diverse_result_over_near_duplicate() -> None:
    selected = mmr_rerank("退款流程", _chunks(), lambda_=0.5, top_k=2)

    assert [chunk.chunk_index for chunk in selected] == [0, 2]


def test_mmr_disabled_keeps_original_order() -> None:
    chunks = _chunks()

    assert mmr_rerank("退款流程", chunks, lambda_=0.0, top_k=2) == chunks[:2]


def test_resolve_mmr_lambda_uses_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_MMR_LAMBDA", raising=False)
    assert resolve_mmr_lambda(None) == 0.0
    assert resolve_mmr_lambda(3.0) == 1.0

    monkeypatch.setenv("XCAGI_KB_MMR_LAMBDA", "0.3")
    assert resolve_mmr_lambda(None) == 0.3


def test_schema_rejects_out_of_range_lambda() -> None:
    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="退款流程", mmr_lambda=1.5)
    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="退款流程", mmr_lambda=-0.1)

    assert DatasetQueryRequest(query="退款流程", mmr_lambda=0.5).mmr_lambda == 0.5


def test_query_returns_diverse_documents_when_enabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.application.dataset_rag.retrieval._auto_rerank_available", lambda: False
    )
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text="退款流程需要审核退款申请并核对退款金额。" * 30,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=40,
        chunk_overlap=0,
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb",
        source="发票.md",
        text="退款流程的发票开具说明。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    baseline = service.query(
        dataset_id="kb", query="退款流程", top_k=2, tenant_id="t1", access_context=_ctx()
    )["chunks"]
    diverse = service.query(
        dataset_id="kb",
        query="退款流程",
        top_k=2,
        tenant_id="t1",
        access_context=_ctx(),
        mmr_lambda=0.5,
    )["chunks"]

    assert {(row.get("metadata") or {}).get("source") for row in baseline} == {"退款.md"}
    assert {(row.get("metadata") or {}).get("source") for row in diverse} == {
        "退款.md",
        "发票.md",
    }


def test_multi_query_mmr_spans_datasets(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.application.dataset_rag.retrieval._auto_rerank_available", lambda: False
    )
    service = _service(tmp_path)
    for key in ("kb1", "kb2"):
        service.ingest_document(
            dataset_id=key,
            source="退款.md",
            text="退款流程需要审核退款申请并核对退款金额。" * 30,
            tenant_id="t1",
            chunk_strategy="fixed",
            chunk_size=40,
            chunk_overlap=0,
            access_context=_ctx(),
        )
    service.ingest_document(
        dataset_id="kb1",
        source="发票.md",
        text="退款流程的发票开具说明。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    baseline = service.multi_query(
        dataset_ids=["kb1", "kb2"], query="退款流程", top_k=2, tenant_id="t1", access_context=_ctx()
    )["chunks"]
    diverse = service.multi_query(
        dataset_ids=["kb1", "kb2"],
        query="退款流程",
        top_k=2,
        tenant_id="t1",
        access_context=_ctx(),
        mmr_lambda=0.5,
    )["chunks"]

    assert {(row.get("metadata") or {}).get("source") for row in baseline} == {"退款.md"}
    assert {(row.get("metadata") or {}).get("source") for row in diverse} == {
        "退款.md",
        "发票.md",
    }


def test_dispatcher_passes_mmr_lambda() -> None:
    from app.domain.shared_services.tools_workflow_memory_rag import (
        _registered_router_dataset_rag,
    )

    with patch("app.application.dataset_rag_app_service.get_dataset_rag_app_service") as mock_get:
        mock_get.return_value.query.return_value = {"success": True, "chunks": []}
        _registered_router_dataset_rag(
            "query",
            {
                "dataset_id": "ds1",
                "query": "退款流程",
                "include_answer": "false",
                "mmr_lambda": 0.6,
            },
            {},
            "admin",
            "",
        )

    assert mock_get.return_value.query.call_args.kwargs["mmr_lambda"] == pytest.approx(0.6)
