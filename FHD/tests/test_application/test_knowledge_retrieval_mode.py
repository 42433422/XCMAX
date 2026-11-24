"""检索模式（hybrid / vector / keyword）：仅关键词、仅向量、默认混合。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes.knowledge.schemas import DatasetQueryRequest
from app.infrastructure.rag import RetrievedChunk
from app.infrastructure.rag.hybrid_retriever import HybridRetriever
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


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
        RetrievedChunk(text="退款流程需要审核退款申请。", score=0.0, chunk_index=0),
        RetrievedChunk(text="桌面安装指南与首次登录。", score=0.0, chunk_index=1),
    ]


def test_keyword_mode_returns_only_lexical_hits() -> None:
    retriever = HybridRetriever(embedder=None, top_k=2, mode="keyword")
    retriever.index(_chunks())

    hits = retriever.retrieve("退款")

    assert [hit.chunk_index for hit in hits] == [0]
    assert hits[0].source == "bm25"


def test_vector_mode_has_no_keyword_lane() -> None:
    retriever = HybridRetriever(embedder=None, top_k=2, mode="vector")
    retriever.index(_chunks())

    # embedder=None 时没有向量，只有关键词也能命中的文本不应被返回。
    assert retriever.retrieve("退款") == []


def test_invalid_mode_falls_back_to_hybrid() -> None:
    retriever = HybridRetriever(embedder=None, top_k=2, mode="unknown")
    retriever.index(_chunks())

    assert retriever.retrieve("退款")


def test_schema_accepts_modes_and_rejects_unknown() -> None:
    assert DatasetQueryRequest(query="退款", retrieval_mode="keyword").retrieval_mode == "keyword"
    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="退款", retrieval_mode="semantic")


def test_query_keyword_mode_skips_unrelated_documents(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text="退款流程需要审核退款申请。",
        tenant_id="t1",
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb",
        source="安装.md",
        text="桌面安装指南与首次登录。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    result = service.query(
        dataset_id="kb",
        query="退款",
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
        retrieval_mode="keyword",
    )

    sources = {(row.get("metadata") or {}).get("source") for row in result["chunks"]}
    assert sources == {"退款.md"}


def test_channel_weights_rebalance_rrf() -> None:
    semantic = RetrievedChunk(text="alpha semantic passage", score=0.0, chunk_index=0)
    lexical = RetrievedChunk(text="target token passage", score=0.0, chunk_index=1)

    def embedder(text: str) -> list[float]:
        return [1.0, 0.0] if "alpha" in text or text == "target" else [0.0, 1.0]

    def ranked(**kwargs) -> list[int]:
        retriever = HybridRetriever(embedder=embedder, top_k=2, **kwargs)
        retriever.index([semantic, lexical])
        return [hit.chunk_index for hit in retriever.retrieve("target")]

    assert ranked()[0] == 0  # 默认等权：向量通道先计入，平票时靠前
    assert ranked(vector_weight=0.0)[0] == 1  # 只看关键词
    assert ranked(keyword_weight=0.0)[0] == 0  # 只看向量
    assert ranked(vector_weight=-1.0)[0] == 0  # 非法权重回落默认 1.0


def test_schema_bounds_channel_weights() -> None:
    assert DatasetQueryRequest(query="退款", keyword_weight=2.5).keyword_weight == 2.5
    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="退款", vector_weight=11.0)
    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="退款", keyword_weight=-0.5)


def test_dispatcher_passes_retrieval_mode(trusted_actor) -> None:
    from app.domain.shared_services.tools_workflow_memory_rag import (
        _registered_router_dataset_rag,
    )

    actor = trusted_actor(permissions=["dataset.read"])
    with patch("app.application.dataset_rag_app_service.get_dataset_rag_app_service") as mock_get:
        mock_get.return_value.query.return_value = {"success": True, "chunks": []}
        _registered_router_dataset_rag(
            "query",
            {
                "dataset_id": "ds1",
                "query": "退款",
                "include_answer": "false",
                "retrieval_mode": "keyword",
                "vector_weight": 2.5,
                "keyword_weight": 0.5,
            },
            actor.context,
            "admin",
            "",
        )

    assert mock_get.return_value.query.call_args.kwargs["retrieval_mode"] == "keyword"
    assert mock_get.return_value.query.call_args.kwargs["vector_weight"] == 2.5
    assert mock_get.return_value.query.call_args.kwargs["keyword_weight"] == 0.5
