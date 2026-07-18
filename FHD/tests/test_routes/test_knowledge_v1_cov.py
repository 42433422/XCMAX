"""Branch-coverage ramp for app.fastapi_routes.knowledge_v1.

Targets the 52 missing branches (58.1% → 75%+). Tests the small pure helpers
directly, then mocks the heavy app-layer dependencies (`AgentOrchestrator`,
`get_dataset_rag_app_service`, `_persy_memory_service`, audit_logger) so the
route handlers can be exercised without real RAG/agent infrastructure.

NOTE: ``app.infrastructure.rag`` must be mocked in ``sys.modules`` before the
module is imported — same pattern as ``test_knowledge_v1.py``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- Mock app.infrastructure.rag BEFORE importing knowledge_v1 --------------
_mock_rag = types.ModuleType("app.infrastructure.rag")
_mock_rag.HybridRetriever = MagicMock
_mock_rag.SemanticChunker = MagicMock
_mock_rag.RetrievedChunk = MagicMock
_mock_rag.get_default_embedder = MagicMock(return_value=None)
_mock_rag.is_rag_enabled = MagicMock(return_value=False)
_original_rag = sys.modules.get("app.infrastructure.rag")
sys.modules["app.infrastructure.rag"] = _mock_rag

from app.fastapi_routes import knowledge_v1 as kv  # noqa: E402

# Restore the original rag module so other tests aren't affected.
if _original_rag is not None:
    sys.modules["app.infrastructure.rag"] = _original_rag
else:
    del sys.modules["app.infrastructure.rag"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(headers: dict | None = None):
    return SimpleNamespace(
        headers=headers or {},
        url=SimpleNamespace(path="/api/knowledge/v1/test"),
        client=SimpleNamespace(host="127.0.0.1"),
    )


# ===========================================================================
# _ensure_bounded_metadata
# ===========================================================================


class TestEnsureBoundedMetadata:
    def test_simple_dict_passes(self):
        kv._ensure_bounded_metadata({"a": 1, "b": "two"})

    def test_list_passes(self):
        kv._ensure_bounded_metadata([1, 2, 3, {"nested": [1, 2]}])

    def test_scalar_passes(self):
        kv._ensure_bounded_metadata("hello")

    def test_none_passes(self):
        kv._ensure_bounded_metadata(None)

    def test_depth_exceeds_8_raises(self):
        nested = "leaf"
        for _ in range(9):
            nested = {"k": nested}
        with pytest.raises(ValueError, match="nesting exceeds 8 levels"):
            kv._ensure_bounded_metadata(nested)

    def test_dict_too_many_fields_raises(self):
        big = {f"k{i}": i for i in range(201)}
        with pytest.raises(ValueError, match="too many fields"):
            kv._ensure_bounded_metadata(big)

    def test_dict_key_too_long_raises(self):
        big_key = "x" * 201
        with pytest.raises(ValueError, match="key is too long"):
            kv._ensure_bounded_metadata({big_key: 1})

    def test_list_too_long_raises(self):
        big_list = list(range(1001))
        with pytest.raises(ValueError, match="list is too long"):
            kv._ensure_bounded_metadata(big_list)

    def test_tuple_too_long_raises(self):
        big_tuple = tuple(range(1001))
        with pytest.raises(ValueError, match="list is too long"):
            kv._ensure_bounded_metadata(big_tuple)

    def test_non_serializable_raises(self):
        # default=str calls str() on non-JSON types; a __str__ that raises
        # TypeError propagates and is rewrapped as "JSON serializable".
        class BadStr:
            def __str__(self):
                raise TypeError("no string for you")

        with pytest.raises(ValueError, match="JSON serializable"):
            kv._ensure_bounded_metadata({"obj": BadStr()})

    def test_bytes_exceed_max_raises(self):
        # Default max is 64KB; build a string just past that.
        big_value = "x" * (kv._DATASET_METADATA_MAX_BYTES + 100)
        with pytest.raises(ValueError, match="cannot exceed"):
            kv._ensure_bounded_metadata({"big": big_value})

    def test_custom_max_bytes(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            kv._ensure_bounded_metadata({"big": "x" * 200}, max_bytes=64)

    def test_nested_dict_in_list_passes(self):
        kv._ensure_bounded_metadata([{"a": [1, 2, {"b": "c"}]}])


# ===========================================================================
# _public_dataset_payload
# ===========================================================================


class TestPublicDatasetPayload:
    def test_scalar_returned_as_is(self):
        assert kv._public_dataset_payload("hello") == "hello"
        assert kv._public_dataset_payload(42) == 42
        assert kv._public_dataset_payload(None) is None

    def test_list_recursed(self):
        result = kv._public_dataset_payload([1, {"a": 1, "_hidden": 2}])
        assert result == [1, {"a": 1}]

    def test_dict_filters_underscore_keys(self):
        result = kv._public_dataset_payload({"a": 1, "_private": 2, "__dunder": 3})
        assert result == {"a": 1}

    def test_dict_filters_storage_keys(self):
        result = kv._public_dataset_payload(
            {
                "id": "x",
                "storage_path": "/secret",
                "file_path": "/secret",
                "vector_index_path": "/secret",
                "public_field": "ok",
            }
        )
        assert "storage_path" not in result
        assert "file_path" not in result
        assert "vector_index_path" not in result
        assert result["id"] == "x"
        assert result["public_field"] == "ok"

    def test_nested_dict_recursed(self):
        result = kv._public_dataset_payload({"outer": {"_inner": 1, "keep": 2}, "_drop": 3})
        assert result == {"outer": {"keep": 2}}

    def test_empty_dict(self):
        assert kv._public_dataset_payload({}) == {}

    def test_empty_list(self):
        assert kv._public_dataset_payload([]) == []


# ===========================================================================
# IngestRequest.validate_chunk_window
# ===========================================================================


class TestIngestRequestValidator:
    def test_semantic_strategy_allows_any_overlap(self):
        # chunk_overlap is capped at 500 by Field; pick the max valid value.
        req = kv.IngestRequest(text="hi", chunk_strategy="semantic", chunk_overlap=500)
        assert req.chunk_strategy == "semantic"
        assert req.chunk_overlap == 500

    def test_fixed_strategy_overlap_ge_size_raises(self):
        with pytest.raises(ValueError, match="chunk_overlap must be smaller"):
            kv.IngestRequest(text="hi", chunk_strategy="fixed", chunk_size=100, chunk_overlap=100)

    def test_fixed_strategy_overlap_gt_size_raises(self):
        with pytest.raises(ValueError, match="chunk_overlap must be smaller"):
            kv.IngestRequest(text="hi", chunk_strategy="fixed", chunk_size=100, chunk_overlap=200)

    def test_fixed_strategy_valid_overlap(self):
        req = kv.IngestRequest(text="hi", chunk_strategy="fixed", chunk_size=500, chunk_overlap=50)
        assert req.chunk_size == 500


# ===========================================================================
# DatasetDocumentIngestRequest validators
# ===========================================================================


class TestDatasetDocumentIngestRequestValidator:
    def test_text_only_passes(self):
        req = kv.DatasetDocumentIngestRequest(text="hello")
        assert req.text == "hello"

    def test_file_path_only_passes(self):
        req = kv.DatasetDocumentIngestRequest(file_path="/tmp/x.txt")
        assert req.file_path == "/tmp/x.txt"

    def test_neither_text_nor_file_raises(self):
        with pytest.raises(ValueError, match="text or file_path is required"):
            kv.DatasetDocumentIngestRequest(text="", file_path="")

    def test_whitespace_only_text_treated_as_empty(self):
        with pytest.raises(ValueError, match="text or file_path is required"):
            kv.DatasetDocumentIngestRequest(text="   ", file_path="  ")

    def test_fixed_strategy_overlap_ge_size_raises(self):
        with pytest.raises(ValueError, match="chunk_overlap must be smaller"):
            kv.DatasetDocumentIngestRequest(
                text="hi", chunk_strategy="fixed", chunk_size=100, chunk_overlap=200
            )

    def test_metadata_validator_runs(self):
        # Use a metadata that exceeds limits.
        with pytest.raises(ValueError, match="too many fields"):
            kv.DatasetDocumentIngestRequest(text="hi", metadata={f"k{i}": i for i in range(201)})


# ===========================================================================
# DatasetQueryRequest / DatasetRollbackRequest / DatasetRebuildRequest metadata validators
# ===========================================================================


class TestDatasetMetadataValidators:
    def test_dataset_query_metadata_filter_too_many_fields(self):
        with pytest.raises(ValueError, match="too many fields"):
            kv.DatasetQueryRequest(query="q", metadata_filter={f"k{i}": i for i in range(201)})

    def test_dataset_rollback_metadata_too_many_fields(self):
        with pytest.raises(ValueError, match="too many fields"):
            kv.DatasetRollbackRequest(
                source="s",
                target_version="v1",
                metadata={f"k{i}": i for i in range(201)},
            )

    def test_dataset_rebuild_metadata_filter_too_many_fields(self):
        with pytest.raises(ValueError, match="too many fields"):
            kv.DatasetRebuildRequest(metadata_filter={f"k{i}": i for i in range(201)})


# ===========================================================================
# PersyMemoryMutationRequest.validate_value
# ===========================================================================


class TestPersyMemoryMutationRequestValue:
    def test_none_value_passes(self):
        req = kv.PersyMemoryMutationRequest(value=None)
        assert req.value is None

    def test_simple_value_passes(self):
        req = kv.PersyMemoryMutationRequest(value="hello")
        assert req.value == "hello"

    def test_dict_value_passes(self):
        req = kv.PersyMemoryMutationRequest(value={"k": 1})
        assert req.value == {"k": 1}

    def test_value_too_large_raises(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            kv.PersyMemoryMutationRequest(value="x" * (16 * 1024 + 100))


# ===========================================================================
# _persy_dataset_error
# ===========================================================================


class TestPersyDatasetError:
    def test_persy_id_returns_none(self):
        assert kv._persy_dataset_error(kv._PERSY_DATASET_ID) is None

    def test_persy_id_with_whitespace_returns_none(self):
        assert kv._persy_dataset_error("  persy-knowledge  ") is None

    def test_other_id_returns_404(self):
        resp = kv._persy_dataset_error("other-dataset")
        assert resp is not None
        assert resp.status_code == 404
        assert resp.body.decode().find("persy_dataset_required") >= 0

    def test_empty_id_returns_404(self):
        resp = kv._persy_dataset_error("")
        assert resp is not None
        assert resp.status_code == 404

    def test_none_id_returns_404(self):
        resp = kv._persy_dataset_error(None)
        assert resp is not None
        assert resp.status_code == 404


# ===========================================================================
# _persy_memory_response
# ===========================================================================


class TestPersyMemoryResponse:
    def test_success_returns_200(self):
        payload = {"success": True, "memory": {"memory_id": "m1"}}
        with patch("app.utils.audit_logger.audit_log") as mock_audit:
            resp = kv._persy_memory_response(payload, request=_request(), action="confirm")
        assert resp.status_code == 200
        mock_audit.assert_called_once()

    def test_failure_returns_400_by_default(self):
        payload = {"success": False, "error_code": "some_other"}
        with patch("app.utils.audit_logger.audit_log"):
            resp = kv._persy_memory_response(payload, request=_request(), action="reject")
        assert resp.status_code == 400

    def test_permission_denied_returns_403(self):
        payload = {"success": False, "error_code": "dataset_permission_denied"}
        with patch("app.utils.audit_logger.audit_log"):
            resp = kv._persy_memory_response(payload, request=_request(), action="confirm")
        assert resp.status_code == 403

    def test_scope_missing_returns_403(self):
        payload = {"success": False, "error_code": "persy_memory_scope_missing"}
        with patch("app.utils.audit_logger.audit_log"):
            resp = kv._persy_memory_response(payload, request=_request(), action="confirm")
        assert resp.status_code == 403

    def test_not_found_returns_404(self):
        payload = {"success": False, "error_code": "persy_memory_not_found"}
        with patch("app.utils.audit_logger.audit_log"):
            resp = kv._persy_memory_response(payload, request=_request(), action="delete")
        assert resp.status_code == 404

    def test_audit_logger_failure_swallowed(self):
        payload = {"success": True, "memory": {"memory_id": "m1"}}
        with patch("app.utils.audit_logger.audit_log", side_effect=RuntimeError("audit down")):
            # Should not raise.
            resp = kv._persy_memory_response(payload, request=_request(), action="confirm")
        assert resp.status_code == 200

    def test_audit_actor_from_access_context(self):
        payload = {"success": True, "memory": {"memory_id": "m1"}}
        access = SimpleNamespace(actor_id="actor-7")
        with (
            patch("app.utils.audit_logger.audit_log") as mock_audit,
            patch.object(kv, "_dataset_access_context_from_request", return_value=access),
        ):
            kv._persy_memory_response(payload, request=_request(), action="confirm")
        args, kwargs = mock_audit.call_args
        # Second positional arg is actor_id.
        assert args[1] == "actor-7"

    def test_memory_payload_with_non_dict_memory(self):
        # memory field is not a dict → memory_id empty string.
        payload = {"success": True, "memory": "not-a-dict"}
        with patch("app.utils.audit_logger.audit_log") as mock_audit:
            resp = kv._persy_memory_response(payload, request=_request(), action="confirm")
        assert resp.status_code == 200
        args, _ = mock_audit.call_args
        assert args[3]["memory_id"] == ""


# ===========================================================================
# _merge_persy_recall
# ===========================================================================


class TestMergePersyRecall:
    def test_non_persy_dataset_returns_payload_unchanged(self):
        payload = {"success": True, "chunks": [{"x": 1}]}
        result = kv._merge_persy_recall(payload, request=_request(), params={"dataset_id": "other"})
        assert result is payload

    def test_persy_dataset_but_payload_not_success_returns_unchanged(self):
        payload = {"success": False, "chunks": []}
        result = kv._merge_persy_recall(
            payload,
            request=_request(),
            params={"dataset_id": kv._PERSY_DATASET_ID, "query": "q"},
        )
        assert result is payload

    def test_persy_dataset_empty_query_returns_unchanged(self):
        payload = {"success": True, "chunks": []}
        result = kv._merge_persy_recall(
            payload,
            request=_request(),
            params={"dataset_id": kv._PERSY_DATASET_ID, "query": "  "},
        )
        assert result is payload

    def test_persy_memory_failure_sets_error_code(self):
        payload = {"success": True, "chunks": [], "citations": [], "answer": "ans"}
        mem_svc = MagicMock()
        mem_svc.query.return_value = {
            "success": False,
            "error_code": "persy_memory_not_found",
            "chunks": [],
            "retriever": "",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            result = kv._merge_persy_recall(
                payload,
                request=_request(),
                params={"dataset_id": kv._PERSY_DATASET_ID, "query": "q", "top_k": 5},
            )
        assert result["persy_memory"]["available"] is False
        assert result["persy_memory"]["error_code"] == "persy_memory_not_found"

    def test_persy_memory_success_merges_chunks_and_citations(self):
        payload = {
            "success": True,
            "chunks": [
                {
                    "text": "k1",
                    "score": 0.5,
                    "source": "s1",
                    "chunk_index": 0,
                    "metadata": {"document_id": "d1"},
                }
            ],
            "citations": [{"index": 1, "source": "doc"}],
            "answer": "kbase ans",
        }
        mem_svc = MagicMock()
        mem_svc.query.return_value = {
            "success": True,
            "chunks": [
                {"text": "mem1", "score": 0.9, "source": "memory", "metadata": {"memory_id": "m1"}},
                {
                    "text": "k1",
                    "score": 0.5,
                    "source": "s1",
                    "chunk_index": 0,
                    "metadata": {"document_id": "d1"},
                },
            ],
            "retriever": "persy",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            result = kv._merge_persy_recall(
                payload,
                request=_request(),
                params={
                    "dataset_id": kv._PERSY_DATASET_ID,
                    "query": "q",
                    "top_k": 5,
                    "include_answer": True,
                },
            )
        # Deduplicated (k1 appears in both, dedup by document_id).
        chunk_texts = [c["text"] for c in result["chunks"]]
        assert "mem1" in chunk_texts
        assert chunk_texts.count("k1") == 1
        # Citation added for EACH memory chunk (2 memory chunks → 2 memory citations).
        memory_citations = [c for c in result["citations"] if c.get("source") == "对话记忆"]
        assert len(memory_citations) == 2
        # Answer includes memory summary.
        assert "已确认的长期记忆" in result["answer"]
        assert "kbase ans" in result["answer"]

    def test_persy_memory_success_no_memory_chunks_skips_answer(self):
        payload = {
            "success": True,
            "chunks": [{"text": "k1", "score": 0.5, "source": "s1", "metadata": {}}],
            "citations": [],
            "answer": "kbase only",
        }
        mem_svc = MagicMock()
        mem_svc.query.return_value = {
            "success": True,
            "chunks": [],  # No memory chunks.
            "retriever": "persy",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            result = kv._merge_persy_recall(
                payload,
                request=_request(),
                params={
                    "dataset_id": kv._PERSY_DATASET_ID,
                    "query": "q",
                    "top_k": 5,
                    "include_answer": False,
                },
            )
        # No memory chunks → no memory answer appended.
        assert result["answer"] == "kbase only"

    def test_persy_memory_chunks_with_no_metadata_uses_text_fingerprint(self):
        """Memory chunk without memory_id/document_id → dedup by source:chunk_index:text."""
        payload = {
            "success": True,
            "chunks": [],
            "citations": [],
            "answer": "",
        }
        mem_svc = MagicMock()
        mem_svc.query.return_value = {
            "success": True,
            "chunks": [
                {"text": "mem-a", "score": 0.9, "source": "memory"},
                {"text": "mem-a", "score": 0.8, "source": "memory"},  # duplicate by fingerprint
            ],
            "retriever": "persy",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            result = kv._merge_persy_recall(
                payload,
                request=_request(),
                params={
                    "dataset_id": kv._PERSY_DATASET_ID,
                    "query": "q",
                    "top_k": 5,
                },
            )
        # Deduplicated: both memory chunks share fingerprint "memory:None:None:mem-a".
        assert len(result["chunks"]) == 1


# ===========================================================================
# _agent_node_output
# ===========================================================================


class TestAgentNodeOutput:
    def test_final_output_with_node_outputs(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {"dataset_rag_query": {"success": True, "data": "x"}}},
            steps=[],
            status="completed",
            error="",
            run_id="r1",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        assert out["success"] is True
        assert out["data"] == "x"
        assert out["run_id"] == "r1"
        assert out["agent_run_id"] == "r1"
        assert out["agent_status"] == "completed"

    def test_fallback_to_steps(self):
        step = SimpleNamespace(
            node_id="dataset_rag_query",
            output={"success": False, "message": "from-step"},
        )
        run = SimpleNamespace(
            final_output={"node_outputs": {}},
            steps=[step],
            status="failed",
            error="some error",
            run_id="r2",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        assert out["success"] is False
        assert out["message"] == "from-step"
        assert out["agent_status"] == "failed"

    def test_fallback_to_default_status_when_no_output(self):
        run = SimpleNamespace(
            final_output=None,
            steps=[],
            status="completed",
            error="",
            run_id="",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        # No output → success defaults to status == "completed"
        assert out["success"] is True
        # No run_id → keys not added.
        assert "run_id" not in out
        assert out["agent_status"] == "completed"

    def test_error_message_added_when_no_message(self):
        run = SimpleNamespace(
            final_output=None,
            steps=[],
            status="failed",
            error="boom",
            run_id="r3",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        assert out["success"] is False
        assert out["message"] == "boom"
        assert out["run_id"] == "r3"

    def test_error_message_not_overwritten(self):
        run = SimpleNamespace(
            final_output={
                "node_outputs": {"dataset_rag_query": {"success": False, "message": "kept"}}
            },
            steps=[],
            status="failed",
            error="boom",
            run_id="",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        assert out["message"] == "kept"

    def test_storage_keys_filtered_from_output(self):
        run = SimpleNamespace(
            final_output={
                "node_outputs": {
                    "dataset_rag_query": {
                        "success": True,
                        "storage_path": "/secret",
                        "data": "ok",
                    }
                }
            },
            steps=[],
            status="completed",
            error="",
            run_id="",
        )
        out = kv._agent_node_output(run, "dataset_rag_query")
        assert "storage_path" not in out
        assert out["data"] == "ok"


# ===========================================================================
# _dataset_agent_user_id
# ===========================================================================


class TestDatasetAgentUserId:
    def test_x_user_id_header_takes_priority(self):
        req = _request(headers={"X-User-Id": "user-from-header"})
        uid = kv._dataset_agent_user_id(req, {})
        assert uid == "user-from-header"

    def test_x_user_id_uppercase_header(self):
        req = _request(headers={"X-User-ID": "uid-upper"})
        uid = kv._dataset_agent_user_id(req, {})
        assert uid == "uid-upper"

    def test_access_context_actor_id(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {"access_context": {"actor_id": "actor-1"}})
        assert uid == "actor-1"

    def test_params_actor_id(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {"actor_id": "actor-2"})
        assert uid == "actor-2"

    def test_params_user_id(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {"user_id": "u-3"})
        assert uid == "u-3"

    def test_params_tenant_id(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {"tenant_id": "t-4"})
        assert uid == "t-4"

    def test_default_fallback(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {})
        assert uid == "dataset-rag-route"

    def test_strips_whitespace(self):
        req = _request(headers={"X-User-Id": "  spaced  "})
        uid = kv._dataset_agent_user_id(req, {})
        assert uid == "spaced"

    def test_access_context_not_dict_ignored(self):
        req = _request()
        uid = kv._dataset_agent_user_id(req, {"access_context": "not-a-dict"})
        assert uid == "dataset-rag-route"


# ===========================================================================
# _run_dataset_rag_agent (the main dispatcher)
# ===========================================================================


class TestRunDatasetRagAgent:
    def test_unregistered_action_returns_400(self):
        with patch.object(kv, "_dataset_access_payload_from_request", return_value={}):
            with patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value={"dataset_rag": {"actions": {}}},
            ):
                resp = kv._run_dataset_rag_agent(
                    request=_request(),
                    action="bogus_action",
                    params={},
                    route_path="/test",
                )
        assert resp.status_code == 400
        assert "未注册的 Dataset/RAG 动作" in resp.body.decode()

    def test_access_payload_propagates_tenant_id(self):
        captured_data = {}

        def _capture_start(*, user_id, message, plan, runtime_context):
            captured_data["tenant_id"] = plan.nodes[0].params.get("tenant_id")
            captured_data["runtime_tenant"] = runtime_context.get("dataset_tenant_id")
            return SimpleNamespace(
                run_id="r1",
                status="completed",
                final_output={"node_outputs": {"dataset_rag_query": {"success": True}}},
                steps=[],
                error="",
            )

        action_meta = {"query": {"risk": "low", "idempotent": True}}
        registry = {"dataset_rag": {"actions": action_meta}}
        orch = MagicMock()
        orch.start_run_from_plan.side_effect = _capture_start

        access_payload = {
            "tenant_id": "tenant-x",
            "permissions": ["dataset.read"],
            "is_admin": False,
        }
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value=access_payload),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            resp = kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        assert resp.status_code == 200
        # Tenant_id from access_payload fills empty data.
        assert captured_data["tenant_id"] == "tenant-x"
        assert captured_data["runtime_tenant"] == "tenant-x"

    def test_access_payload_does_not_override_existing_tenant_id(self):
        captured_data = {}

        def _capture_start(*, user_id, message, plan, runtime_context):
            captured_data["tenant_id"] = plan.nodes[0].params.get("tenant_id")
            return SimpleNamespace(
                run_id="r1",
                status="completed",
                final_output={"node_outputs": {"dataset_rag_query": {"success": True}}},
                steps=[],
                error="",
            )

        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.side_effect = _capture_start

        access_payload = {"tenant_id": "from-access", "permissions": [], "is_admin": False}
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value=access_payload),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q", "tenant_id": "from-data"},
                route_path="/test",
            )
        # Existing tenant_id in data should not be overridden.
        assert captured_data["tenant_id"] == "from-data"

    def test_run_waiting_user_triggers_continue(self):
        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        # First call returns waiting_user, continue_run returns a completed run.
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="waiting_user",
            final_output=None,
            steps=[],
            error="",
        )
        orch.continue_run.return_value = SimpleNamespace(
            run_id="r1",
            status="completed",
            final_output={"node_outputs": {"dataset_rag_query": {"success": True}}},
            steps=[],
            error="",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            resp = kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        orch.continue_run.assert_called_once()
        assert resp.status_code == 200

    def test_run_running_triggers_continue(self):
        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="running",
            final_output=None,
            steps=[],
            error="",
        )
        orch.continue_run.return_value = None  # continued is None → run stays unchanged
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            resp = kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        orch.continue_run.assert_called_once()
        # Run still "running" → falls to else → 200
        assert resp.status_code == 200

    def test_run_blocked_returns_202(self):
        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="blocked",
            final_output={"node_outputs": {"dataset_rag_query": {"success": False}}},
            steps=[],
            error="",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            resp = kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        assert resp.status_code == 202

    def test_tool_exception_returns_500(self):
        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="failed",
            final_output={
                "node_outputs": {
                    "dataset_rag_query": {"success": False, "error_code": "tool_exception"}
                }
            },
            steps=[],
            error="boom",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            resp = kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        assert resp.status_code == 500

    def test_query_action_triggers_persy_recall_merge(self):
        registry = {"dataset_rag": {"actions": {"query": {"risk": "low"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="completed",
            final_output={"node_outputs": {"dataset_rag_query": {"success": True}}},
            steps=[],
            error="",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
            patch.object(kv, "_merge_persy_recall", return_value={"success": True}) as mock_merge,
        ):
            kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        mock_merge.assert_called_once()

    def test_non_query_action_skips_persy_recall(self):
        registry = {"dataset_rag": {"actions": {"ingest_document": {"risk": "medium"}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="completed",
            final_output={"node_outputs": {"dataset_rag_ingest_document": {"success": True}}},
            steps=[],
            error="",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
            patch.object(kv, "_merge_persy_recall") as mock_merge,
        ):
            kv._run_dataset_rag_agent(
                request=_request(),
                action="ingest_document",
                params={"dataset_id": "d1"},
                route_path="/test",
            )
        mock_merge.assert_not_called()

    def test_default_action_meta_risk_when_missing(self):
        # action_meta has no "risk" key → defaults to "medium"
        registry = {"dataset_rag": {"actions": {"query": {}}}}
        orch = MagicMock()
        orch.start_run_from_plan.return_value = SimpleNamespace(
            run_id="r1",
            status="completed",
            final_output={"node_outputs": {"dataset_rag_query": {"success": True}}},
            steps=[],
            error="",
        )
        with (
            patch.object(kv, "_dataset_access_payload_from_request", return_value={}),
            patch(
                "app.application.workflow_registry_app.get_workflow_tool_registry",
                return_value=registry,
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
        ):
            kv._run_dataset_rag_agent(
                request=_request(),
                action="query",
                params={"dataset_id": "d1", "query": "q"},
                route_path="/test",
            )
        # Inspect the plan passed to orchestrator.
        plan_arg = orch.start_run_from_plan.call_args.kwargs["plan"]
        assert plan_arg.risk_level == "medium"
        assert plan_arg.nodes[0].risk == "medium"


# ===========================================================================
# ingest / query / status / health endpoints (direct calls)
# ===========================================================================


class TestIngestEndpoint:
    def test_happy_path_returns_success(self):
        with patch.object(kv, "_index") as mock_index:
            mock_index.ingest.return_value = 3
            resp = kv.ingest(kv.IngestRequest(text="hello"))
        assert resp.success is True
        assert resp.chunk_count == 3
        assert resp.source == "default"
        assert resp.strategy == "semantic"
        assert "已入库" in resp.message

    def test_value_error_returns_failure(self):
        with patch.object(kv, "_index") as mock_index:
            mock_index.ingest.side_effect = ValueError("bad input")
            resp = kv.ingest(kv.IngestRequest(text="hello"))
        assert resp.success is False
        assert resp.chunk_count == 0
        assert "bad input" in resp.message

    def test_type_error_returns_failure(self):
        with patch.object(kv, "_index") as mock_index:
            mock_index.ingest.side_effect = TypeError("type wrong")
            resp = kv.ingest(kv.IngestRequest(text="hello"))
        assert resp.success is False
        assert "type wrong" in resp.message


class TestQueryEndpoint:
    def test_happy_path_returns_chunks(self):
        chunk = SimpleNamespace(chunk_index=0, text="result", score=0.9, source="s")
        with (
            patch.object(kv, "_index") as mock_index,
            patch.object(kv, "is_rag_enabled", return_value=True),
        ):
            mock_index.query.return_value = [chunk]
            resp = kv.query(kv.QueryRequest(query="q"))
        assert resp.success is True
        assert resp.rag_enabled is True
        assert resp.chunks[0]["text"] == "result"
        assert resp.citations == []

    def test_empty_chunks(self):
        with (
            patch.object(kv, "_index") as mock_index,
            patch.object(kv, "is_rag_enabled", return_value=False),
        ):
            mock_index.query.return_value = []
            resp = kv.query(kv.QueryRequest(query="q"))
        assert resp.success is True
        assert resp.rag_enabled is False
        assert resp.chunks == []


class TestStatusEndpoint:
    def test_returns_status(self):
        with (
            patch.object(kv, "_index") as mock_index,
            patch.object(kv, "is_rag_enabled", return_value=True),
            patch.object(kv, "get_default_embedder", return_value="embedder"),
        ):
            mock_index.status.return_value = {"sources": 5, "chunks": 25}
            resp = kv.status()
        assert resp.rag_enabled is True
        assert resp.embedder_available is True
        assert resp.indexed_sources == 5
        assert resp.indexed_chunks == 25


class TestHealthEndpoint:
    def test_returns_health_dict(self):
        with (
            patch.object(kv, "_index") as mock_index,
            patch.object(kv, "is_rag_enabled", return_value=False),
            patch.object(kv, "get_default_embedder", return_value=None),
        ):
            mock_index.status.return_value = {"sources": 0, "chunks": 0}
            resp = kv.health()
        assert resp["success"] is True
        assert resp["rag_enabled"] is False
        assert resp["embedder_available"] is False


# ===========================================================================
# dataset routes (TestClient-based)
# ===========================================================================


def _build_client():
    app = FastAPI()
    app.include_router(kv.router)
    return TestClient(app, raise_server_exceptions=False)


class TestDatasetRoutes:
    def test_ingest_dataset_document_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b'{"ok":1}')
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/documents",
                json={"text": "hello"},
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "ingest_document"

    def test_query_dataset_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b'{"ok":1}')
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/query",
                json={"query": "q"},
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "query"

    def test_diff_dataset_versions_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/versions/diff",
                json={"source": "s", "from_version": "v1"},
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "diff_versions"

    def test_rollback_dataset_version_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/versions/rollback",
                json={"source": "s", "target_version": "v1"},
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "rollback_version"

    def test_rebuild_dataset_index_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/index/rebuild",
                json={},
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "rebuild_index"

    def test_cancel_rebuild_job_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/index/rebuild/job-1/cancel",
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "cancel_rebuild"

    def test_delete_dataset_document_routes_to_agent(self):
        client = _build_client()
        with patch.object(kv, "_run_dataset_rag_agent") as mock_run:
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            resp = client.delete(
                "/api/knowledge/v1/datasets/d1/documents/doc-1",
            )
        assert resp.status_code == 200
        assert mock_run.call_args.kwargs["action"] == "delete_document"

    def test_dataset_status_all_returns_payload(self):
        client = _build_client()
        svc = MagicMock()
        svc.status.return_value = {"success": True, "datasets": [{"id": "d1"}], "_internal": "x"}
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=svc,
            ),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get("/api/knowledge/v1/datasets")
        assert resp.status_code == 200
        # _public_dataset_payload filters _internal.
        assert "_internal" not in resp.json()
        assert resp.json()["datasets"][0]["id"] == "d1"

    def test_dataset_status_single_returns_payload(self):
        client = _build_client()
        svc = MagicMock()
        svc.status.return_value = {"success": True, "id": "d1", "storage_path": "/secret"}
        access = SimpleNamespace(tenant_id="t1")
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=svc,
            ),
            patch.object(kv, "_dataset_access_context_from_request", return_value=access),
        ):
            resp = client.get("/api/knowledge/v1/datasets/d1/status")
        assert resp.status_code == 200
        assert "storage_path" not in resp.json()
        svc.status.assert_called_once_with("d1", tenant_id="t1", access_context=access)

    def test_dataset_rebuild_job_returns_payload(self):
        client = _build_client()
        svc = MagicMock()
        svc.get_rebuild_job.return_value = {
            "success": True,
            "job_id": "j1",
            "vector_index_path": "/secret",
        }
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=svc,
            ),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get("/api/knowledge/v1/datasets/d1/index/rebuild/j1")
        assert resp.status_code == 200
        assert "vector_index_path" not in resp.json()
        assert resp.json()["job_id"] == "j1"


# ===========================================================================
# dataset_graph
# ===========================================================================


class TestDatasetGraph:
    def test_persy_dataset_with_memory_nodes_reduces_graph_limit(self):
        client = _build_client()
        ds_svc = MagicMock()
        ds_svc.knowledge_graph.return_value = {
            "success": True,
            "nodes": [{"id": "k1"}],
            "edges": [],
            "stats": {},
        }
        mem_svc = MagicMock()
        mem_svc.graph.return_value = {
            "success": True,
            "nodes": [{"id": "memory:m1"}],
            "edges": [],
            "stats": {},
        }
        merged = {"success": True, "nodes": [{"id": "merged1"}], "edges": [], "stats": {}}
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=ds_svc,
            ),
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch(
                "app.application.persy_memory_app_service.merge_memory_graph",
                return_value=merged,
            ),
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/graph?limit=80")
        assert resp.status_code == 200
        # merge_memory_graph called because both succeeded.
        ds_svc.knowledge_graph.assert_called_once()
        # Limit reduced because memory_graph had nodes (0.62 * 80 = 49).
        assert ds_svc.knowledge_graph.call_args.kwargs["limit"] == 49

    def test_persy_dataset_without_memory_nodes_keeps_full_limit(self):
        client = _build_client()
        ds_svc = MagicMock()
        ds_svc.knowledge_graph.return_value = {
            "success": True,
            "nodes": [],
            "edges": [],
            "stats": {},
        }
        mem_svc = MagicMock()
        mem_svc.graph.return_value = {
            "success": True,
            "nodes": [],  # no memory nodes
            "edges": [],
            "stats": {},
        }
        merged = {"success": True, "nodes": [], "edges": [], "stats": {}}
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=ds_svc,
            ),
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch(
                "app.application.persy_memory_app_service.merge_memory_graph",
                return_value=merged,
            ) as mock_merge,
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/graph?limit=80")
        assert resp.status_code == 200
        # Memory graph empty → graph_limit stays at the full limit.
        assert ds_svc.knowledge_graph.call_args.kwargs["limit"] == 80
        # merge still called since both succeeded.
        mock_merge.assert_called_once()

    def test_non_persy_dataset_skips_memory_graph(self):
        client = _build_client()
        ds_svc = MagicMock()
        ds_svc.knowledge_graph.return_value = {
            "success": True,
            "nodes": [{"id": "k1"}],
            "edges": [],
            "stats": {},
        }
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=ds_svc,
            ),
            patch.object(kv, "_persy_memory_service") as mock_mem,
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get("/api/knowledge/v1/datasets/other-dataset/graph?limit=80")
        assert resp.status_code == 200
        # _persy_memory_service not invoked for non-persy datasets.
        mock_mem.assert_not_called()

    def test_base_graph_failure_returns_base_unchanged(self):
        client = _build_client()
        ds_svc = MagicMock()
        ds_svc.knowledge_graph.return_value = {
            "success": False,
            "error_code": "denied",
            "nodes": [],
            "edges": [],
            "stats": {},
        }
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=ds_svc,
            ),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get("/api/knowledge/v1/datasets/other-dataset/graph?limit=80")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_memory_graph_failure_returns_base_graph(self):
        client = _build_client()
        ds_svc = MagicMock()
        ds_svc.knowledge_graph.return_value = {
            "success": True,
            "nodes": [{"id": "k1"}],
            "edges": [],
            "stats": {},
        }
        mem_svc = MagicMock()
        mem_svc.graph.return_value = {"success": False, "nodes": [], "edges": [], "stats": {}}
        with (
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=ds_svc,
            ),
            patch.object(kv, "_persy_memory_service", return_value=mem_svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.application.persy_memory_app_service.merge_memory_graph") as mock_merge,
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/graph?limit=80")
        assert resp.status_code == 200
        # merge not called when memory_graph fails.
        mock_merge.assert_not_called()


# ===========================================================================
# list_persy_memories / query_persy_memories
# ===========================================================================


class TestPersyMemoryListQuery:
    def test_unsupported_dataset_returns_404(self):
        client = _build_client()
        resp = client.get("/api/knowledge/v1/datasets/other/memories")
        assert resp.status_code == 404

    def test_list_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.list_memories.return_value = {
            "success": True,
            "memories": [{"memory_id": "m1"}],
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories?status=pending"
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_permission_denied_returns_403(self):
        client = _build_client()
        svc = MagicMock()
        svc.list_memories.return_value = {
            "success": False,
            "error_code": "dataset_permission_denied",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories")
        assert resp.status_code == 403

    def test_list_scope_missing_returns_403(self):
        client = _build_client()
        svc = MagicMock()
        svc.list_memories.return_value = {
            "success": False,
            "error_code": "persy_memory_scope_missing",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories")
        assert resp.status_code == 403

    def test_list_other_error_returns_400(self):
        client = _build_client()
        svc = MagicMock()
        svc.list_memories.return_value = {
            "success": False,
            "error_code": "some_other",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.get(f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories")
        assert resp.status_code == 400

    def test_query_unsupported_dataset_returns_404(self):
        client = _build_client()
        resp = client.post(
            "/api/knowledge/v1/datasets/other/memories/query",
            json={"query": "q"},
        )
        assert resp.status_code == 404

    def test_query_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.query.return_value = {"success": True, "chunks": []}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.post(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/query",
                json={"query": "q", "top_k": 5},
            )
        assert resp.status_code == 200

    def test_query_permission_denied_returns_403(self):
        client = _build_client()
        svc = MagicMock()
        svc.query.return_value = {
            "success": False,
            "error_code": "dataset_permission_denied",
        }
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
        ):
            resp = client.post(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/query",
                json={"query": "q"},
            )
        assert resp.status_code == 403


# ===========================================================================
# confirm / reject / correct / delete persy memory mutations
# ===========================================================================


class TestPersyMemoryMutations:
    def test_confirm_unsupported_dataset_returns_404(self):
        client = _build_client()
        resp = client.post(
            "/api/knowledge/v1/datasets/other/memories/m1/confirm",
            json={},
        )
        assert resp.status_code == 404

    def test_confirm_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {"memory_id": "m1"}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            resp = client.post(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1/confirm",
                json={},
            )
        assert resp.status_code == 200
        svc.mutate.assert_called_once()
        assert svc.mutate.call_args.kwargs["action"] == "confirm"

    def test_confirm_with_correction_fields(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            client.post(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1/confirm",
                json={"key": "k", "value": "v", "memory_type": "fact", "confidence": 0.9},
            )
        patch_arg = svc.mutate.call_args.kwargs["patch"]
        assert patch_arg == {"key": "k", "value": "v", "memory_type": "fact", "confidence": 0.9}

    def test_reject_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            resp = client.post(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1/reject",
                json={"reason": "obsolete"},
            )
        assert resp.status_code == 200
        assert svc.mutate.call_args.kwargs["action"] == "reject"
        assert svc.mutate.call_args.kwargs["reason"] == "obsolete"

    def test_correct_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            resp = client.patch(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1",
                json={"key": "new-key", "value": "new-val"},
            )
        assert resp.status_code == 200
        assert svc.mutate.call_args.kwargs["action"] == "correct"
        assert svc.mutate.call_args.kwargs["patch"] == {"key": "new-key", "value": "new-val"}

    def test_correct_with_empty_patch(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            client.patch(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1",
                json={},
            )
        # Empty patch when no key/value provided.
        assert svc.mutate.call_args.kwargs["patch"] == {}

    def test_delete_success(self):
        client = _build_client()
        svc = MagicMock()
        svc.mutate.return_value = {"success": True, "memory": {}}
        with (
            patch.object(kv, "_persy_memory_service", return_value=svc),
            patch.object(kv, "_dataset_access_context_from_request", return_value=None),
            patch("app.utils.audit_logger.audit_log"),
        ):
            resp = client.delete(
                f"/api/knowledge/v1/datasets/{kv._PERSY_DATASET_ID}/memories/m1?reason=bad"
            )
        assert resp.status_code == 200
        assert svc.mutate.call_args.kwargs["action"] == "delete"
        assert svc.mutate.call_args.kwargs["reason"] == "bad"

    def test_delete_unsupported_dataset_returns_404(self):
        client = _build_client()
        resp = client.delete("/api/knowledge/v1/datasets/other/memories/m1?reason=bad")
        assert resp.status_code == 404


# ===========================================================================
# upload_dataset_document
# ===========================================================================


class TestUploadDatasetDocument:
    def test_unsupported_extension_returns_400(self):
        client = _build_client()
        # Build a fake UploadFile via TestClient's `files` parameter.
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("doc.exe", b"hello", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "不支持的资料类型" in resp.json()["message"]

    def test_source_too_long_returns_400(self):
        client = _build_client()
        long_source = "x" * 301
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("doc.txt", b"hello", "text/plain")},
            data={"source": long_source},
        )
        assert resp.status_code == 400
        assert "300" in resp.json()["message"]

    def test_tenant_id_too_long_returns_400(self):
        client = _build_client()
        long_tenant = "x" * 161
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("doc.txt", b"hello", "text/plain")},
            data={"tenant_id": long_tenant},
        )
        assert resp.status_code == 400
        assert "上传参数过长" in resp.json()["message"]

    def test_version_too_long_returns_400(self):
        client = _build_client()
        long_version = "x" * 81
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("doc.txt", b"hello", "text/plain")},
            data={"version": long_version},
        )
        assert resp.status_code == 400
        assert "上传参数过长" in resp.json()["message"]

    def test_version_label_too_long_returns_400(self):
        client = _build_client()
        long_label = "x" * 121
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("doc.txt", b"hello", "text/plain")},
            data={"version_label": long_label},
        )
        assert resp.status_code == 400
        assert "上传参数过长" in resp.json()["message"]

    def test_happy_path_routes_to_agent(self, tmp_path):
        client = _build_client()
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            mock_run.return_value = MagicMock(status_code=200, body=b'{"ok":1}')
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/documents/upload",
                files={"file": ("doc.txt", b"hello world", "text/plain")},
                data={"source": "test-doc", "chunk_strategy": "fixed"},
            )
        assert resp.status_code == 200
        # Check the agent was called with the saved file path and proper params.
        params = mock_run.call_args.kwargs["params"]
        assert params["source"] == "test-doc"
        assert params["chunk_strategy"] == "fixed"
        assert params["file_path"].endswith(".txt")
        assert params["metadata"]["original_file_name"] == "doc.txt"
        assert params["metadata"]["upload_size_bytes"] == len(b"hello world")

    def test_invalid_chunk_strategy_falls_back_to_semantic(self, tmp_path):
        client = _build_client()
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            client.post(
                "/api/knowledge/v1/datasets/d1/documents/upload",
                files={"file": ("doc.txt", b"hi", "text/plain")},
                data={"chunk_strategy": "bogus"},
            )
        params = mock_run.call_args.kwargs["params"]
        assert params["chunk_strategy"] == "semantic"

    def test_oversize_file_returns_400(self, tmp_path):
        client = _build_client()
        # Build payload just over 25 MB.
        big_payload = b"x" * (kv._DATASET_UPLOAD_MAX_BYTES + 100)
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            resp = client.post(
                "/api/knowledge/v1/datasets/d1/documents/upload",
                files={"file": ("doc.txt", big_payload, "text/plain")},
            )
        assert resp.status_code == 400
        assert "25 MB" in resp.json()["message"]
        assert resp.json()["error_code"] == "dataset_upload_too_large"
        mock_run.assert_not_called()

    def test_dataset_id_never_controls_upload_path(self, tmp_path):
        client = _build_client()
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            client.post(
                "/api/knowledge/v1/datasets/customer-secret/documents/upload",
                files={"file": ("doc.txt", b"safe", "text/plain")},
            )

        saved_path = Path(mock_run.call_args.kwargs["params"]["file_path"])
        assert saved_path.parent == tmp_path.resolve() / "knowledge"
        assert saved_path.suffix == ".txt"

    def test_agent_failure_cleans_up_file(self, tmp_path):
        client = _build_client()
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            mock_run.return_value = MagicMock(status_code=500, body=b'{"err":1}')
            client.post(
                "/api/knowledge/v1/datasets/d1/documents/upload",
                files={"file": ("doc.txt", b"hi", "text/plain")},
            )
            # The saved file should have been unlinked because status >= 400.
            saved_files = list(Path(str(tmp_path)).rglob("*.txt"))
            assert saved_files == []

    def test_filename_without_extension_returns_400(self, tmp_path):
        # Filename "noext" has empty suffix → not in allowed set → 400.
        client = _build_client()
        resp = client.post(
            "/api/knowledge/v1/datasets/d1/documents/upload",
            files={"file": ("noext", b"hi", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "无扩展名" in resp.json()["message"]

    def test_long_filename_truncated(self, tmp_path):
        client = _build_client()
        long_stem = "x" * 300
        with (
            patch("app.utils.path_utils.get_upload_dir", return_value=str(tmp_path)),
            patch.object(kv, "_run_dataset_rag_agent") as mock_run,
        ):
            mock_run.return_value = MagicMock(status_code=200, body=b"{}")
            client.post(
                "/api/knowledge/v1/datasets/d1/documents/upload",
                files={"file": (f"{long_stem}.txt", b"hi", "text/plain")},
            )
        params = mock_run.call_args.kwargs["params"]
        # Stem truncated to fit 240 chars total.
        assert len(params["metadata"]["original_file_name"]) <= 240
        assert params["metadata"]["original_file_name"].endswith(".txt")
