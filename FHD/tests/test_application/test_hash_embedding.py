"""hash 降级 embedding：二元组哈希、维度迁移与相似度。"""

from __future__ import annotations

from app.application.dataset_rag.models import _DatasetState
from app.application.dataset_rag.vector_index import backfill_missing_embeddings
from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.rag import RetrievedChunk


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_hash_embedding_is_deterministic_and_normalized() -> None:
    service = EmbeddingService(mode="hash")
    first = service.embed_one("退款政策七天内可申请")
    second = service.embed_one("退款政策七天内可申请")

    assert len(first) == 192
    assert first == second
    assert abs(sum(value * value for value in first) ** 0.5 - 1.0) < 1e-6


def test_hash_embedding_prefers_related_text() -> None:
    service = EmbeddingService(mode="hash")
    query = service.embed_one("退款政策")
    related = service.embed_one("退款政策：签收后七天内可申请")
    unrelated = service.embed_one("权限说明：管理员可以分配模块")

    assert _cosine(query, related) > _cosine(query, unrelated)


def test_backfill_recomputes_stale_dimension() -> None:
    state = _DatasetState("ds")
    stale = RetrievedChunk(text="退款政策", score=0.0, metadata={"_embedding": [0.1, 0.2]})
    fresh = RetrievedChunk(text="权限说明", score=0.0, metadata={"_embedding": [0.3, 0.4, 0.5]})
    state.chunks = [stale, fresh]

    changed = backfill_missing_embeddings(lambda text: [1.0, 0.0, 0.0], state)

    assert changed is True
    assert stale.metadata["_embedding"] == [1.0, 0.0, 0.0]
    assert fresh.metadata["_embedding"] == [0.3, 0.4, 0.5]


def test_backfill_keeps_matching_dimension() -> None:
    state = _DatasetState("ds")
    chunk = RetrievedChunk(text="退款政策", score=0.0, metadata={"_embedding": [0.1, 0.2]})
    state.chunks = [chunk]

    assert backfill_missing_embeddings(lambda text: [0.9, 0.1], state) is False
    assert chunk.metadata["_embedding"] == [0.1, 0.2]
