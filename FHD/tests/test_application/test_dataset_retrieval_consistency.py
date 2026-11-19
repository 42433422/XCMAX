"""Independent recall and model/version transitions, using synthetic documents."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.rag.dataset_vector_index import DatasetVectorPgIndex


def _service(tmp_path, embedder):
    return DatasetRagApplicationService(
        storage_path=tmp_path / "documents.json",
        vector_index_path=tmp_path / "vectors.sqlite",
        embedder=embedder,
        rebuild_workers_enabled=False,
    )


@pytest.mark.parametrize("mode", ["keyword", "hybrid"])
def test_keyword_recall_is_independent_of_dense_candidate_limit(tmp_path, monkeypatch, mode):
    embedded = []

    def embed(text):
        embedded.append(text)
        return [0.0, 1.0] if text.startswith("needle") else [1.0, 0.0]

    service = _service(tmp_path, embed)
    for number in range(51):
        assert service.ingest_document(
            dataset_id="catalog",
            source=f"fruit-{number}",
            text=f"ordinary fruit description {number}",
            chunk_strategy="fixed",
        )["success"]
    assert service.ingest_document(
        dataset_id="catalog", source="target", text="needle rarecode", chunk_strategy="fixed"
    )["success"]
    calls = []
    original = service._vector.backend.query

    def dense_query(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(service._vector.backend, "query", dense_query)
    embedded.clear()
    result = service.query(dataset_id="catalog", query="rarecode", top_k=3, retrieval_mode=mode)
    assert "needle rarecode" in [chunk["text"] for chunk in result["chunks"]]
    if mode == "keyword":
        empty = service.query(dataset_id="catalog", query="unmatchedtoken", retrieval_mode=mode)
        assert empty["chunks"] == []
        assert empty["answer_grounded"] is False
        assert calls == [] and embedded == [], "keyword retrieval must not depend on embeddings"


class _Embedding:
    def __init__(self, identity, vector):
        self.embedding_fingerprint = identity
        self.vector = vector
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return self.vector


def test_dense_candidates_do_not_match_text_against_vector_coordinates(tmp_path):
    service = _service(
        tmp_path, lambda text: [0.0, 1.0] if text.startswith("fruit") else [1.0, 0.0]
    )
    service.ingest_document(
        dataset_id="catalog", source="fruit", text="fruit number 0", chunk_strategy="fixed"
    )
    result = service.query(dataset_id="catalog", query="unmatchedtoken", retrieval_mode="vector")
    assert result["chunks"] == []


@pytest.mark.parametrize("replacement", [[0.0, 1.0], []])
def test_restart_rebuilds_same_dimension_model_change(tmp_path, replacement):
    original = _Embedding("synthetic-model-v1", [1.0, 0.0])
    service = _service(tmp_path, original)
    assert service.ingest_document(
        dataset_id="catalog", source="fruit", text="apple description", chunk_strategy="fixed"
    )["success"]
    changed = _Embedding("synthetic-model-v2", replacement)
    reloaded = _service(tmp_path, changed)
    chunks = reloaded._repository.datasets["catalog"].chunks
    assert all((chunk.metadata or {}).get("_embedding", []) == replacement for chunk in chunks)
    assert "apple description" in changed.calls
    if replacement:
        persisted = json.loads((tmp_path / "documents.json").read_text())
        assert (
            persisted["datasets"]["catalog"]["chunks"][0]["metadata"]["_embedding_fingerprint"]
            == "synthetic-model-v2"
        )
        changed.calls.clear()
        _service(tmp_path, changed)
        assert "apple description" not in changed.calls


def test_embedding_identity_tracks_model_revision_not_credentials(monkeypatch):
    monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://example.invalid/embeddings")
    monkeypatch.setenv("FHD_EMBEDDING_REMOTE_MODEL", "fruit-model-v1")
    original = EmbeddingService(mode="remote")
    monkeypatch.setenv("FHD_EMBEDDING_REMOTE_API_KEY", "synthetic-key")
    assert EmbeddingService(mode="remote").embedding_fingerprint == original.embedding_fingerprint
    monkeypatch.setenv("FHD_EMBEDDING_REMOTE_MODEL", "fruit-model-v2")
    changed = EmbeddingService(mode="remote")
    assert changed.embedding_fingerprint != original.embedding_fingerprint
    monkeypatch.setenv("FHD_EMBEDDING_MODEL_REVISION", "fruit-revision-2")
    assert EmbeddingService(mode="remote").embedding_fingerprint != changed.embedding_fingerprint


def test_queued_rebuild_invalidates_old_model_without_loading_new_model(tmp_path):
    service = _service(tmp_path, _Embedding("synthetic-model-v1", [1.0, 0.0]))
    service.ingest_document(
        dataset_id="catalog", source="fruit", text="apple description", chunk_strategy="fixed"
    )
    assert (
        service.start_rebuild_index(dataset_id="catalog", background=True)["job"]["status"]
        == "queued"
    )
    changed = _Embedding("synthetic-model-v2", [0.0, 1.0])
    reloaded = _service(tmp_path, changed)
    assert changed.calls == []
    assert all(
        "_embedding" not in chunk.metadata
        for chunk in reloaded._repository.datasets["catalog"].chunks
    )
    assert reloaded.drain_rebuild_queue()["drained_count"] == 1
    assert "apple description" in changed.calls
    assert all(
        chunk.metadata["_embedding_fingerprint"] == "synthetic-model-v2"
        for chunk in reloaded._repository.datasets["catalog"].chunks
    )


def test_pg_latest_is_selected_before_dense_top_k():
    """Execute the generated relational query; replace only pgvector distance syntax.

    This tests filter/LIMIT semantics with SQLite's SQL engine, not pgvector ANN
    behavior. Live PostgreSQL integration remains a separate deployment gate.
    """
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE dataset_vector_chunks (index_id TEXT, tenant_id TEXT, source TEXT, "
        "document_version INTEGER, version_label TEXT, content TEXT, embedding REAL, "
        "metadata TEXT, source_url TEXT, chunk_index INTEGER, char_start INTEGER, "
        "char_end INTEGER, page INTEGER)"
    )
    for version, distance in [(1, 0.0), (2, 0.8)]:
        connection.execute(
            "INSERT INTO dataset_vector_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "dataset:catalog",
                "default",
                "fruit",
                version,
                f"v{version}",
                f"apple description v{version}",
                distance,
                json.dumps({"source": "fruit", "document_version": version}),
                "",
                0,
                0,
                20,
                None,
            ),
        )

    class Result:
        def __init__(self, cursor):
            self.cursor = cursor

        def mappings(self):
            return self

        def all(self):
            return [dict(row) for row in self.cursor.fetchall()]

    class Engine:
        @contextmanager
        def begin(self):
            yield self

        def execute(self, statement, params):
            sql = str(statement).replace("embedding <=> CAST(:query_vector AS vector)", "embedding")
            return Result(connection.execute(sql, params))

    backend = object.__new__(DatasetVectorPgIndex)
    backend._engine = Engine()
    try:
        assert backend.query("catalog", [1.0], top_k=1)[0].text.endswith("v1")
        latest = backend.query("catalog", [1.0], top_k=1, version="latest")
        assert [chunk.text for chunk in latest] == ["apple description v2"]
    finally:
        connection.close()
