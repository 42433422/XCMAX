from __future__ import annotations

"""Targeted real-behavior tests filling the residual coverage gaps in
dataset_rag_app_service.py.

These complement test_dataset_rag_app_service.py and test_dataset_rag_cov.py;
they deliberately exercise the few remaining uncovered units: extraction
error branches, rebuild-job worker/exception/recovery paths, vector-index
failure handling, document-version resolution edge cases, and small helper
fall-through branches.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application import dataset_rag_app_service as mod
from app.application.dataset_rag_app_service import (
    DatasetAccessContext,
    DatasetRagApplicationService,
    DatasetRebuildJob,
    _build_dataset_vector_index_backend,
    _DatasetState,
    _embedding_metadata,
    _metadata_matches,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk


def _embedder(text: str) -> list[float]:
    lowered = text.lower()
    return [float(len(lowered)), float(lowered.count("xcauto")), 1.0]


def _make_svc(tmp_path: Path, *, workers: bool = False, **kwargs) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        embedder=_embedder,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=workers,
        vector_index_backend_name="none",
        **kwargs,
    )


def _ingest(svc: DatasetRagApplicationService, dataset_id: str = "ds", **kw) -> dict:
    params = {
        "dataset_id": dataset_id,
        "text": "the deployment policy uses XCauto model",
        "source": "policy.md",
        "chunk_strategy": "fixed",
        "chunk_size": 200,
    }
    params.update(kw)
    return svc.ingest_document(**params)


# ---------------------------------------------------------------------------
# ingest_document: "document produced no chunks" branch (line 228)
# ---------------------------------------------------------------------------


def test_ingest_no_chunks_produced_returns_error(tmp_path):
    svc = _make_svc(tmp_path)
    # text passes the non-empty guard, but the splitter yields nothing.
    with patch.object(svc, "_split_text", return_value=[]):
        r = svc.ingest_document(
            dataset_id="ds",
            text="content that strips to non-empty",
            chunk_strategy="fixed",
        )
    assert r["success"] is False
    assert r["error_code"] == "dataset_ingest_failed"
    assert "no chunks" in r["message"]


# ---------------------------------------------------------------------------
# _extract_file_text: unsupported / pdf / docx branches (lines 890, 895-919)
# ---------------------------------------------------------------------------


def test_ingest_unsupported_file_type_returns_error(tmp_path):
    bad = tmp_path / "image.png"
    bad.write_bytes(b"\x89PNG not really")
    svc = _make_svc(tmp_path)
    r = svc.ingest_document(dataset_id="ds", file_path=str(bad))
    assert r["success"] is False
    assert "unsupported document type" in r["message"]
    assert ".png" in r["message"]


def test_extract_pdf_missing_dependency_raises_runtime(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    svc = _make_svc(tmp_path)
    # Force the in-function `import pdfplumber` to fail.
    with patch.dict("sys.modules", {"pdfplumber": None}):
        with pytest.raises(RuntimeError, match="pdfplumber is required"):
            svc._extract_pdf_text(pdf)


def test_extract_pdf_success_with_fake_plumber(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    svc = _make_svc(tmp_path)

    page1 = MagicMock()
    page1.extract_text.return_value = "First page about XCauto."
    page2 = MagicMock()
    page2.extract_text.return_value = ""  # exercise the "skip empty page" branch

    fake_pdf = MagicMock()
    fake_pdf.pages = [page1, page2]
    fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
    fake_pdf.__exit__ = MagicMock(return_value=False)

    fake_module = MagicMock()
    fake_module.open.return_value = fake_pdf
    with patch.dict("sys.modules", {"pdfplumber": fake_module}):
        text, parser, meta = svc._extract_pdf_text(pdf)

    assert "First page about XCauto." in text
    assert parser == "pdfplumber"
    assert meta["page_count"] == 2
    assert meta["extension"] == ".pdf"


def test_extract_docx_missing_dependency_raises_runtime(tmp_path):
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"PK fake docx")
    svc = _make_svc(tmp_path)
    with patch.dict("sys.modules", {"docx": None}):
        with pytest.raises(RuntimeError, match="python-docx is required"):
            svc._extract_docx_text(docx)


def test_extract_docx_success_with_paragraphs_and_tables(tmp_path):
    docx = tmp_path / "doc.docx"
    docx.write_bytes(b"PK fake docx")
    svc = _make_svc(tmp_path)

    para = MagicMock()
    para.text = "Policy paragraph"
    empty_para = MagicMock()
    empty_para.text = "   "  # filtered out

    cell_a = MagicMock()
    cell_a.text = "col1"
    cell_b = MagicMock()
    cell_b.text = "col2"
    row = MagicMock()
    row.cells = [cell_a, cell_b]
    empty_cell = MagicMock()
    empty_cell.text = "  "
    empty_row = MagicMock()
    empty_row.cells = [empty_cell]
    table = MagicMock()
    table.rows = [row, empty_row]

    doc_obj = MagicMock()
    doc_obj.paragraphs = [para, empty_para]
    doc_obj.tables = [table]

    fake_docx_module = MagicMock()
    fake_docx_module.Document.return_value = doc_obj
    with patch.dict("sys.modules", {"docx": fake_docx_module}):
        text, parser, meta = svc._extract_docx_text(docx)

    assert "Policy paragraph" in text
    assert "col1 | col2" in text
    assert parser == "python-docx"
    assert meta["extension"] == ".docx"


# ---------------------------------------------------------------------------
# _load_persisted_state: malformed payload skip branches (lines 945, 949)
# ---------------------------------------------------------------------------


def test_load_persisted_state_skips_non_dict_payloads(tmp_path):
    storage = tmp_path / "store.json"
    # datasets is a dict, but one value is not a dict (line 949 `continue`),
    # and one good dataset is loaded.
    storage.write_text(
        '{"version": 1, "datasets": {"bad": "not-a-dict", "good": {"dataset_id": "good"}}}',
        encoding="utf-8",
    )
    svc = _make_svc(tmp_path)
    status = svc.status()
    assert status["success"] is True
    assert "good" in status["datasets"]
    assert "bad" not in status["datasets"]


def test_load_persisted_state_non_dict_datasets_field(tmp_path):
    storage = tmp_path / "store.json"
    # datasets is a list, not a dict (line 944-945 early return).
    storage.write_text('{"version": 1, "datasets": [1, 2, 3]}', encoding="utf-8")
    svc = _make_svc(tmp_path)
    status = svc.status()
    assert status["success"] is True
    assert status["dataset_count"] == 0


# ---------------------------------------------------------------------------
# _resolve_document_version: vN prefix + invalid raise (lines 1033, 1036)
# ---------------------------------------------------------------------------


def test_resolve_document_version_v_prefix():
    state = _DatasetState("ds")
    assert (
        DatasetRagApplicationService._resolve_document_version(
            state, source="s", tenant_id="t", requested="v3"
        )
        == 3
    )


def test_resolve_document_version_invalid_raises():
    state = _DatasetState("ds")
    with pytest.raises(ValueError, match="version must be an integer"):
        DatasetRagApplicationService._resolve_document_version(
            state, source="s", tenant_id="t", requested="abc"
        )


def test_ingest_with_v_prefix_version(tmp_path):
    svc = _make_svc(tmp_path)
    r = _ingest(svc, version="v4")
    assert r["success"] is True
    assert r["document"]["version"] == 4


# ---------------------------------------------------------------------------
# _resolve_document_for_version: explicit version not found (line 1066)
# ---------------------------------------------------------------------------


def test_resolve_document_for_version_not_found_returns_none(tmp_path):
    svc = _make_svc(tmp_path)
    _ingest(svc, version=1)
    state = svc._datasets["ds"]
    # Candidates exist for source/tenant, but version 9 has no match.
    found = DatasetRagApplicationService._resolve_document_for_version(
        state, source="policy.md", tenant_id="default", version="9"
    )
    assert found is None


# ---------------------------------------------------------------------------
# cancel_rebuild_job: tenant denied attaches job_id (lines 607-608)
# ---------------------------------------------------------------------------


def test_cancel_rebuild_job_tenant_denied_includes_job_id(tmp_path):
    svc = _make_svc(tmp_path, workers=False)
    svc.ingest_document(
        dataset_id="ds",
        text="tenant scoped content for cancel",
        source="policy.md",
        tenant_id="tenant_a",
        chunk_strategy="fixed",
    )
    start = svc.start_rebuild_index(dataset_id="ds", tenant_id="tenant_a", background=True)
    job_id = start["job"]["job_id"]
    other_tenant = DatasetAccessContext(
        actor_id="bob",
        tenant_id="tenant_b",
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    r = svc.cancel_rebuild_job("ds", job_id, access_context=other_tenant)
    assert r["success"] is False
    assert r["error_code"] == "dataset_permission_denied"
    assert r["job_id"] == job_id


# ---------------------------------------------------------------------------
# start_rebuild_index background with workers enabled (line 559) +
# _start_rebuild_threads / _run_rebuild_job claimed path (1125, 1134, 1165...)
# ---------------------------------------------------------------------------


def test_start_rebuild_background_with_workers_completes(tmp_path):
    # workers enabled -> _claim_next_rebuild_jobs_locked returns starts (559),
    # threads spawn (1123-1134) and run the job to completion.
    svc = _make_svc(tmp_path, workers=True, max_concurrent_rebuild_jobs=1)
    _ingest(svc, tenant_id="tenant_a")
    r = svc.start_rebuild_index(
        dataset_id="ds",
        tenant_id="tenant_a",
        metadata_filter={"source": "policy.md"},
        background=True,
    )
    assert r["success"] is True
    assert r["background"] is True
    job_id = r["job"]["job_id"]

    # Wait for the daemon thread to finish via the public getter.
    import time

    deadline = time.time() + 5.0
    status = "queued"
    while time.time() < deadline:
        job = svc.get_rebuild_job("ds", job_id)["job"]
        status = job["status"]
        if status in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert status == "completed"
    assert job["chunk_count"] >= 1
    assert job["document_count"] >= 1


# ---------------------------------------------------------------------------
# _run_rebuild_job: terminal status early-return (lines 1148-1150)
# ---------------------------------------------------------------------------


def test_run_rebuild_job_already_terminal_is_noop(tmp_path):
    svc = _make_svc(tmp_path, workers=False)
    _ingest(svc)
    state = svc._datasets["ds"]
    job = DatasetRebuildJob(job_id="done_job", dataset_id="ds", status="completed")
    state.rebuild_jobs["done_job"] = job
    # Should return immediately without altering the completed job.
    svc._run_rebuild_job("ds", "done_job", schedule_next=False)
    assert state.rebuild_jobs["done_job"].status == "completed"


def test_run_rebuild_job_missing_state_is_noop(tmp_path):
    svc = _make_svc(tmp_path, workers=False)
    # No dataset -> state is None -> early return (line 1147-1148).
    svc._run_rebuild_job("ghost", "no_job", schedule_next=False)
    assert "ghost" not in svc._datasets


# ---------------------------------------------------------------------------
# _run_rebuild_job: exception path requeue + final failure (1191-1205)
# ---------------------------------------------------------------------------


def test_run_rebuild_job_exception_requeues_then_fails(tmp_path):
    svc = _make_svc(tmp_path, workers=False)
    _ingest(svc)
    # First start a queued job with 2 attempts allowed.
    start = svc.start_rebuild_index(dataset_id="ds", background=True, max_attempts=2)
    job_id = start["job"]["job_id"]

    # Patch module-level _embedding_metadata to raise a recoverable error from
    # inside the rebuild loop (line 1175 call site).
    def boom(_embedder, _text):
        raise OSError("embed backend down")

    with patch.object(mod, "_embedding_metadata", side_effect=boom):
        # Attempt 1 -> exception -> requeued (attempt_count 1 < max 2).
        svc._run_rebuild_job("ds", job_id, claimed=False, schedule_next=False)
        job = svc.get_rebuild_job("ds", job_id)["job"]
        assert job["status"] == "queued"
        assert job["attempt_count"] == 1
        assert "embed backend down" in job["error"]

        # Attempt 2 -> exception -> attempt_count 2 == max -> failed.
        svc._run_rebuild_job("ds", job_id, claimed=False, schedule_next=False)
        job2 = svc.get_rebuild_job("ds", job_id)["job"]
    assert job2["status"] == "failed"
    assert job2["attempt_count"] == 2
    assert job2["completed_at"] != ""


# ---------------------------------------------------------------------------
# _run_rebuild_job: tenant + metadata_filter skip branches (1170-1173)
# ---------------------------------------------------------------------------


def test_run_rebuild_job_filters_by_tenant_and_metadata(tmp_path):
    svc = _make_svc(tmp_path, workers=False)
    svc.ingest_document(
        dataset_id="ds",
        text="tenant A kept chunk content",
        source="a.md",
        tenant_id="tenant_a",
        chunk_strategy="fixed",
        metadata={"doc_type": "keep"},
    )
    svc.ingest_document(
        dataset_id="ds",
        text="tenant A skipped by metadata",
        source="b.md",
        tenant_id="tenant_a",
        chunk_strategy="fixed",
        metadata={"doc_type": "drop"},
    )
    svc.ingest_document(
        dataset_id="ds",
        text="tenant B skipped by tenant filter",
        source="c.md",
        tenant_id="tenant_b",
        chunk_strategy="fixed",
        metadata={"doc_type": "keep"},
    )
    r = svc.start_rebuild_index(
        dataset_id="ds",
        tenant_id="tenant_a",
        metadata_filter={"doc_type": "keep"},
        background=False,
    )
    assert r["success"] is True
    job = r["job"]
    assert job["status"] == "completed"
    # Only the single tenant_a/keep document is rebuilt.
    assert job["document_count"] == 1
    assert job["chunk_count"] == 1


# ---------------------------------------------------------------------------
# _recover_rebuild_jobs_locked: running -> queued on reload (1459-1464)
# ---------------------------------------------------------------------------


def test_running_job_requeued_after_restart(tmp_path):
    storage = tmp_path / "store.json"
    svc = _make_svc(tmp_path, workers=False)
    _ingest(svc)
    state = svc._datasets["ds"]
    job = DatasetRebuildJob(
        job_id="stuck",
        dataset_id="ds",
        status="running",
        worker_id="worker-1",
    )
    state.rebuild_jobs["stuck"] = job
    with svc._lock:
        svc._persist_locked()

    reloaded = DatasetRagApplicationService(
        embedder=_embedder,
        allowed_roots=[tmp_path],
        storage_path=storage,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    recovered = reloaded.get_rebuild_job("ds", "stuck")["job"]
    assert recovered["status"] == "queued"
    assert recovered["worker_id"] == ""
    assert "requeued after service restart" in recovered["error"]


# ---------------------------------------------------------------------------
# Vector-index failure handling: sync failed + status failed (1246-1248,
# 1266-1267) and query candidate error (1225/1234)
# ---------------------------------------------------------------------------


def test_vector_backend_sync_and_status_failures_recorded(tmp_path):
    backend = MagicMock()
    backend.backend_name = "flaky"
    backend.replace_dataset.side_effect = OSError("write failed")
    backend.status.side_effect = OSError("status failed")
    backend.query.side_effect = OSError("query failed")
    svc = DatasetRagApplicationService(
        embedder=_embedder,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=False,
        vector_index_backend=backend,
    )
    r = _ingest(svc)
    assert r["success"] is True
    status = svc.status("ds")
    index = status["index"]
    # _sync_vector_index_locked failure branch (1246-1248).
    assert index["vector_backend_sync_status"] == "failed"
    assert "write failed" in index["vector_backend_error"]
    # _vector_index_status failure branch (1266-1267).
    assert index["vector_backend"]["status"] == "failed"
    assert "status failed" in index["vector_backend"]["error"]


def test_query_vector_backend_error_falls_back_to_in_memory(tmp_path):
    backend = MagicMock()
    backend.backend_name = "flaky"
    backend.replace_dataset.return_value = 1
    backend.status.return_value = {
        "backend": "flaky",
        "persistent": True,
        "chunk_count": 1,
        "index_exists": True,
    }
    backend.query.side_effect = OSError("query down")
    svc = DatasetRagApplicationService(
        embedder=_embedder,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=False,
        vector_index_backend=backend,
    )
    _ingest(svc, text="XCauto deployment policy says use the platform model")
    r = svc.query(dataset_id="ds", query="XCauto policy")
    assert r["success"] is True
    # Backend query failed -> fell back to in-memory hybrid.
    assert r["vector_backend_used"] is False
    assert r["index"]["query_backend"] == "in_memory_hybrid"


def test_query_vector_backend_returns_non_list_embedding(tmp_path):
    # Embedder returns a non-list -> _query_vector_index_candidates returns None
    # (line 1224-1225) -> in-memory path.
    backend = MagicMock()
    backend.backend_name = "flaky"
    backend.replace_dataset.return_value = 1
    backend.status.return_value = {
        "backend": "flaky",
        "persistent": True,
        "chunk_count": 1,
        "index_exists": True,
    }
    calls = {"n": 0}

    def odd_embedder(text: str):
        calls["n"] += 1
        # First calls (during ingest) return a real vector so chunks persist;
        # the query-time call returns a non-list.
        if "QUERYSENTINEL" in text:
            return "not-a-list"
        return [float(len(text)), 1.0, 0.0]

    svc = DatasetRagApplicationService(
        embedder=odd_embedder,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=False,
        vector_index_backend=backend,
    )
    svc.ingest_document(
        dataset_id="ds",
        text="policy content here for fallback",
        source="policy.md",
        chunk_strategy="fixed",
        chunk_size=200,
    )
    r = svc.query(dataset_id="ds", query="QUERYSENTINEL policy")
    assert r["success"] is True
    assert r["vector_backend_used"] is False


# ---------------------------------------------------------------------------
# _build_dataset_vector_index_backend: pgvector dimension parse error (1516-1517)
# ---------------------------------------------------------------------------


def test_build_pgvector_invalid_dimension_defaults_to_256(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASET_RAG_PGVECTOR_DATABASE_URL", "postgresql://rag/db")
    monkeypatch.setenv("DATASET_RAG_PGVECTOR_DIMENSION", "not-an-int")
    with patch.object(mod, "DatasetVectorPgIndex") as mock_pg:
        backend = _build_dataset_vector_index_backend(
            backend_name="pgvector",
            storage_path=tmp_path / "store.json",
            vector_index_path=None,
        )
    mock_pg.assert_called_once_with("postgresql://rag/db", dimension=256)
    assert backend is mock_pg.return_value


# ---------------------------------------------------------------------------
# _embedding_metadata: float-conversion failure branch (1837-1838)
# ---------------------------------------------------------------------------


def test_embedding_metadata_non_numeric_values_returns_empty():
    def bad_values(_text):
        return ["a", "b", "c"]  # list-but-non-numeric -> float() raises ValueError

    assert _embedding_metadata(bad_values, "text") == {}


# ---------------------------------------------------------------------------
# _metadata_matches: scalar mismatch final return False (line 1911)
# ---------------------------------------------------------------------------


def test_metadata_matches_scalar_mismatch_returns_false():
    chunk = RetrievedChunk(
        text="t",
        score=1.0,
        source="s",
        chunk_index=0,
        char_start=0,
        char_end=1,
        metadata={"doc_type": "policy"},
    )
    assert _metadata_matches(chunk, {"doc_type": "manual"}) is False
    assert _metadata_matches(chunk, {"doc_type": "policy"}) is True
