"""Independent sparse/dense retrieval over a synthetic local collection."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import rag_service as rag
from modstore_server import vector_engine
from modstore_server.models import KnowledgeCollection, KnowledgeMembership


@pytest.fixture
def sql_catalog(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.sqlite'}")
    KnowledgeCollection.__table__.create(engine)
    KnowledgeMembership.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        collection = KnowledgeCollection(owner_kind="user", owner_id="1", name="fruit")
        session.add(collection)
        session.commit()
    monkeypatch.setattr(rag, "get_session_factory", lambda: factory)
    monkeypatch.setenv("MODSTORE_RAG_RETRIEVAL_MODE", "hybrid")
    monkeypatch.delenv("MODSTORE_RAG_RERANK", raising=False)
    yield collection.id
    engine.dispose()


@pytest.fixture
def catalog(sql_catalog, monkeypatch):
    rows = [
        ("apple", "ordinary apple", 0.0),
        ("pear", "ordinary pear", 0.1),
        ("target", "needle rarecode", 0.9),
    ]

    class Collection:
        state = "ready"

        def count(self):
            return len(rows)

        def query(self, *, n_results, **_kwargs):
            if self.state == "failed":
                raise vector_engine.VectorEngineError("synthetic dense failure")
            selected = [] if self.state == "empty" else rows[:n_results]
            return {
                "ids": [[row[0] for row in selected]],
                "documents": [[row[1] for row in selected]],
                "distances": [[row[2] for row in selected]],
                "metadatas": [[{"doc_id": row[0]} for row in selected]],
            }

        def get(self, *, limit, offset, include):
            assert include == ["documents", "metadatas"]
            selected = rows[offset : offset + limit]
            return {
                "ids": [row[0] for row in selected],
                "documents": [row[1] for row in selected],
                "metadatas": [{"doc_id": row[0]} for row in selected],
            }

    backend = Collection()
    monkeypatch.setattr(vector_engine, "get_collection", lambda name: backend)
    return backend


@pytest.mark.parametrize("state", ["ready", "empty", "failed", "embedding_failed"])
def test_hybrid_recalls_keyword_chunk_outside_dense_candidates(catalog, monkeypatch, state):
    catalog.state = state

    async def unavailable(*args, **kwargs):
        raise rag.EmbeddingConfigError("synthetic embedding unavailable")

    monkeypatch.setattr(rag, "embed_texts", unavailable)
    result = asyncio.run(
        rag.retrieve(
            user_id=1,
            query="rarecode",
            top_k=2,
            query_embedding=None if state == "embedding_failed" else [1.0, 0.0],
        )
    )
    assert "target" in [chunk.chunk_id for chunk in result]
    assert all(chunk.collection_name == "fruit" and chunk.doc_id for chunk in result)
    if state == "ready":
        assert next(chunk for chunk in result if chunk.chunk_id == "apple").distance == 0.0


def test_hybrid_zero_hit_returns_no_arbitrary_keyword_rows(catalog):
    catalog.state = "empty"
    assert (
        asyncio.run(
            rag.retrieve(user_id=1, query="unmatchedtoken", top_k=2, query_embedding=[1.0, 0.0])
        )
        == []
    )


def test_lexical_pagination_stops_at_initial_collection_size(monkeypatch):
    offsets = []

    class GrowingCollection:
        def count(self):
            return 2

        def get(self, *, limit, offset, include):
            offsets.append(offset)
            return {"ids": [str(offset)], "documents": ["growing corpus"]}

    monkeypatch.setattr(vector_engine, "get_collection", lambda name: GrowingCollection())
    result = list(vector_engine.iter_documents("growing", batch_size=1))
    assert [row["id"] for row in result] == ["0", "1"]
    assert offsets == [0, 1]


def test_lexical_count_failure_remains_visible(monkeypatch):
    class UnavailableCollection:
        def count(self):
            raise RuntimeError("collection unavailable")

    monkeypatch.setattr(vector_engine, "get_collection", lambda name: UnavailableCollection())
    with pytest.raises(vector_engine.VectorEngineError, match="collection unavailable"):
        list(vector_engine.iter_documents("unavailable"))


def test_hybrid_real_chroma_reads_independent_paginated_corpus(sql_catalog, tmp_path, monkeypatch):
    pytest.importorskip("chromadb")
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "False")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    vector_engine.reset_client_for_tests()
    name = vector_engine.kb_collection_name(sql_catalog)
    try:
        vector_engine.upsert(
            name,
            ids=["apple", "pear", "target"],
            documents=["ordinary apple", "ordinary pear", "needle rarecode"],
            embeddings=[[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]],
            metadatas=[{"doc_id": value} for value in ["apple", "pear", "target"]],
        )
        dense = vector_engine.query(name, query_embedding=[1.0, 0.0], top_k=2)
        assert "target" not in [row["id"] for row in dense]
        result = asyncio.run(
            rag.retrieve(user_id=1, query="rarecode", top_k=2, query_embedding=[1.0, 0.0])
        )
        assert "target" in [chunk.chunk_id for chunk in result]
        assert {row["id"] for row in vector_engine.iter_documents(name, batch_size=1)} == {
            "apple",
            "pear",
            "target",
        }
    finally:
        vector_engine.reset_client_for_tests()
