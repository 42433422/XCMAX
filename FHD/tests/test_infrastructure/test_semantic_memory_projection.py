from __future__ import annotations

from unittest.mock import MagicMock

from app.infrastructure.memory.semantic_projection import query_semantic_projection
from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore


def test_semantic_projection_migrates_scoped_legacy_rows_and_reuses_cache(tmp_path, monkeypatch):
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "legacy.sqlite"))
    for owner in ("owner1", "owner2"):
        store.create_or_update_index(owner, owner)
        store.upsert_chunks(
            owner,
            [
                {
                    "chunk_id": owner + "-a",
                    "content": owner + " original",
                    "embedding": [1.0] + [0.0] * 255,
                    "metadata": {"source_owner_id": owner, "source_memory_id": owner},
                }
            ],
        )
    embedder = MagicMock()
    embedder.mode = "fastembed"
    embedder.embedding_fingerprint = "model-A"
    embedder.dim.return_value = 3
    embedder.embed_query.return_value = [1.0, 0.0, 0.0]
    embedder.embed_texts.return_value = [[1.0, 0.0, 0.0]]
    monkeypatch.setattr(
        "app.infrastructure.memory.semantic_projection.get_default_embedding_service",
        lambda: embedder,
    )

    def query():
        return query_semantic_projection(
            store, "owner1", "query", cutoff=0, governed_only=True, limit=10, top_k=2
        )

    assert [row["chunk_id"] for row in query()] == ["owner1-a"]
    assert [row["chunk_id"] for row in query()] == ["owner1-a"]
    embedder.embed_texts.assert_called_once_with(["owner1 original"])
    embedder.embedding_fingerprint = "model-B"
    assert query()
    assert embedder.embed_texts.call_count == 2
    assert store.delete_source(index_id="owner1", source_memory_id="owner1") == 1
    assert query() == []
    assert store.semantic_snapshot("owner1", "model-A", 0, True, 10) == []


def test_semantic_projection_fails_closed_on_incompatible_dimensions(tmp_path, monkeypatch):
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "legacy.sqlite"))
    embedder = MagicMock()
    embedder.mode = "fastembed"
    embedder.dim.return_value = 3
    embedder.embed_query.return_value = [1.0, 0.0]
    monkeypatch.setattr(
        "app.infrastructure.memory.semantic_projection.get_default_embedding_service",
        lambda: embedder,
    )
    assert (
        query_semantic_projection(
            store, "owner1", "query", cutoff=0, governed_only=True, limit=10, top_k=2
        )
        is None
    )
