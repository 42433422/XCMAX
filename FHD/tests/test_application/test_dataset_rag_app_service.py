from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import dataset_rag_app_service as dataset_rag_module
from app.application.dataset_rag_app_service import (
    DatasetAccessContext,
    DatasetRagApplicationService,
)
from app.fastapi_routes.knowledge_v1 import router as knowledge_router
from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorPgIndex,
    DatasetVectorSQLiteIndex,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk


def _minimal_pdf_bytes() -> bytes:
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 104 >>
stream
BT
/F1 18 Tf
72 720 Td
(The deployment policy says all AI routes should use the server platform XCauto model.) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000311 00000 n 
trailer
<< /Root 1 0 R /Size 6 >>
startxref
465
%%EOF
"""


def test_dataset_ingests_pdf_and_answers_with_citation(tmp_path: Path) -> None:
    pdf_path = tmp_path / "xcauto_policy.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
    )

    ingest = svc.ingest_document(
        dataset_id="ai-platform",
        file_path=str(pdf_path),
        source="xcauto_policy.pdf",
        chunk_strategy="fixed",
        chunk_size=200,
        chunk_overlap=0,
    )

    assert ingest["success"] is True
    assert ingest["document"]["parser"] == "pdfplumber"
    assert ingest["chunk_count"] >= 1

    answer = svc.answer(
        dataset_id="ai-platform",
        query="Which model should AI routes use?",
        top_k=2,
    )

    assert answer["success"] is True
    assert "XCauto" in answer["answer"]
    assert answer["citations"]
    assert answer["citations"][0]["source_url"] == "xcauto_policy.pdf"
    assert answer["chunks"][0]["metadata"]["document_id"] == ingest["document"]["document_id"]


def test_dataset_rejects_file_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[allowed],
        storage_path=tmp_path / "dataset_store.json",
    )

    result = svc.ingest_document(dataset_id="safe", file_path=str(outside))

    assert result["success"] is False
    assert result["error_code"] == "dataset_ingest_failed"
    assert "not under allowed dirs" in result["message"]


def test_dataset_document_delete_removes_chunks(tmp_path: Path) -> None:
    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    ingest = svc.ingest_document(
        dataset_id="delete-me",
        text="alpha document for delete path",
        source="inline",
        chunk_strategy="fixed",
    )
    document_id = ingest["document"]["document_id"]

    deleted = svc.delete_document("delete-me", document_id)
    status = svc.status("delete-me")

    assert deleted["success"] is True
    assert deleted["deleted_chunks"] == ingest["chunk_count"]
    assert status["document_count"] == 0
    assert status["chunk_count"] == 0

    reloaded = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    assert reloaded.status("delete-me")["document_count"] == 0


def test_dataset_persists_and_reloads_documents(tmp_path: Path) -> None:
    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    ingest = svc.ingest_document(
        dataset_id="persisted",
        text="Persistent dataset evidence says XCauto survives service restart.",
        source="persisted-policy.md",
        chunk_strategy="fixed",
    )

    reloaded = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    answer = reloaded.answer(
        dataset_id="persisted",
        query="What survives restart?",
        top_k=1,
    )
    status = reloaded.status("persisted")

    assert ingest["success"] is True
    assert status["document_count"] == 1
    assert status["chunk_count"] == ingest["chunk_count"]
    assert status["storage_path"] == str(storage_path.resolve())
    assert status["persistent"] is True
    assert "XCauto" in answer["answer"]
    assert answer["citations"][0]["source_url"] == "persisted-policy.md"


def test_dataset_tenant_version_filter_rerank_and_index_persist(tmp_path: Path) -> None:
    def embedder(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(lowered.count("xcauto")),
            float(lowered.count("deepseek")),
            float(len(lowered.split())),
        ]

    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=embedder,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    old = svc.ingest_document(
        dataset_id="governed",
        tenant_id="tenant-a",
        source="policy.md",
        text="Legacy policy says tenant A used a local model before migration.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )
    current = svc.ingest_document(
        dataset_id="governed",
        tenant_id="tenant-a",
        source="policy.md",
        text="Current policy says tenant A must use the server platform XCauto model.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )
    other_tenant = svc.ingest_document(
        dataset_id="governed",
        tenant_id="tenant-b",
        source="policy.md",
        text="Tenant B policy mentions DeepSeek and must not leak into tenant A answers.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )

    assert old["document"]["version"] == 1
    assert current["document"]["version"] == 2
    assert other_tenant["document"]["version"] == 1

    latest = svc.answer(
        dataset_id="governed",
        tenant_id="tenant-a",
        version="latest",
        metadata_filter={"doc_type": "policy"},
        rerank=True,
        query="Which server platform model does tenant A use?",
        top_k=1,
    )
    v1 = svc.answer(
        dataset_id="governed",
        tenant_id="tenant-a",
        version="1",
        query="Which model did tenant A use before migration?",
        top_k=1,
    )
    tenant_b = svc.answer(
        dataset_id="governed",
        tenant_id="tenant-b",
        version="latest",
        query="Which model is mentioned for tenant B?",
        top_k=1,
    )
    status = svc.status("governed")

    assert latest["success"] is True
    assert "XCauto" in latest["answer"]
    assert "DeepSeek" not in latest["answer"]
    assert latest["chunks"][0]["metadata"]["tenant_id"] == "tenant-a"
    assert latest["chunks"][0]["metadata"]["document_version"] == 2
    assert "_embedding" not in latest["chunks"][0]["metadata"]
    assert "Legacy" in v1["answer"]
    assert "DeepSeek" in tenant_b["answer"]
    assert status["tenant_ids"] == ["tenant-a", "tenant-b"]
    assert status["index"]["chunk_count"] == status["chunk_count"]
    assert status["index"]["embedding_count"] == status["chunk_count"]
    assert status["index"]["embedding_persisted"] is True

    reloaded = DatasetRagApplicationService(
        embedder=embedder,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    reload_status = reloaded.status("governed")
    reload_latest = reloaded.answer(
        dataset_id="governed",
        tenant_id="tenant-a",
        version="latest",
        query="Which server platform model does tenant A use?",
        top_k=1,
    )

    assert reload_status["index"]["embedding_count"] == status["index"]["embedding_count"]
    assert "XCauto" in reload_latest["answer"]


def test_dataset_sqlite_vector_index_backend_filters_and_persists(tmp_path: Path) -> None:
    def embedder(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(lowered.count("xcauto")),
            float(lowered.count("deepseek")),
            float(len(lowered.split())),
        ]

    vector_path = tmp_path / "dataset_vectors.sqlite"
    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=embedder,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
        vector_index_backend_name="sqlite",
        vector_index_path=vector_path,
    )
    old = svc.ingest_document(
        dataset_id="indexed",
        tenant_id="tenant-a",
        source="policy.md",
        text="Legacy tenant A policy used a local model before migration.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )
    current = svc.ingest_document(
        dataset_id="indexed",
        tenant_id="tenant-a",
        source="policy.md",
        text="Current tenant A policy says all AI routes use the server platform XCauto model.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )
    svc.ingest_document(
        dataset_id="indexed",
        tenant_id="tenant-b",
        source="policy.md",
        text="Tenant B policy mentions DeepSeek and must not leak into tenant A answers.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )

    latest = svc.answer(
        dataset_id="indexed",
        tenant_id="tenant-a",
        version="latest",
        metadata_filter={"doc_type": "policy"},
        query="Which server platform model does tenant A use?",
        top_k=1,
        rerank=True,
    )
    status = svc.status("indexed")
    backend = DatasetVectorSQLiteIndex(vector_path)
    backend_status = backend.status("indexed")
    backend_hits = backend.query(
        "indexed",
        embedder("XCauto server platform"),
        tenant_id="tenant-a",
        version="latest",
        metadata_filter={"doc_type": "policy"},
        top_k=5,
    )

    assert old["document"]["version"] == 1
    assert current["document"]["version"] == 2
    assert latest["success"] is True
    assert latest["vector_backend_used"] is True
    assert latest["index"]["query_backend"] == "sqlite_vector"
    assert "XCauto" in latest["answer"]
    assert "DeepSeek" not in latest["answer"]
    assert status["index"]["vector_backend_name"] == "sqlite_vector"
    assert status["index"]["vector_backend_persistent"] is True
    assert status["index"]["vector_backend_sync_status"] == "synced"
    assert status["index"]["vector_backend_chunk_count"] == status["chunk_count"]
    assert backend_status["index_exists"] is True
    assert backend_status["chunk_count"] == status["chunk_count"]
    assert len(backend_hits) == 1
    assert backend_hits[0].metadata["tenant_id"] == "tenant-a"
    assert backend_hits[0].metadata["document_version"] == 2

    reloaded = DatasetRagApplicationService(
        embedder=embedder,
        allowed_roots=[tmp_path],
        storage_path=storage_path,
        vector_index_backend_name="sqlite",
        vector_index_path=vector_path,
    )
    reload_answer = reloaded.answer(
        dataset_id="indexed",
        tenant_id="tenant-a",
        version="latest",
        metadata_filter={"doc_type": "policy"},
        query="Which server platform model does tenant A use?",
        top_k=1,
        rerank=True,
    )

    assert reload_answer["vector_backend_used"] is True
    assert "XCauto" in reload_answer["answer"]


class _FakePgResult:
    def __init__(self, *, first_row=None, rows=None, rowcount: int = 1) -> None:
        self._first_row = first_row
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._first_row

    def all(self):
        return self._rows


class _FakePgConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "SELECT chunk_count FROM dataset_vector_indexes" in sql:
            return _FakePgResult(first_row={"chunk_count": 1})
        if "SELECT index_id, dataset_id, backend" in sql and "WHERE index_id" in sql:
            return _FakePgResult(
                first_row={
                    "index_id": "dataset:docs",
                    "dataset_id": "docs",
                    "backend": "pgvector",
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "chunk_count": 1,
                }
            )
        if "SELECT" in sql and "content" in sql and "dataset_vector_chunks" in sql:
            return _FakePgResult(
                rows=[
                    {
                        "content": "Current policy uses XCauto.",
                        "source": "policy.md",
                        "source_url": "policy.md",
                        "chunk_index": 0,
                        "char_start": 0,
                        "char_end": 27,
                        "page": None,
                        "metadata": {
                            "tenant_id": "tenant-a",
                            "document_version": 2,
                            "version_label": "v2",
                            "doc_type": "policy",
                        },
                        "score": 0.98,
                    }
                ]
            )
        return _FakePgResult()


class _FakePgBegin:
    def __init__(self, conn: _FakePgConn) -> None:
        self._conn = conn

    def __enter__(self) -> _FakePgConn:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakePgEngine:
    def __init__(self) -> None:
        self.conn = _FakePgConn()

    def begin(self) -> _FakePgBegin:
        return _FakePgBegin(self.conn)


def test_dataset_pgvector_builder_reads_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATASET_RAG_PGVECTOR_DATABASE_URL", "postgresql://rag/db")
    monkeypatch.setenv("DATASET_RAG_PGVECTOR_DIMENSION", "384")
    with patch.object(dataset_rag_module, "DatasetVectorPgIndex") as mock_pg:
        backend = dataset_rag_module._build_dataset_vector_index_backend(
            backend_name="pgvector",
            storage_path=tmp_path / "store.json",
            vector_index_path=None,
        )

    mock_pg.assert_called_once_with("postgresql://rag/db", dimension=384)
    assert backend is mock_pg.return_value


def test_dataset_pgvector_index_replace_query_and_status(monkeypatch) -> None:
    fake_engine = _FakePgEngine()
    monkeypatch.setattr(
        "app.infrastructure.rag.dataset_vector_index.create_engine",
        lambda *args, **kwargs: fake_engine,
    )
    backend = DatasetVectorPgIndex("postgresql://rag/db", dimension=3)
    chunk = RetrievedChunk(
        text="Current policy uses XCauto.",
        score=0.0,
        source="policy.md",
        chunk_index=0,
        char_start=0,
        char_end=27,
        metadata={
            "_embedding": [1.0, 0.0, 0.0],
            "tenant_id": "tenant-a",
            "document_id": "doc-1",
            "document_version": 2,
            "version_label": "v2",
            "doc_type": "policy",
        },
        source_url="policy.md",
    )

    replaced = backend.replace_dataset("docs", [chunk])
    hits = backend.query(
        "docs",
        [1.0, 0.0, 0.0],
        tenant_id="tenant-a",
        version="v2",
        metadata_filter={"doc_type": "policy"},
        top_k=3,
    )
    status = backend.status("docs")

    assert replaced == 1
    assert hits[0].text == "Current policy uses XCauto."
    assert hits[0].score == 0.98
    assert hits[0].metadata["tenant_id"] == "tenant-a"
    assert status["backend"] == "pgvector"
    assert status["dimension"] == 3
    insert_call = next(
        params
        for sql, params in fake_engine.conn.calls
        if "INSERT INTO dataset_vector_chunks" in sql
    )
    assert insert_call["embedding"] == "[1.0, 0.0, 0.0]"
    query_call = next(
        params
        for sql, params in fake_engine.conn.calls
        if "ORDER BY embedding <=> CAST(:query_vector AS vector)" in sql
    )
    assert query_call["tenant_id"] == "tenant-a"
    assert query_call["document_version"] == 2
    assert query_call["metadata_key_0"] == "doc_type"
    assert query_call["metadata_filter_0"] == "policy"


def test_dataset_access_context_enforces_permissions_and_tenant_scope(tmp_path: Path) -> None:
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
    )
    admin = DatasetAccessContext(
        actor_id="admin",
        permissions=frozenset({"dataset.admin"}),
        is_admin=True,
    )
    tenant_a_reader = DatasetAccessContext(
        actor_id="alice",
        tenant_id="tenant-a",
        permissions=frozenset({"dataset.read"}),
    )
    tenant_a_writer = DatasetAccessContext(
        actor_id="alice",
        tenant_id="tenant-a",
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    tenant_b_reader = DatasetAccessContext(
        actor_id="bob",
        tenant_id="tenant-b",
        permissions=frozenset({"dataset.read"}),
    )

    tenant_a = svc.ingest_document(
        dataset_id="secure",
        tenant_id="tenant-a",
        source="policy.md",
        text="Tenant A private policy uses XCauto.",
        chunk_strategy="fixed",
        access_context=admin,
    )
    tenant_b = svc.ingest_document(
        dataset_id="secure",
        tenant_id="tenant-b",
        source="policy.md",
        text="Tenant B private policy mentions DeepSeek.",
        chunk_strategy="fixed",
        access_context=admin,
    )

    own_answer = svc.answer(
        dataset_id="secure",
        query="Which model is in my policy?",
        top_k=2,
        access_context=tenant_a_reader,
    )
    cross_query = svc.answer(
        dataset_id="secure",
        tenant_id="tenant-b",
        query="Which model is in tenant B policy?",
        access_context=tenant_a_reader,
    )
    scoped_status = svc.status("secure", access_context=tenant_a_reader)
    admin_status = svc.status("secure", access_context=admin)
    read_only_ingest = svc.ingest_document(
        dataset_id="secure",
        source="denied.md",
        text="write should fail",
        access_context=tenant_a_reader,
    )
    implicit_tenant_ingest = svc.ingest_document(
        dataset_id="secure",
        source="own.md",
        text="Tenant A writer can ingest without spoofing tenant id.",
        chunk_strategy="fixed",
        access_context=tenant_a_writer,
    )
    cross_delete = svc.delete_document(
        "secure",
        tenant_b["document"]["document_id"],
        access_context=tenant_a_writer,
    )
    rebuild = svc.start_rebuild_index(
        dataset_id="secure",
        background=False,
        access_context=tenant_a_writer,
    )
    job_id = rebuild["job"]["job_id"]
    cross_job = svc.get_rebuild_job("secure", job_id, access_context=tenant_b_reader)

    assert tenant_a["success"] is True
    assert tenant_b["success"] is True
    assert own_answer["success"] is True
    assert "XCauto" in own_answer["answer"]
    assert "DeepSeek" not in own_answer["answer"]
    assert own_answer["tenant_id"] == "tenant-a"
    assert cross_query["success"] is False
    assert cross_query["error_code"] == "dataset_permission_denied"
    assert scoped_status["document_count"] == 1
    assert scoped_status["tenant_ids"] == ["tenant-a"]
    assert scoped_status["index"]["filtered_by_tenant"] == "tenant-a"
    assert admin_status["document_count"] == 2
    assert set(admin_status["tenant_ids"]) == {"tenant-a", "tenant-b"}
    assert read_only_ingest["success"] is False
    assert read_only_ingest["required_permission"] == "dataset.write"
    assert implicit_tenant_ingest["success"] is True
    assert implicit_tenant_ingest["document"]["tenant_id"] == "tenant-a"
    assert cross_delete["success"] is False
    assert cross_delete["error_code"] == "dataset_permission_denied"
    assert rebuild["success"] is True
    assert rebuild["job"]["tenant_id"] == "tenant-a"
    assert cross_job["success"] is False
    assert cross_job["error_code"] == "dataset_permission_denied"


def test_dataset_version_diff_rollback_and_rebuild_job_persist(tmp_path: Path) -> None:
    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    v1 = svc.ingest_document(
        dataset_id="versioned",
        tenant_id="tenant-a",
        source="policy.md",
        text="Tenant A policy uses the local model.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )
    v2 = svc.ingest_document(
        dataset_id="versioned",
        tenant_id="tenant-a",
        source="policy.md",
        text="Tenant A policy uses the server platform XCauto model.",
        chunk_strategy="fixed",
        metadata={"doc_type": "policy"},
    )

    diff = svc.diff_versions(
        dataset_id="versioned",
        tenant_id="tenant-a",
        source="policy.md",
        from_version="1",
        to_version="latest",
    )
    rollback = svc.rollback_document_version(
        dataset_id="versioned",
        tenant_id="tenant-a",
        source="policy.md",
        target_version="1",
        metadata={"rollback_reason": "operator requested"},
    )
    latest_after_rollback = svc.answer(
        dataset_id="versioned",
        tenant_id="tenant-a",
        version="latest",
        query="Which model does tenant A use?",
        top_k=1,
    )
    rebuild = svc.start_rebuild_index(
        dataset_id="versioned",
        tenant_id="tenant-a",
        metadata_filter={"doc_type": "policy"},
        background=False,
    )
    job_id = rebuild["job"]["job_id"]
    job_status = svc.get_rebuild_job("versioned", job_id)
    status = svc.status("versioned")

    assert v1["document"]["version"] == 1
    assert v2["document"]["version"] == 2
    assert diff["success"] is True
    assert diff["changed"] is True
    assert diff["from_version"] == 1
    assert diff["to_version"] == 2
    assert any("XCauto" in line for line in diff["added_lines"])
    assert any("local model" in line for line in diff["removed_lines"])
    assert rollback["success"] is True
    assert rollback["document"]["version"] == 3
    assert rollback["document"]["metadata"]["rollback"] is True
    assert rollback["document"]["metadata"]["rollback_from_version"] == 1
    assert "local model" in latest_after_rollback["answer"]
    assert rebuild["success"] is True
    assert rebuild["job"]["status"] == "completed"
    assert rebuild["job"]["chunk_count"] == status["chunk_count"]
    assert job_status["job"]["job_id"] == job_id
    assert status["rebuild_job_count"] == 1
    assert status["rebuild_jobs"][0]["status"] == "completed"

    reloaded = DatasetRagApplicationService(
        embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
        allowed_roots=[tmp_path],
        storage_path=storage_path,
    )
    reloaded_status = reloaded.status("versioned")
    reloaded_job = reloaded.get_rebuild_job("versioned", job_id)

    assert reloaded_status["document_count"] == 3
    assert reloaded_status["rebuild_job_count"] == 1
    assert reloaded_job["job"]["status"] == "completed"


def test_dataset_rebuild_queue_governance_cancel_drain_and_reload(tmp_path: Path) -> None:
    storage_path = tmp_path / "dataset_store.json"
    svc = DatasetRagApplicationService(
        embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
        allowed_roots=[tmp_path],
        storage_path=storage_path,
        max_concurrent_rebuild_jobs=1,
        rebuild_workers_enabled=False,
    )
    writer = DatasetAccessContext(
        actor_id="alice",
        tenant_id="tenant-a",
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    ingest = svc.ingest_document(
        dataset_id="queued",
        source="policy.md",
        text="Tenant A queued rebuild policy uses XCauto.",
        chunk_strategy="fixed",
        access_context=writer,
    )

    first = svc.start_rebuild_index(
        dataset_id="queued",
        background=True,
        access_context=writer,
    )
    second = svc.start_rebuild_index(
        dataset_id="queued",
        background=True,
        access_context=writer,
    )
    first_id = first["job"]["job_id"]
    second_id = second["job"]["job_id"]
    queued_status = svc.status("queued", access_context=writer)
    cancelled = svc.cancel_rebuild_job("queued", second_id, access_context=writer)
    drained = svc.drain_rebuild_queue()
    final_status = svc.status("queued", access_context=writer)
    first_job = svc.get_rebuild_job("queued", first_id, access_context=writer)
    second_job = svc.get_rebuild_job("queued", second_id, access_context=writer)

    assert ingest["success"] is True
    assert first["job"]["status"] == "queued"
    assert first["job"]["queue_position"] == 1
    assert second["job"]["status"] == "queued"
    assert second["job"]["queue_position"] == 2
    assert queued_status["rebuild_queue"]["queued"] == 2
    assert queued_status["rebuild_queue"]["worker_enabled"] is False
    assert queued_status["rebuild_queue"]["next_job_id"] == first_id
    assert cancelled["success"] is True
    assert cancelled["job"]["status"] == "cancelled"
    assert drained["drained_count"] == 1
    assert drained["jobs"][0]["job_id"] == first_id
    assert drained["jobs"][0]["status"] == "completed"
    assert first_job["job"]["status"] == "completed"
    assert first_job["job"]["attempt_count"] == 1
    assert second_job["job"]["status"] == "cancelled"
    assert final_status["rebuild_queue"]["completed"] == 1
    assert final_status["rebuild_queue"]["cancelled"] == 1
    assert final_status["rebuild_queue"]["queued"] == 0

    reloaded = DatasetRagApplicationService(
        embedder=lambda text: [float(len(text)), float(text.lower().count("xcauto"))],
        allowed_roots=[tmp_path],
        storage_path=storage_path,
        max_concurrent_rebuild_jobs=1,
        rebuild_workers_enabled=False,
    )
    reload_status = reloaded.status("queued", access_context=writer)

    assert reload_status["document_count"] == 1
    assert reload_status["rebuild_queue"]["completed"] == 1
    assert reload_status["rebuild_queue"]["cancelled"] == 1


def test_knowledge_v1_dataset_routes_use_dataset_service(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
    )

    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=svc,
    ):
        ingest = client.post(
            "/api/knowledge/v1/datasets/route-docs/documents",
            json={
                "text": "Route dataset evidence says XCauto is the server model.",
                "source": "route-policy.md",
                "tenant_id": "tenant-route",
                "chunk_strategy": "fixed",
                "metadata": {"doc_type": "route_policy"},
            },
        )
        query = client.post(
            "/api/knowledge/v1/datasets/route-docs/query",
            json={
                "query": "What is the server model?",
                "top_k": 1,
                "tenant_id": "tenant-route",
                "version": "latest",
                "metadata_filter": {"doc_type": "route_policy"},
                "rerank": True,
            },
        )

    assert ingest.status_code == 200
    assert ingest.json()["success"] is True
    assert query.status_code == 200
    body = query.json()
    assert body["success"] is True
    assert "XCauto" in body["answer"]
    assert body["citations"][0]["source_url"] == "route-policy.md"


def test_knowledge_v1_dataset_routes_enforce_access_context(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
    )
    admin_headers = {"X-Dataset-Admin": "true"}
    tenant_a_read_headers = {
        "X-Dataset-Tenant-ID": "tenant-a",
        "X-Dataset-Permissions": "dataset.read",
    }
    tenant_a_write_headers = {
        "X-Dataset-Tenant-ID": "tenant-a",
        "X-Dataset-Permissions": "dataset.read,dataset.write",
    }

    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=svc,
    ):
        tenant_a = client.post(
            "/api/knowledge/v1/datasets/secure-route/documents",
            headers=admin_headers,
            json={
                "text": "Tenant A route policy uses XCauto.",
                "source": "route-policy.md",
                "tenant_id": "tenant-a",
                "chunk_strategy": "fixed",
            },
        )
        client.post(
            "/api/knowledge/v1/datasets/secure-route/documents",
            headers=admin_headers,
            json={
                "text": "Tenant B route policy mentions DeepSeek.",
                "source": "route-policy.md",
                "tenant_id": "tenant-b",
                "chunk_strategy": "fixed",
            },
        )
        own_query = client.post(
            "/api/knowledge/v1/datasets/secure-route/query",
            headers=tenant_a_read_headers,
            json={"query": "Which route policy model?", "top_k": 2},
        )
        cross_query = client.post(
            "/api/knowledge/v1/datasets/secure-route/query",
            headers=tenant_a_read_headers,
            json={
                "query": "Which model does tenant B mention?",
                "tenant_id": "tenant-b",
            },
        )
        read_only_ingest = client.post(
            "/api/knowledge/v1/datasets/secure-route/documents",
            headers=tenant_a_read_headers,
            json={"text": "denied", "source": "denied.md"},
        )
        own_ingest = client.post(
            "/api/knowledge/v1/datasets/secure-route/documents",
            headers=tenant_a_write_headers,
            json={"text": "Tenant A own write.", "source": "own.md"},
        )
        status = client.get(
            "/api/knowledge/v1/datasets/secure-route/status",
            headers=tenant_a_read_headers,
        )
        delete_cross = client.delete(
            f"/api/knowledge/v1/datasets/secure-route/documents/{tenant_a.json()['document']['document_id']}",
            headers={
                "X-Dataset-Tenant-ID": "tenant-b",
                "X-Dataset-Permissions": "dataset.read,dataset.write",
            },
        )

    assert tenant_a.status_code == 200
    assert own_query.status_code == 200
    assert own_query.json()["success"] is True
    assert "XCauto" in own_query.json()["answer"]
    assert "DeepSeek" not in own_query.json()["answer"]
    assert cross_query.status_code == 200
    assert cross_query.json()["success"] is False
    assert cross_query.json()["error_code"] == "dataset_permission_denied"
    assert read_only_ingest.json()["success"] is False
    assert read_only_ingest.json()["required_permission"] == "dataset.write"
    assert own_ingest.json()["document"]["tenant_id"] == "tenant-a"
    assert status.json()["document_count"] == 2
    assert status.json()["tenant_ids"] == ["tenant-a"]
    assert delete_cross.json()["success"] is False
    assert delete_cross.json()["error_code"] == "dataset_permission_denied"


def test_knowledge_v1_dataset_version_ops_and_rebuild_routes(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
    )

    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=svc,
    ):
        first = client.post(
            "/api/knowledge/v1/datasets/route-versioned/documents",
            json={
                "text": "Route policy v1 says local model.",
                "source": "route-policy.md",
                "tenant_id": "tenant-route",
                "chunk_strategy": "fixed",
                "metadata": {"doc_type": "route_policy"},
            },
        )
        second = client.post(
            "/api/knowledge/v1/datasets/route-versioned/documents",
            json={
                "text": "Route policy v2 says XCauto model.",
                "source": "route-policy.md",
                "tenant_id": "tenant-route",
                "chunk_strategy": "fixed",
                "metadata": {"doc_type": "route_policy"},
            },
        )
        diff = client.post(
            "/api/knowledge/v1/datasets/route-versioned/versions/diff",
            json={
                "source": "route-policy.md",
                "tenant_id": "tenant-route",
                "from_version": "1",
                "to_version": "latest",
            },
        )
        rollback = client.post(
            "/api/knowledge/v1/datasets/route-versioned/versions/rollback",
            json={
                "source": "route-policy.md",
                "tenant_id": "tenant-route",
                "target_version": "1",
                "metadata": {"rollback_reason": "route test"},
            },
        )
        rebuild = client.post(
            "/api/knowledge/v1/datasets/route-versioned/index/rebuild",
            json={
                "tenant_id": "tenant-route",
                "metadata_filter": {"doc_type": "route_policy"},
                "background": False,
            },
        )
        job_id = rebuild.json()["job"]["job_id"]
        job_status = client.get(
            f"/api/knowledge/v1/datasets/route-versioned/index/rebuild/{job_id}"
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["document"]["version"] == 1
    assert second.json()["document"]["version"] == 2
    assert diff.status_code == 200
    assert diff.json()["success"] is True
    assert any("XCauto" in line for line in diff.json()["added_lines"])
    assert rollback.status_code == 200
    assert rollback.json()["success"] is True
    assert rollback.json()["document"]["version"] == 3
    assert rebuild.status_code == 200
    assert rebuild.json()["job"]["status"] == "completed"
    assert job_status.status_code == 200
    assert job_status.json()["job"]["job_id"] == job_id


def test_knowledge_v1_dataset_rebuild_cancel_route(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
    svc = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "dataset_store.json",
        rebuild_workers_enabled=False,
    )
    headers = {
        "X-Dataset-Tenant-ID": "tenant-route",
        "X-Dataset-Permissions": "dataset.read,dataset.write",
    }

    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=svc,
    ):
        client.post(
            "/api/knowledge/v1/datasets/route-queue/documents",
            headers=headers,
            json={
                "text": "Route queue policy uses XCauto.",
                "source": "route-policy.md",
                "chunk_strategy": "fixed",
            },
        )
        rebuild = client.post(
            "/api/knowledge/v1/datasets/route-queue/index/rebuild",
            headers=headers,
            json={"background": True},
        )
        job_id = rebuild.json()["job"]["job_id"]
        cancelled = client.post(
            f"/api/knowledge/v1/datasets/route-queue/index/rebuild/{job_id}/cancel",
            headers=headers,
        )
        job_status = client.get(
            f"/api/knowledge/v1/datasets/route-queue/index/rebuild/{job_id}",
            headers=headers,
        )

    assert rebuild.status_code == 200
    assert rebuild.json()["job"]["status"] == "queued"
    assert cancelled.status_code == 200
    assert cancelled.json()["success"] is True
    assert cancelled.json()["job"]["status"] == "cancelled"
    assert job_status.json()["job"]["status"] == "cancelled"
