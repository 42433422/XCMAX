from __future__ import annotations

"""Branch-coverage supplement for dataset_rag_app_service.py.

Targets the 97 missing branches across ingest_document, delete_document,
diff_versions, rollback_document_version, start_rebuild_index,
cancel_rebuild_job, get_rebuild_job, status, query, answer, and helpers.
"""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.dataset_rag_app_service import (
    DatasetAccessContext,
    DatasetRagApplicationService,
    DatasetRebuildJob,
    _build_dataset_vector_index_backend,
    _chunk_to_dict,
    _clean_key,
    _coerce_access_context,
    _deterministic_answer,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _embedding_metadata,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _filter_chunks,
    _has_dataset_permission,
    _metadata_matches,
    _rebuild_job_from_dict,
    _rerank_chunks,
    _resolve_max_concurrent_rebuild_jobs,
    _resolve_tenant_for_access,
    _stable_document_id,
    _tokenize_for_rerank,
    reset_dataset_rag_app_service_for_tests,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedder():
    """Return a trivial deterministic embedder (no real ML)."""

    def embedder(text: str) -> list[float]:
        h = hash(text) % (2**16)
        return [float(h % 256) / 255.0] * 8

    return embedder


def _make_svc(
    tmp_path: Path, *, workers: bool = False, embedder=None
) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        embedder=embedder or _make_embedder(),
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=workers,
        vector_index_backend_name="none",
    )


def _ingest(
    svc: DatasetRagApplicationService,
    dataset_id: str = "ds1",
    text: str = "hello world content here",
) -> dict:
    return svc.ingest_document(
        dataset_id=dataset_id,
        text=text,
        chunk_strategy="fixed",
        chunk_size=100,
        chunk_overlap=0,
    )


# ---------------------------------------------------------------------------
# 1. ingest_document – branch coverage
# ---------------------------------------------------------------------------


class TestIngestDocument:
    def test_inline_text_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = _ingest(svc)
        assert r["success"] is True
        assert r["chunk_count"] >= 1

    def test_empty_text_and_no_file_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(dataset_id="ds", text="", file_path="")
        assert r["success"] is False

    def test_text_only_whitespace_empty(self, tmp_path):
        """text.strip() == '' AND file_path also empty → error."""
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(dataset_id="ds", text="   ", file_path="")
        assert r["success"] is False

    def test_file_path_with_txt(self, tmp_path):
        txt = tmp_path / "doc.txt"
        txt.write_text("file content is here", encoding="utf-8")
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(
            dataset_id="ds", file_path=str(txt), chunk_strategy="fixed", chunk_size=50
        )
        assert r["success"] is True

    def test_access_context_write_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="t1", permissions=frozenset(["dataset.read"])
        )
        r = svc.ingest_document(dataset_id="ds", text="hello", access_context=ctx)
        assert r["success"] is False
        assert "permission" in r.get("error_code", "")

    def test_version_explicit_int(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(
            dataset_id="ds", text="v2 content", version=2, chunk_strategy="fixed"
        )
        assert r["success"] is True
        assert r["document"]["version"] == 2

    def test_version_label_override(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(
            dataset_id="ds",
            text="content here x",
            version_label="release-1",
            chunk_strategy="fixed",
        )
        assert r["document"]["version_label"] == "release-1"

    def test_file_path_not_found_returns_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(dataset_id="ds", file_path=str(tmp_path / "missing.txt"))
        assert r["success"] is False

    def test_text_empty_after_extraction_error(self, tmp_path):
        """Empty extracted text branch."""
        txt = tmp_path / "empty.txt"
        txt.write_text("   ", encoding="utf-8")
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(dataset_id="ds", file_path=str(txt), chunk_strategy="fixed")
        assert r["success"] is False

    def test_access_context_as_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = {
            "actor_id": "u1",
            "tenant_id": "t1",
            "permissions": ["dataset.write", "dataset.read"],
            "is_admin": False,
        }
        r = svc.ingest_document(dataset_id="ds", text="hello from dict ctx", access_context=ctx)
        assert r["success"] is True

    def test_document_id_explicit(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(
            dataset_id="ds", text="explicit id doc", document_id="doc_custom_001"
        )
        assert r["document"]["document_id"] == "doc_custom_001"

    def test_semantic_chunking_branch(self, tmp_path):
        """Branch where chunk_strategy == 'semantic'."""
        svc = _make_svc(tmp_path)
        r = svc.ingest_document(
            dataset_id="ds", text="long content " * 20, chunk_strategy="semantic"
        )
        assert r["success"] is True


# ---------------------------------------------------------------------------
# 2. delete_document – branch coverage
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    def test_delete_nonexistent_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.delete_document("nonexistent", "doc_abc")
        assert r["success"] is False
        assert "not found" in r["message"]

    def test_delete_nonexistent_doc_in_existing_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.delete_document("ds", "doc_missing")
        assert r["success"] is False
        assert "not found" in r["message"]

    def test_delete_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.delete_document("ds", "x", access_context=ctx)
        assert r["success"] is False
        assert "permission" in r.get("error_code", "")

    def test_delete_tenant_mismatch(self, tmp_path):
        """Delete document when actor tenant != document tenant."""
        svc = _make_svc(tmp_path)
        ingest = svc.ingest_document(dataset_id="ds", text="secret data", tenant_id="tenant_a")
        doc_id = ingest["document"]["document_id"]
        ctx = DatasetAccessContext(
            actor_id="u",
            tenant_id="tenant_b",
            permissions=frozenset(["dataset.write", "dataset.read"]),
        )
        r = svc.delete_document("ds", doc_id, access_context=ctx)
        assert r["success"] is False

    def test_delete_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        ingest = _ingest(svc, "ds")
        doc_id = ingest["document"]["document_id"]
        r = svc.delete_document("ds", doc_id)
        assert r["success"] is True
        assert r["deleted_chunks"] >= 0


# ---------------------------------------------------------------------------
# 3. diff_versions – branch coverage
# ---------------------------------------------------------------------------


class TestDiffVersions:
    def test_diff_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.diff_versions(dataset_id="missing", source="x.txt", from_version=1, to_version=2)
        assert r["success"] is False
        assert "dataset not found" in r["message"]

    def test_diff_version_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.diff_versions(dataset_id="ds", source="no_source.txt", from_version=1, to_version=2)
        assert r["success"] is False
        assert "version not found" in r["message"]

    def test_diff_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.diff_versions(dataset_id="ds", source="x", from_version=1, access_context=ctx)
        assert r["success"] is False

    def test_diff_same_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.ingest_document(
            dataset_id="ds",
            text="same content text",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=1,
        )
        svc.ingest_document(
            dataset_id="ds",
            text="same content text",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=2,
        )
        r = svc.diff_versions(dataset_id="ds", source="doc.txt", from_version=1, to_version=2)
        assert r["success"] is True

    def test_diff_different_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.ingest_document(
            dataset_id="ds",
            text="version one content text here",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=1,
        )
        svc.ingest_document(
            dataset_id="ds",
            text="version two content text different",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=2,
        )
        r = svc.diff_versions(dataset_id="ds", source="doc.txt", from_version=1, to_version=2)
        assert r["success"] is True
        assert r["changed"] is True


# ---------------------------------------------------------------------------
# 4. rollback_document_version – branch coverage
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.rollback_document_version(dataset_id="nope", source="x", target_version=1)
        assert r["success"] is False

    def test_rollback_version_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.rollback_document_version(dataset_id="ds", source="nope.txt", target_version=99)
        assert r["success"] is False

    def test_rollback_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.rollback_document_version(
            dataset_id="ds", source="x", target_version=1, access_context=ctx
        )
        assert r["success"] is False

    def test_rollback_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.ingest_document(
            dataset_id="ds",
            text="original version text",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=1,
        )
        svc.ingest_document(
            dataset_id="ds",
            text="updated version text different content",
            source="doc.txt",
            chunk_strategy="fixed",
            chunk_size=200,
            version=2,
        )
        r = svc.rollback_document_version(dataset_id="ds", source="doc.txt", target_version=1)
        assert r["success"] is True


# ---------------------------------------------------------------------------
# 5. start_rebuild_index – branch coverage
# ---------------------------------------------------------------------------


class TestStartRebuildIndex:
    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.start_rebuild_index(dataset_id="missing")
        assert r["success"] is False

    def test_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.start_rebuild_index(dataset_id="ds", access_context=ctx)
        assert r["success"] is False

    def test_foreground_rebuild(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.start_rebuild_index(dataset_id="ds", background=False)
        assert r["success"] is True
        assert r["background"] is False

    def test_background_rebuild_workers_disabled(self, tmp_path):
        """background=True but workers disabled → job still queued."""
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc, "ds")
        r = svc.start_rebuild_index(dataset_id="ds", background=True)
        assert r["success"] is True
        assert r["background"] is True

    def test_rebuild_with_metadata_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.start_rebuild_index(
            dataset_id="ds", background=False, metadata_filter={"source": "inline"}
        )
        assert r["success"] is True


# ---------------------------------------------------------------------------
# 6. cancel_rebuild_job – branch coverage
# ---------------------------------------------------------------------------


class TestCancelRebuildJob:
    def _create_queued_job(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc, "ds")
        r = svc.start_rebuild_index(dataset_id="ds", background=True)
        return svc, r["job"]["job_id"]

    def test_cancel_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.cancel_rebuild_job("ds", "jid", access_context=ctx)
        assert r["success"] is False

    def test_cancel_job_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.cancel_rebuild_job("ds", "nonexistent_job")
        assert r["success"] is False

    def test_cancel_queued_job(self, tmp_path):
        svc, job_id = self._create_queued_job(tmp_path)
        r = svc.cancel_rebuild_job("ds", job_id)
        assert r["success"] is True
        assert r["job"]["status"] == "cancelled"

    def test_cancel_already_terminal(self, tmp_path):
        """Cancelling a completed job returns success with message."""
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        result = svc.start_rebuild_index(dataset_id="ds", background=False)
        job_id = result["job"]["job_id"]
        r = svc.cancel_rebuild_job("ds", job_id)
        assert r["success"] is True
        assert "already" in r.get("message", "")

    def test_cancel_running_job_fails(self, tmp_path):
        """Cancelling a 'running' job is not allowed."""
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        # Manually put a job in running state
        with svc._lock:
            from app.application.dataset_rag_app_service import _DatasetState, _utc_now_iso

            state = svc._datasets["ds"]
            job = DatasetRebuildJob(job_id="running_job", dataset_id="ds", status="running")
            state.rebuild_jobs["running_job"] = job
        r = svc.cancel_rebuild_job("ds", "running_job")
        assert r["success"] is False
        assert "cancel" in r["message"].lower() or "queued" in r["message"].lower()


# ---------------------------------------------------------------------------
# 7. get_rebuild_job – branch coverage
# ---------------------------------------------------------------------------


class TestGetRebuildJob:
    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.get_rebuild_job("ds", "jid", access_context=ctx)
        assert r["success"] is False

    def test_job_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.get_rebuild_job("ds", "ghost_job")
        assert r["success"] is False

    def test_job_found(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc, "ds")
        start = svc.start_rebuild_index(dataset_id="ds", background=True)
        job_id = start["job"]["job_id"]
        r = svc.get_rebuild_job("ds", job_id)
        assert r["success"] is True

    def test_tenant_mismatch_denied(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        svc.ingest_document(dataset_id="ds", text="tenant content", tenant_id="t_a")
        # start rebuild for t_a
        start = svc.start_rebuild_index(dataset_id="ds", tenant_id="t_a", background=True)
        job_id = start["job"]["job_id"]
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="t_b", permissions=frozenset(["dataset.read"])
        )
        r = svc.get_rebuild_job("ds", job_id, access_context=ctx)
        assert r["success"] is False


# ---------------------------------------------------------------------------
# 8. status – branch coverage
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_all_datasets(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds1")
        _ingest(svc, "ds2")
        r = svc.status()
        assert r["success"] is True
        assert "datasets" in r

    def test_status_single_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "my-dataset")
        r = svc.status("my-dataset")
        assert r["success"] is True
        assert r["document_count"] >= 1

    def test_status_nonexistent_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.status("ghost-dataset")
        assert r["success"] is True
        assert r["document_count"] == 0

    def test_status_with_tenant_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.ingest_document(dataset_id="ds", text="t1 content here", tenant_id="t1")
        svc.ingest_document(dataset_id="ds", text="t2 content here", tenant_id="t2")
        r = svc.status("ds", tenant_id="t1")
        assert r["success"] is True
        assert r["document_count"] >= 1

    def test_status_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.status("ds", access_context=ctx)
        assert r["success"] is False


# ---------------------------------------------------------------------------
# 9. query – branch coverage
# ---------------------------------------------------------------------------


class TestQuery:
    def test_empty_query_returns_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds")
        r = svc.query(dataset_id="ds", query="")
        assert r["success"] is False
        assert "query is required" in r["message"]

    def test_query_no_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.query(dataset_id="empty-dataset", query="hello")
        assert r["success"] is True
        assert r["chunks"] == []

    def test_query_returns_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds", "the deployment policy says use XCauto model always")
        r = svc.query(dataset_id="ds", query="deployment policy")
        assert r["success"] is True

    def test_query_with_rerank(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds", "policy for deployment of ai models in production")
        r = svc.query(dataset_id="ds", query="ai policy", rerank=True)
        assert r["success"] is True

    def test_query_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.query(dataset_id="ds", query="hello", access_context=ctx)
        assert r["success"] is False

    def test_query_with_version_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.ingest_document(
            dataset_id="ds",
            text="version one content policy",
            source="doc.txt",
            version=1,
            chunk_strategy="fixed",
        )
        r = svc.query(dataset_id="ds", query="policy", version="latest")
        assert r["success"] is True

    def test_query_with_metadata_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds", "content for metadata filter test here")
        r = svc.query(dataset_id="ds", query="content", metadata_filter={"source": "inline"})
        assert r["success"] is True

    def test_query_vector_backend_error_falls_back(self, tmp_path):
        """When vector backend query raises, falls back to in-memory."""
        mock_backend = MagicMock()
        mock_backend.replace_dataset.return_value = 0
        mock_backend.query.side_effect = OSError("db down")
        mock_backend.status.return_value = {
            "backend": "mock",
            "persistent": False,
            "chunk_count": 0,
        }
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend=mock_backend,
        )
        _ingest(svc, "ds")
        r = svc.query(dataset_id="ds", query="hello")
        assert r["success"] is True


# ---------------------------------------------------------------------------
# 10. answer – branch coverage
# ---------------------------------------------------------------------------


class TestAnswer:
    def test_answer_no_chunks_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.answer(dataset_id="empty-ds", query="anything")
        assert r.get("answer") == ""

    def test_answer_with_llm_call(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds", "the XCauto policy deployment says always use the platform model")

        def fake_llm(query: str, prompt: str) -> str:
            return f"Based on context: {prompt[:50]}"

        r = svc.answer(dataset_id="ds", query="policy", llm_call=fake_llm)
        assert r["success"] is True
        assert r["answer"]

    def test_answer_deterministic_without_llm(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, "ds", "content about the product deployment requirements policy")
        r = svc.answer(dataset_id="ds", query="deployment")
        assert r["success"] is True
        assert r["answer"]

    def test_answer_access_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t", permissions=frozenset())
        r = svc.answer(dataset_id="ds", query="hello", access_context=ctx)
        assert r["success"] is False


# ---------------------------------------------------------------------------
# 11. drain_rebuild_queue
# ---------------------------------------------------------------------------


class TestDrainRebuildQueue:
    def test_drain_empty_queue(self, tmp_path):
        svc = _make_svc(tmp_path)
        r = svc.drain_rebuild_queue()
        assert r["drained_count"] == 0

    def test_drain_with_limit(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc, "ds")
        svc.start_rebuild_index(dataset_id="ds", background=True)
        r = svc.drain_rebuild_queue(max_jobs=1)
        assert r["success"] is True
        assert r["drained_count"] >= 1


# ---------------------------------------------------------------------------
# 12. _resolve_tenant_for_access helper branches
# ---------------------------------------------------------------------------


class TestResolveTenantForAccess:
    def test_no_context_no_tenant_returns_default(self):
        tenant, denied = _resolve_tenant_for_access(
            None,
            "",
            required_permission="dataset.read",
            default_without_context="default",
            dataset_id="ds",
        )
        assert denied is None
        assert tenant == "default"

    def test_no_context_with_requested_tenant(self):
        tenant, denied = _resolve_tenant_for_access(
            None,
            "my_tenant",
            required_permission="dataset.read",
            default_without_context="default",
            dataset_id="ds",
        )
        assert tenant == "my_tenant"
        assert denied is None

    def test_context_no_actor_tenant_denied(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="", permissions=frozenset(["dataset.read"])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx, "", required_permission="dataset.read", default_without_context="", dataset_id="ds"
        )
        assert denied is not None

    def test_context_admin_uses_requested(self):
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t_admin", is_admin=True)
        tenant, denied = _resolve_tenant_for_access(
            ctx,
            "t_requested",
            required_permission="dataset.write",
            default_without_context="",
            dataset_id="ds",
        )
        assert denied is None
        assert tenant == "t_requested"

    def test_context_tenant_mismatch_denied(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="t1", permissions=frozenset(["dataset.write"])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx,
            "t2",
            required_permission="dataset.write",
            default_without_context="",
            dataset_id="ds",
        )
        assert denied is not None

    def test_context_no_permission_denied(self):
        ctx = DatasetAccessContext(actor_id="u", tenant_id="t1", permissions=frozenset())
        _, denied = _resolve_tenant_for_access(
            ctx, "", required_permission="dataset.read", default_without_context="", dataset_id="ds"
        )
        assert denied is not None


# ---------------------------------------------------------------------------
# 13. _ensure_tenant_allowed helper branches
# ---------------------------------------------------------------------------


class TestEnsureTenantAllowed:
    def test_no_context_allowed(self):
        r = _ensure_tenant_allowed(None, "t1", dataset_id="ds", operation="op")
        assert r is None

    def test_admin_allowed(self):
        ctx = DatasetAccessContext(is_admin=True)
        r = _ensure_tenant_allowed(ctx, "t1", dataset_id="ds", operation="op")
        assert r is None

    def test_actor_no_tenant_denied(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="", permissions=frozenset(["dataset.write"])
        )
        r = _ensure_tenant_allowed(ctx, "t1", dataset_id="ds", operation="op")
        assert r is not None

    def test_target_no_tenant_denied(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="t1", permissions=frozenset(["dataset.write"])
        )
        r = _ensure_tenant_allowed(ctx, "", dataset_id="ds", operation="op")
        assert r is not None

    def test_tenant_mismatch_denied(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="t1", permissions=frozenset(["dataset.write"])
        )
        r = _ensure_tenant_allowed(ctx, "t2", dataset_id="ds", operation="op")
        assert r is not None

    def test_same_tenant_allowed(self):
        ctx = DatasetAccessContext(
            actor_id="u", tenant_id="t1", permissions=frozenset(["dataset.write"])
        )
        r = _ensure_tenant_allowed(ctx, "t1", dataset_id="ds", operation="op")
        assert r is None


# ---------------------------------------------------------------------------
# 14. _coerce_access_context – permission parsing branches
# ---------------------------------------------------------------------------


class TestCoerceAccessContext:
    def test_none_returns_none(self):
        assert _coerce_access_context(None) is None

    def test_dataclass_passthrough(self):
        ctx = DatasetAccessContext(actor_id="u")
        assert _coerce_access_context(ctx) is ctx

    def test_dict_with_string_permissions(self):
        ctx = _coerce_access_context({"actor_id": "u", "permissions": "dataset.read,dataset.write"})
        assert "dataset.read" in ctx.permissions

    def test_dict_with_list_permissions(self):
        ctx = _coerce_access_context({"actor_id": "u", "permissions": ["dataset.read"]})
        assert "dataset.read" in ctx.permissions

    def test_dict_with_no_permissions(self):
        ctx = _coerce_access_context({"actor_id": "u"})
        assert ctx.permissions == frozenset()

    def test_dict_is_admin_flag(self):
        ctx = _coerce_access_context({"actor_id": "u", "admin": True})
        assert ctx.is_admin is True


# ---------------------------------------------------------------------------
# 15. _has_dataset_permission – branches
# ---------------------------------------------------------------------------


class TestHasDatasetPermission:
    def test_none_context_always_true(self):
        assert _has_dataset_permission(None, "dataset.read") is True

    def test_admin_flag_true(self):
        ctx = DatasetAccessContext(is_admin=True)
        assert _has_dataset_permission(ctx, "dataset.write") is True

    def test_admin_permission_true(self):
        ctx = DatasetAccessContext(permissions=frozenset(["dataset.admin"]))
        assert _has_dataset_permission(ctx, "dataset.write") is True

    def test_exact_permission_true(self):
        ctx = DatasetAccessContext(permissions=frozenset(["dataset.read"]))
        assert _has_dataset_permission(ctx, "dataset.read") is True

    def test_wildcard_permission_true(self):
        ctx = DatasetAccessContext(permissions=frozenset(["*"]))
        assert _has_dataset_permission(ctx, "dataset.write") is True

    def test_prefix_wildcard(self):
        ctx = DatasetAccessContext(permissions=frozenset(["dataset.*"]))
        assert _has_dataset_permission(ctx, "dataset.read") is True

    def test_no_permission_false(self):
        ctx = DatasetAccessContext(permissions=frozenset())
        assert _has_dataset_permission(ctx, "dataset.read") is False


# ---------------------------------------------------------------------------
# 16. _filter_chunks branches (version filters)
# ---------------------------------------------------------------------------


class TestFilterChunks:
    def _chunk(self, **kw) -> RetrievedChunk:
        defaults = {
            "text": "t",
            "score": 1.0,
            "source": "s",
            "chunk_index": 0,
            "char_start": 0,
            "char_end": 1,
        }
        defaults.update(kw)
        return RetrievedChunk(**defaults)

    def test_no_filters_returns_all(self):
        chunks = [self._chunk(metadata={"tenant_id": "t1"})]
        result = _filter_chunks(chunks, tenant_id="", version="", metadata_filter={})
        assert len(result) == 1

    def test_tenant_filter(self):
        c1 = self._chunk(metadata={"tenant_id": "t1"})
        c2 = self._chunk(metadata={"tenant_id": "t2"})
        result = _filter_chunks([c1, c2], tenant_id="t1", version="", metadata_filter={})
        assert len(result) == 1

    def test_version_numeric(self):
        c1 = self._chunk(metadata={"document_version": 1})
        c2 = self._chunk(metadata={"document_version": 2})
        result = _filter_chunks([c1, c2], tenant_id="", version="1", metadata_filter={})
        assert len(result) == 1

    def test_version_v_prefix(self):
        c1 = self._chunk(metadata={"document_version": 1, "version_label": "v1"})
        result = _filter_chunks([c1], tenant_id="", version="v1", metadata_filter={})
        assert len(result) == 1

    def test_version_latest(self):
        c1 = self._chunk(metadata={"document_version": 1, "tenant_id": "t", "source": "s"})
        c2 = self._chunk(metadata={"document_version": 2, "tenant_id": "t", "source": "s"})
        result = _filter_chunks([c1, c2], tenant_id="", version="latest", metadata_filter={})
        # only latest version 2 survives
        assert all(c.metadata["document_version"] == 2 for c in result)

    def test_metadata_filter_list_value(self):
        c1 = self._chunk(metadata={"tag": "a"})
        c2 = self._chunk(metadata={"tag": "b"})
        result = _filter_chunks([c1, c2], tenant_id="", version="", metadata_filter={"tag": ["a"]})
        assert len(result) == 1

    def test_metadata_filter_dict_value(self):
        c1 = self._chunk(metadata={"nested": {"k": "v"}})
        c2 = self._chunk(metadata={"nested": {"k": "x"}})
        result = _filter_chunks(
            [c1, c2], tenant_id="", version="", metadata_filter={"nested": {"k": "v"}}
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 17. _rerank_chunks
# ---------------------------------------------------------------------------


class TestRerankChunks:
    def _chunk(self, text, score=1.0) -> RetrievedChunk:
        return RetrievedChunk(
            text=text, score=score, source="s", chunk_index=0, char_start=0, char_end=len(text)
        )

    def test_rerank_empty_query_terms(self):
        chunks = [self._chunk("hello world")]
        result = _rerank_chunks("   ", chunks, top_k=5)
        assert result == chunks[:5]

    def test_rerank_with_exact_match_bonus(self):
        c1 = self._chunk("deployment policy for production")
        c2 = self._chunk("unrelated content")
        result = _rerank_chunks("deployment policy", [c1, c2], top_k=5)
        assert result[0].text == c1.text

    def test_rerank_already_has_rerank_in_source(self):
        chunk = RetrievedChunk(
            text="hello world policy",
            score=1.0,
            source="s+rerank",
            chunk_index=0,
            char_start=0,
            char_end=5,
        )
        result = _rerank_chunks("hello", [chunk], top_k=5)
        # source should not double-append rerank
        assert "+rerank" in result[0].source
        assert result[0].source.count("rerank") == 1


# ---------------------------------------------------------------------------
# 18. _embedding_metadata branches
# ---------------------------------------------------------------------------


class TestEmbeddingMetadata:
    def test_none_embedder_returns_empty(self):
        assert _embedding_metadata(None, "text") == {}

    def test_embedder_exception_returns_empty(self):
        def bad_embedder(t):
            raise OSError("fail")

        assert _embedding_metadata(bad_embedder, "text") == {}

    def test_empty_embedding_list_returns_empty(self):
        def empty_embedder(t):
            return []

        assert _embedding_metadata(empty_embedder, "text") == {}

    def test_non_list_embedding_returns_empty(self):
        def non_list_embedder(t):
            return "not a list"

        assert _embedding_metadata(non_list_embedder, "text") == {}

    def test_valid_embedding_returned(self):
        def good_embedder(t):
            return [0.1, 0.2, 0.3]

        result = _embedding_metadata(good_embedder, "hello")
        assert "_embedding" in result
        assert result["_embedding"] == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# 19. _build_dataset_vector_index_backend branches
# ---------------------------------------------------------------------------


class TestBuildVectorIndexBackend:
    def test_none_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="none", storage_path=tmp_path, vector_index_path=None
        )
        assert result is None

    def test_disabled_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="disabled", storage_path=tmp_path, vector_index_path=None
        )
        assert result is None

    def test_sqlite_with_explicit_path(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="sqlite", storage_path=tmp_path, vector_index_path=tmp_path / "idx.db"
        )
        assert result is not None

    def test_sqlite_without_explicit_path(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="sqlite", storage_path=tmp_path, vector_index_path=None
        )
        assert result is not None

    def test_unknown_backend_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unsupported"):
            _build_dataset_vector_index_backend(
                backend_name="badbackend", storage_path=tmp_path, vector_index_path=None
            )


# ---------------------------------------------------------------------------
# 20. _resolve_max_concurrent_rebuild_jobs
# ---------------------------------------------------------------------------


class TestResolveMaxConcurrentRebuildJobs:
    def test_explicit_value(self):
        assert _resolve_max_concurrent_rebuild_jobs(3) == 3

    def test_explicit_clamped_high(self):
        assert _resolve_max_concurrent_rebuild_jobs(100) == 8

    def test_explicit_clamped_low(self):
        assert _resolve_max_concurrent_rebuild_jobs(0) == 1

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", "4")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 4

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        monkeypatch.setenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", "2")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 2

    def test_no_env_default(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(None) == 1


# ---------------------------------------------------------------------------
# 21. Persistence load / round-trip
# ---------------------------------------------------------------------------


class TestPersistenceRoundTrip:
    def test_state_survives_reload(self, tmp_path):
        storage = tmp_path / "store.json"
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        _ingest(svc, "ds", "persist content here")

        svc2 = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        r = svc2.status("ds")
        assert r["document_count"] >= 1

    def test_corrupt_storage_file_resets(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text("not valid json !!!", encoding="utf-8")
        svc = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        # should not raise; starts with empty datasets
        r = svc.status()
        assert r["success"] is True


# ---------------------------------------------------------------------------
# 22. get_dataset_rag_app_service singleton
# ---------------------------------------------------------------------------


def test_singleton_reset(tmp_path):
    reset_dataset_rag_app_service_for_tests()
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    with (
        patch(
            "app.application.dataset_rag_app_service._default_storage_path",
            return_value=tmp_path / "s.json",
        ),
        patch(
            "app.application.dataset_rag_app_service._build_dataset_vector_index_backend",
            return_value=None,
        ),
    ):
        svc1 = get_dataset_rag_app_service()
        svc2 = get_dataset_rag_app_service()
        assert svc1 is svc2
    reset_dataset_rag_app_service_for_tests()


# ---------------------------------------------------------------------------
# 23. Misc helper functions
# ---------------------------------------------------------------------------


def test_clean_key_special_chars():
    assert _clean_key("hello world!", default="def") == "hello_world"


def test_clean_key_all_special():
    assert _clean_key("---", default="def") == "def"


def test_stable_document_id_deterministic():
    a = _stable_document_id("ds", "t", "src", 1, "text")
    b = _stable_document_id("ds", "t", "src", 1, "text")
    assert a == b
    assert a.startswith("doc_")


def test_document_from_dict_defaults():
    doc = _document_from_dict({"document_id": "d1", "source": "s", "parser": "p"})
    assert doc.version == 1
    assert doc.tenant_id == "default"


def test_rebuild_job_from_dict_defaults():
    job = _rebuild_job_from_dict({"job_id": "j1", "dataset_id": "ds"})
    assert job.status == "queued"
    assert job.max_attempts == 1


def test_chunk_to_dict_public_hides_underscore():
    chunk = RetrievedChunk(
        text="hello",
        score=1.0,
        source="s",
        chunk_index=0,
        char_start=0,
        char_end=5,
        metadata={"_embedding": [0.1], "public_key": "v"},
    )
    d = _chunk_to_dict(chunk, public=True)
    assert "_embedding" not in d["metadata"]
    assert "public_key" in d["metadata"]


def test_dict_to_retrieved_chunk_page_handling():
    data = {"text": "t", "page": 3}
    chunk = _dict_to_retrieved_chunk(data)
    assert chunk.page == 3

    data2 = {"text": "t", "page": "not-int"}
    chunk2 = _dict_to_retrieved_chunk(data2)
    assert chunk2.page is None


def test_deterministic_answer_empty_chunks():
    result = _deterministic_answer("q", [])
    assert result == ""


def test_deterministic_answer_long_excerpt():
    chunk = RetrievedChunk(
        text="x" * 400, score=1.0, source="s", chunk_index=0, char_start=0, char_end=400
    )
    result = _deterministic_answer("q", [chunk])
    assert "..." in result


def test_tokenize_for_rerank():
    tokens = _tokenize_for_rerank("Hello World! 123")
    assert "hello" in tokens
    assert "world" in tokens


def test_metadata_matches_dict_value_not_dict_actual():
    chunk = RetrievedChunk(
        text="t",
        score=1.0,
        source="s",
        chunk_index=0,
        char_start=0,
        char_end=1,
        metadata={"nested": "not_a_dict"},
    )
    assert _metadata_matches(chunk, {"nested": {"k": "v"}}) is False
