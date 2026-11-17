"""知识库语义能力与精排的单元测试。"""

from __future__ import annotations

import pytest

from app.application.dataset_rag.retrieval_policy import (
    _rerank_chunks,
    _semantic_rerank_chunks,
)
from app.application.dataset_rag.vector_index import _semantic_embedding_available
from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.rag import RetrievedChunk


def _chunk(text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(text=text, score=score, source="doc", chunk_index=0)


def _semantic_mode(monkeypatch, mode: str) -> None:
    service = EmbeddingService(mode=mode)
    monkeypatch.setattr(
        "app.infrastructure.llm.embedding_service.get_default_embedding_service",
        lambda: service,
    )


def test_hash_mode_is_not_reported_as_semantic(monkeypatch):
    _semantic_mode(monkeypatch, "hash")
    assert _semantic_embedding_available(0) is False
    # 旧数据里的向量计数不能把 hash 洗成语义
    assert _semantic_embedding_available(12) is False


@pytest.mark.parametrize("mode", ["fastembed", "local", "remote"])
def test_semantic_modes_are_reported(monkeypatch, mode):
    _semantic_mode(monkeypatch, mode)
    assert _semantic_embedding_available(0) is True


def test_semantic_rerank_uses_model_scores(monkeypatch):
    class FakeReranker:
        def score(self, query: str, passages: list[str]) -> list[float]:
            return [0.1, 0.9]

    monkeypatch.setattr(
        "app.infrastructure.rag.reranker.get_default_reranker", lambda: FakeReranker()
    )
    chunks = [_chunk("退货", 0.9), _chunk("退款七天内可申请", 0.2)]
    top = _semantic_rerank_chunks("退款多久到账", chunks, top_k=1)
    assert top is not None
    assert top[0].text == "退款七天内可申请"
    assert top[0].score == pytest.approx(0.9)
    assert top[0].source.endswith("+rerank")


def test_semantic_rerank_falls_back_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.rag.reranker.get_default_reranker", lambda: None
    )
    chunks = [_chunk("a", 0.5)]
    assert _semantic_rerank_chunks("a", chunks, top_k=1) is None


def test_semantic_rerank_rejects_partial_scores(monkeypatch):
    class BadReranker:
        def score(self, query: str, passages: list[str]) -> list[float]:
            return [0.5]

    monkeypatch.setattr(
        "app.infrastructure.rag.reranker.get_default_reranker", lambda: BadReranker()
    )
    chunks = [_chunk("a", 0.5), _chunk("b", 0.4)]
    assert _semantic_rerank_chunks("q", chunks, top_k=1) is None


def test_lexical_rerank_still_available():
    chunks = [_chunk("无关内容", 0.9), _chunk("退款政策说明", 0.1)]
    top = _rerank_chunks("退款政策", chunks, top_k=1)
    assert top[0].text == "退款政策说明"
