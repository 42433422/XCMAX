"""Branch-coverage tests for app/application/agent_orchestrator/chat_trace.py.

Targets the ~83 missing branches reported in coverage_new.json.
All external I/O (DB, billing, artifact ingestion) is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.agent_orchestrator import chat_trace as ct
from app.application.agent_orchestrator.run_models import (
    AgentArtifact,
    AgentRun,
    LLMCall,
    MemoryReference,
    RetrievalCall,
)
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ledger_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_BACKEND", raising=False)
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


@pytest.fixture()
def repo():
    return InMemoryAgentRunRepository()


def _make_run(**kwargs) -> AgentRun:
    defaults = {"user_id": "u1", "message": "hi", "status": "running", "intent": "test"}
    defaults.update(kwargs)
    return AgentRun(**defaults)


# ===========================================================================
# _trace_safe_value — lines 42-61
# ===========================================================================

class TestTraceSafeValue:
    def test_depth_limit_converts_to_str(self):
        result = ct._trace_safe_value({"key": "val"}, depth=4)
        assert isinstance(result, str)

    def test_long_string_truncated(self):
        s = "x" * (ct._MAX_TRACE_STRING_CHARS + 100)
        result = ct._trace_safe_value(s)
        assert result.endswith("...[truncated]")
        assert len(result) == ct._MAX_TRACE_STRING_CHARS + len("...[truncated]")

    def test_short_string_unchanged(self):
        result = ct._trace_safe_value("hello")
        assert result == "hello"

    def test_int_unchanged(self):
        assert ct._trace_safe_value(42) == 42

    def test_float_unchanged(self):
        assert ct._trace_safe_value(3.14) == 3.14

    def test_bool_unchanged(self):
        assert ct._trace_safe_value(True) is True

    def test_none_unchanged(self):
        assert ct._trace_safe_value(None) is None

    def test_list_truncated_at_limit(self):
        big_list = list(range(ct._MAX_TRACE_LIST_ITEMS + 5))
        result = ct._trace_safe_value(big_list)
        assert len(result) == ct._MAX_TRACE_LIST_ITEMS

    def test_tuple_treated_like_list(self):
        result = ct._trace_safe_value((1, 2, 3))
        assert result == [1, 2, 3]

    def test_dict_truncated_at_limit(self):
        big_dict = {str(i): i for i in range(ct._MAX_TRACE_DICT_ITEMS + 5)}
        result = ct._trace_safe_value(big_dict)
        assert result.get("_truncated") is True

    def test_unknown_type_stringified(self):
        class MyObj:
            def __str__(self):
                return "myobj"
        result = ct._trace_safe_value(MyObj())
        assert result == "myobj"

    def test_nested_dict(self):
        payload = {"outer": {"inner": "value"}}
        result = ct._trace_safe_value(payload)
        assert result["outer"]["inner"] == "value"


# ===========================================================================
# _resolved_user_id — lines 64-81
# ===========================================================================

class TestResolvedUserId:
    def test_uses_explicit_user_id(self):
        result = ct._resolved_user_id(runtime_context=None, user_id="u123")
        assert result == "u123"

    def test_falls_back_to_context_user_id(self):
        result = ct._resolved_user_id(runtime_context={"user_id": "ctx_u"}, user_id=None)
        assert result == "ctx_u"

    def test_falls_back_to_userId(self):
        result = ct._resolved_user_id(runtime_context={"userId": "U456"}, user_id=None)
        assert result == "U456"

    def test_falls_back_to_uid(self):
        result = ct._resolved_user_id(runtime_context={"uid": "uid789"}, user_id=None)
        assert result == "uid789"

    def test_falls_back_to_username(self):
        result = ct._resolved_user_id(runtime_context={"username": "alice"}, user_id=None)
        assert result == "alice"

    def test_returns_anonymous_when_all_empty(self):
        result = ct._resolved_user_id(runtime_context={}, user_id=None)
        assert result == "anonymous"

    def test_explicit_user_id_wins_over_context(self):
        result = ct._resolved_user_id(runtime_context={"user_id": "ctx"}, user_id="explicit")
        assert result == "explicit"


# ===========================================================================
# _payload_status — lines 89-95
# ===========================================================================

class TestPayloadStatus:
    def test_requires_token_returns_waiting_user(self):
        assert ct._payload_status({"requires_token": True}) == "waiting_user"

    def test_data_requires_token_returns_waiting_user(self):
        assert ct._payload_status({"data": {"requires_token": True}}) == "waiting_user"

    def test_success_false_returns_failed(self):
        assert ct._payload_status({"success": False}) == "failed"

    def test_default_returns_completed(self):
        assert ct._payload_status({"success": True}) == "completed"


# ===========================================================================
# _payload_error_message — lines 98-106
# ===========================================================================

class TestPayloadErrorMessage:
    def test_uses_message_field(self):
        assert ct._payload_error_message({"message": "oops"}) == "oops"

    def test_falls_back_to_error_field(self):
        assert ct._payload_error_message({"error": "crash"}) == "crash"

    def test_falls_back_to_data_message(self):
        assert ct._payload_error_message({"data": {"message": "nested"}}) == "nested"

    def test_falls_back_to_default(self):
        assert ct._payload_error_message({}) == "Chat run failed"


# ===========================================================================
# _iter_payload_dicts — lines 109-124
# ===========================================================================

class TestIterPayloadDicts:
    def test_yields_root(self):
        payload = {"a": 1}
        result = list(ct._iter_payload_dicts(payload))
        assert payload in result

    def test_yields_nested_data(self):
        payload = {"data": {"x": 2}}
        items = list(ct._iter_payload_dicts(payload))
        assert {"x": 2} in items

    def test_stops_at_max_depth(self):
        # Build 5-deep nesting
        deep = {"data": {"data": {"data": {"data": {"deep": True}}}}}
        items = list(ct._iter_payload_dicts(deep, max_depth=2))
        assert not any(item.get("deep") for item in items)

    def test_avoids_cycles(self):
        a: dict = {}
        b: dict = {"data": a}
        a["data"] = b
        # Should not infinite loop
        items = list(ct._iter_payload_dicts(a, max_depth=3))
        assert len(items) > 0


# ===========================================================================
# _coerce_trace_int / _coerce_trace_float
# ===========================================================================

class TestCoerceHelpers:
    def test_int_valid(self):
        assert ct._coerce_trace_int("5") == 5

    def test_int_bad_value(self):
        assert ct._coerce_trace_int("bad") == 0

    def test_int_none(self):
        assert ct._coerce_trace_int(None) == 0

    def test_float_valid(self):
        assert ct._coerce_trace_float("3.5") == 3.5

    def test_float_bad_value(self):
        assert ct._coerce_trace_float("bad") == 0.0

    def test_float_none(self):
        assert ct._coerce_trace_float(None) == 0.0


# ===========================================================================
# _llm_call_from_trace — lines 253-309
# ===========================================================================

class TestLlmCallFromTrace:
    def test_returns_none_for_empty_trace(self):
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=0):
            result = ct._llm_call_from_trace({})
        assert result is None

    def test_creates_call_from_valid_trace(self):
        trace = {
            "provider_id": "openai",
            "model": "gpt-4",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=10):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.model == "gpt-4"
        assert result.provider_id == "openai"

    def test_camel_case_fields(self):
        trace = {
            "providerId": "azure",
            "modelName": "gpt-4o",
            "promptTokens": 200,
            "completionTokens": 100,
            "totalTokens": 300,
        }
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=20):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.provider_id == "azure"

    def test_invalid_status_normalized(self):
        trace = {
            "provider": "anthropic",
            "model": "claude-3",
            "total_tokens": 100,
            "status": "weird_status",
        }
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=5):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.status == "completed"

    def test_call_id_set_when_present(self):
        trace = {
            "provider": "openai",
            "model": "gpt-3.5",
            "total_tokens": 50,
            "call_id": "cid-abc",
        }
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=3):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.call_id == "cid-abc"

    def test_error_field_creates_non_none_call(self):
        trace = {"error": "timeout", "provider": "openai", "model": "gpt-4"}
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=0):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.error == "timeout"

    def test_metered_billing_status_when_cost_units(self):
        trace = {
            "provider": "openai",
            "model": "gpt-4",
            "total_tokens": 100,
            "cost_units": 5,
        }
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=0):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.billing_status == "metered"


# ===========================================================================
# _append_llm_calls_to_run / _refresh_llm_metadata — lines 446-473
# ===========================================================================

class TestAppendLlmCallsToRun:
    def test_skips_duplicate_calls(self, repo):
        run = _make_run()
        # Pre-populate run.llm_calls with a call so its signature is in existing
        pre_call = LLMCall(
            provider_id="openai", provider="openai", model="gpt-4",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            billing_status="unmetered",
        )
        run.llm_calls.append(pre_call)
        # Now try to append another call with the same signature
        dup_call = LLMCall(
            provider_id="openai", provider="openai", model="gpt-4",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            billing_status="unmetered",
        )
        entry = {"billing_status": "unmetered", "billing_source": "est", "cost_units": 0,
                 "usage_id": "u1", "usage_key": "k1"}
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value=entry):
            ct._append_llm_calls_to_run(run, [dup_call])
        # The duplicate should be skipped
        assert len(run.llm_calls) == 1

    def test_adds_new_calls_and_refreshes_metadata(self, repo):
        run = _make_run()
        call = LLMCall(
            provider_id="openai", provider="openai", model="gpt-4",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
        )
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value={
            "billing_status": "metered", "billing_source": "est", "cost_units": 10,
            "usage_id": "uid1", "usage_key": "k1",
        }):
            ct._append_llm_calls_to_run(run, [call])
        assert run.metadata["llm_call_count"] == 1
        assert run.metadata["llm_model"] == "gpt-4"


# ===========================================================================
# _record_llm_usage_entry billing branches — lines 351-443
# ===========================================================================

class TestRecordLlmUsageEntry:
    def test_non_completed_returns_none(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10, status="failed")
        result = ct._record_llm_usage_entry(run, call)
        assert result is None

    def test_debited_status_sets_balance(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        entry = {
            "billing_status": "debited",
            "billing_source": "wallet",
            "cost_units": 5,
            "usage_id": "u1",
            "usage_key": "k1",
            "wallet_debit": {"balance_after_units": 950, "balance_after_yuan": "9.50"},
        }
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value=entry):
            ct._record_llm_usage_entry(run, call)
        assert run.metadata.get("model_wallet_balance_units") == 950
        assert run.metadata.get("model_wallet_balance_yuan") == "9.50"

    def test_insufficient_balance_sets_run_failed(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        entry = {
            "billing_status": "insufficient_balance",
            "billing_source": "wallet",
            "cost_units": 5,
            "usage_id": "u2",
            "usage_key": "k2",
            "wallet_debit": {"balance_after_units": 0},
        }
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value=entry):
            ct._record_llm_usage_entry(run, call)
        assert run.status == "failed"

    def test_market_debit_failed_sets_run_failed(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        entry = {
            "billing_status": "market_debit_failed",
            "billing_source": "market",
            "cost_units": 5,
            "usage_id": "u3",
            "usage_key": "k3",
            "wallet_debit": {},
        }
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value=entry):
            ct._record_llm_usage_entry(run, call)
        assert run.status == "failed"

    def test_billing_record_failure_adds_event(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        with patch("app.infrastructure.billing.model_usage.record_model_usage", side_effect=RuntimeError("ledger down")):
            result = ct._record_llm_usage_entry(run, call)
        assert result is None
        assert any(e.event_type == "billing.record_failed" for e in run.events)

    def test_unmetered_billing_recorded_event(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        entry = {
            "billing_status": "unmetered",
            "billing_source": "estimated",
            "cost_units": 0,
            "usage_id": "u4",
            "usage_key": "k4",
            "wallet_debit": None,
        }
        with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value=entry):
            ct._record_llm_usage_entry(run, call)
        assert any(e.event_type == "billing.recorded" for e in run.events)


# ===========================================================================
# _retrieval_call_from_payload — lines 526-584
# ===========================================================================

class TestRetrievalCallFromPayload:
    def test_no_chunks_citations_error_returns_none(self):
        result = ct._retrieval_call_from_payload({}, default_query="q")
        assert result is None

    def test_with_error_creates_failed_call(self):
        item = {"rag_error": "retrieval failed"}
        result = ct._retrieval_call_from_payload(item, default_query="query")
        assert result is not None
        assert result.status == "failed"
        assert result.error == "retrieval failed"

    def test_with_chunks(self):
        item = {"chunks": [{"text": "chunk1", "chunk_index": 0}]}
        result = ct._retrieval_call_from_payload(item, default_query="find something")
        assert result is not None
        assert result.status == "completed"
        assert len(result.chunks) == 1

    def test_with_citations(self):
        item = {"citations": [{"source": "doc.pdf", "text": "ref"}]}
        result = ct._retrieval_call_from_payload(item, default_query="q")
        assert result is not None
        assert len(result.citations) == 1

    def test_top_k_from_item(self):
        item = {"chunks": [{"text": "c"}], "top_k": 5}
        result = ct._retrieval_call_from_payload(item, default_query="q")
        assert result is not None
        assert result.top_k == 5


# ===========================================================================
# _memory_reference_from_payload — lines 719-804
# ===========================================================================

class TestMemoryReferenceFromPayload:
    def test_no_marker_no_hits_returns_none(self):
        result = ct._memory_reference_from_payload({}, default_query="q")
        assert result is None

    def test_has_marker_but_no_hits_no_summary_returns_none(self):
        item = {"user_memory_rag": True}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is None

    def test_with_summary_and_marker(self):
        item = {
            "user_memory_rag_summary": "This is a memory summary",
            "user_memory_hits": [{"chunk_id": "c1", "content": "some memory"}],
        }
        result = ct._memory_reference_from_payload(item, default_query="search")
        assert result is not None
        assert result.summary == "This is a memory summary"

    def test_with_error(self):
        item = {"user_memory_error": "memory fetch failed", "user_memory_rag": True}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None
        assert result.status == "failed"

    def test_with_userMemoryRag_marker(self):
        item = {
            "userMemoryRag": True,
            "userMemoryRagSummary": "summary text",
        }
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None

    def test_summary_containing_UserMemoryRAG(self):
        item = {"summary": "UserMemoryRAG context loaded"}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None


# ===========================================================================
# _artifact_from_ocr_payload — lines 903-947
# ===========================================================================

class TestArtifactFromOcrPayload:
    def test_no_text_returns_none(self):
        result = ct._artifact_from_ocr_payload({})
        assert result is None

    def test_text_without_ocr_shape_returns_none(self):
        result = ct._artifact_from_ocr_payload({"text": "hello"})
        assert result is None

    def test_with_confidence_creates_artifact(self):
        item = {"text": "OCR text", "confidence": 0.95, "file_path": "/img.jpg"}
        result = ct._artifact_from_ocr_payload(item)
        assert result is not None
        assert result.artifact_type == "ocr_text"

    def test_with_analysis_dict(self):
        item = {"text": "OCR", "analysis": {"key": "val"}, "file_path": "/p.png"}
        result = ct._artifact_from_ocr_payload(item)
        assert result is not None

    def test_with_structured_data(self):
        item = {
            "text": "Invoice data",
            "structured_data": {"amount": "100", "date": "2024-01-01"},
            "file_path": "/invoice.jpg",
        }
        result = ct._artifact_from_ocr_payload(item)
        assert result is not None
        assert result.artifact_type == "ocr_text"


# ===========================================================================
# _artifact_from_file_analysis_payload — lines 950-1004
# ===========================================================================

class TestArtifactFromFileAnalysisPayload:
    def test_no_required_keys_returns_none(self):
        result = ct._artifact_from_file_analysis_payload({"other": True})
        assert result is None

    def test_empty_values_returns_none(self):
        result = ct._artifact_from_file_analysis_payload({"parser_used": "", "extension": ""})
        assert result is None

    def test_sqlite_db_type(self):
        item = {"parser_used": "sqlite_db", "saved_name": "test.db"}
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "database_file"

    def test_excel_extension(self):
        item = {"extension": ".xlsx", "saved_name": "data.xlsx"}
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "excel_file"

    def test_pdf_extension(self):
        item = {"extension": ".pdf", "saved_name": "doc.pdf"}
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "pdf_document"

    def test_office_doc_extension(self):
        item = {"extension": ".docx", "saved_name": "report.docx"}
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "office_document"

    def test_fallback_type(self):
        item = {"parser_used": "custom_parser", "saved_name": "file.custom"}
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "file_analysis"

    def test_with_db_meta_table_columns(self):
        item = {
            "parser_used": "sqlite_db",
            "saved_name": "test.db",
            "db_meta": {"table_columns": {"users": ["id", "name"], "orders": ["id", "user_id"]}},
        }
        result = ct._artifact_from_file_analysis_payload(item)
        assert result is not None
        assert len(result.fields) == 2


# ===========================================================================
# _mime_from_document_name / _artifact_type_from_document
# ===========================================================================

class TestMimeAndArtifactType:
    def test_pdf_mime(self):
        assert ct._mime_from_document_name("report.pdf") == "application/pdf"

    def test_docx_mime(self):
        assert "wordprocessingml" in ct._mime_from_document_name("doc.docx")

    def test_xlsx_mime(self):
        assert "spreadsheetml" in ct._mime_from_document_name("data.xlsx")

    def test_pptx_mime(self):
        assert "presentationml" in ct._mime_from_document_name("slides.pptx")

    def test_unknown_default(self):
        assert ct._mime_from_document_name("file.txt", "text/plain") == "text/plain"

    def test_artifact_type_pdf(self):
        assert ct._artifact_type_from_document("doc.pdf", "") == "pdf_document"

    def test_artifact_type_office_by_name(self):
        assert ct._artifact_type_from_document("doc.docx", "") == "office_document"

    def test_artifact_type_office_by_mime(self):
        assert ct._artifact_type_from_document("file.bin", "application/vnd.ms-officedocument") == "office_document"

    def test_artifact_type_fallback(self):
        assert ct._artifact_type_from_document("file.bin", "application/octet-stream") == "document_file"

    def test_artifact_type_pdf_by_mime(self):
        assert ct._artifact_type_from_document("file", "application/pdf") == "pdf_document"


# ===========================================================================
# _artifact_from_generated_document_payload — lines 1032-1090
# ===========================================================================

class TestArtifactFromGeneratedDocumentPayload:
    def test_no_document_marker_returns_none(self):
        result = ct._artifact_from_generated_document_payload({"other": "data"})
        assert result is None

    def test_with_download_url(self):
        item = {"download_url": "http://example.com/file.pdf", "name": "report.pdf"}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is not None
        assert result.uri == "http://example.com/file.pdf"

    def test_with_document_nested(self):
        item = {"document": {"download_url": "http://x.com/f.docx", "file_name": "f.docx"}}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is not None
        assert result.name == "f.docx"

    def test_pickup_token_without_name_uri(self):
        # Must have at least one of name, uri, pickup_token
        item = {"pickup_token": "token123"}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is not None
        assert result.preview["pickup_token"] == "token123"

    def test_no_name_uri_token_returns_none(self):
        item = {"document": {"other": "data"}}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is None

    def test_mime_inferred_from_name(self):
        item = {"download_url": "http://x.com/d.pdf", "name": "doc.pdf"}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is not None
        assert result.mime_type == "application/pdf"


# ===========================================================================
# _artifact_from_excel_analysis_payload — lines 1093-1128
# ===========================================================================

class TestArtifactFromExcelAnalysisPayload:
    def test_no_preview_data_returns_none(self):
        result = ct._artifact_from_excel_analysis_payload({})
        assert result is None

    def test_preview_data_without_keys_returns_none(self):
        result = ct._artifact_from_excel_analysis_payload({"preview_data": {"other": True}})
        assert result is None

    def test_with_sample_rows(self):
        item = {
            "preview_data": {
                "sample_rows": [{"col1": "a"}, {"col1": "b"}],
                "sheet_name": "Sheet1",
            },
            "name": "report.xlsx",
        }
        result = ct._artifact_from_excel_analysis_payload(item)
        assert result is not None
        assert result.artifact_type == "excel_records"
        assert result.preview["record_count"] == 2

    def test_fields_filtered(self):
        item = {
            "preview_data": {"sheet_name": "S1"},
            "fields": [{"name": "col1"}, "not_a_dict", {"name": "col2"}],
        }
        result = ct._artifact_from_excel_analysis_payload(item)
        assert result is not None
        assert len(result.fields) == 2


# ===========================================================================
# _normalized_record_payload — lines 1236-1252
# ===========================================================================

class TestNormalizedRecordPayload:
    def test_basic_extraction(self):
        record = {
            "tool_id": "customers",
            "action": "query",
            "params": {"filter": "all"},
            "output": {"success": True, "rows": []},
        }
        tool_id, action, params, output = ct._normalized_record_payload(record)
        assert tool_id == "customers"
        assert action == "query"
        assert params == {"filter": "all"}
        assert output["success"] is True

    def test_defaults_action_to_execute(self):
        record = {"tool_id": "products", "output": {"success": True}}
        _, action, _, _ = ct._normalized_record_payload(record)
        assert action == "execute"

    def test_non_dict_output_wrapped(self):
        record = {"tool_id": "t", "output": "error string"}
        _, _, _, output = ct._normalized_record_payload(record)
        assert output["success"] is False
        assert "error string" in output["message"]

    def test_non_dict_params_returns_empty(self):
        record = {"tool_id": "t", "params": "not a dict"}
        _, _, params, _ = ct._normalized_record_payload(record)
        assert params == {}


# ===========================================================================
# _attach_run_id — lines 1472-1481
# ===========================================================================

class TestAttachRunId:
    def test_attaches_run_id_to_root(self):
        payload = {"success": True}
        result = ct._attach_run_id(payload, "run-123")
        assert result["run_id"] == "run-123"
        assert result["agent_run_id"] == "run-123"
        assert result["data"]["run_id"] == "run-123"

    def test_updates_existing_data_dict(self):
        payload = {"success": True, "data": {"text": "hello"}}
        result = ct._attach_run_id(payload, "run-456")
        assert result["data"]["run_id"] == "run-456"
        assert result["data"]["text"] == "hello"

    def test_creates_data_when_data_not_dict(self):
        payload = {"success": True, "data": "not a dict"}
        result = ct._attach_run_id(payload, "run-789")
        assert result["data"]["run_id"] == "run-789"


# ===========================================================================
# attach_chat_trace_run — lines 1686-1717
# ===========================================================================

class TestAttachChatTraceRun:
    def test_non_dict_payload_returned_as_is(self):
        result = ct.attach_chat_trace_run("not a dict", message="q")  # type: ignore[arg-type]
        assert result == "not a dict"

    def test_already_has_run_id_returns_as_is(self):
        payload = {"success": True, "run_id": "existing-run"}
        result = ct.attach_chat_trace_run(payload, message="q")
        assert result is payload

    def test_data_already_has_run_id(self):
        payload = {"success": True, "data": {"run_id": "existing-run"}}
        result = ct.attach_chat_trace_run(payload, message="q")
        assert result is payload

    def test_data_already_has_agent_run_id(self):
        payload = {"success": True, "data": {"agent_run_id": "existing-run"}}
        result = ct.attach_chat_trace_run(payload, message="q")
        assert result is payload

    def test_exception_returns_original_payload(self):
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.create_chat_trace_run",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = ct.attach_chat_trace_run(payload, message="test")
        assert result is payload

    def test_attaches_run_id_on_success(self, repo):
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.attach_chat_trace_run(payload, message="q", user_id="u1")
        assert "run_id" in result


# ===========================================================================
# create_chat_trace_run — lines 1597-1683
# ===========================================================================

class TestCreateChatTraceRun:
    def test_waiting_user_status(self, repo):
        payload = {"requires_token": True, "message": "需要授权", "token_name": "api_key"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.create_chat_trace_run(payload, message="test", user_id="u1")
        assert run.status == "waiting_user"
        assert any(e.event_type == "step.waiting_user" for e in run.events)

    def test_failed_status(self, repo):
        payload = {"success": False, "message": "error occurred", "error": "crashed"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.create_chat_trace_run(payload, message="test", user_id="u1")
        assert run.status == "failed"
        assert any(e.event_type == "run.failed" for e in run.events)

    def test_with_llm_trace(self, repo):
        payload = {
            "success": True,
            "response": "done",
            "_xcagi_trace": {
                "provider": "openai",
                "model": "gpt-4",
                "total_tokens": 100,
                "prompt_tokens": 70,
                "completion_tokens": 30,
            },
        }
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            with patch("app.infrastructure.billing.model_usage.record_model_usage", return_value={
                "billing_status": "unmetered", "billing_source": "est", "cost_units": 0,
                "usage_id": "u1", "usage_key": "k1",
            }):
                with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=5):
                    run = ct.create_chat_trace_run(payload, message="test", user_id="u2")
        assert run.status == "completed"

    def test_with_rag_chunks(self, repo):
        payload = {
            "success": True,
            "chunks": [{"text": "chunk1", "chunk_index": 0}],
            "response": "ok",
        }
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.create_chat_trace_run(payload, message="search query", user_id="u3")
        assert run.status == "completed"


# ===========================================================================
# finalize_legacy_chat_run — lines 1519-1594
# ===========================================================================

class TestFinalizeLegacyChatRun:
    def test_non_dict_payload_returned_as_is(self, repo):
        # When payload is not a dict, it is returned immediately (line 1530 branch)
        payload = "this is not a dict"
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run("any-run-id", payload, message="q")  # type: ignore[arg-type]
        assert result == payload

    def test_run_not_found_calls_attach(self, repo):
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run("nonexistent-run-id", payload, message="q")
        assert "run_id" in result

    def test_with_existing_run(self, repo):
        run = _make_run()
        repo.save(run)
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run(run.run_id, payload, message="q")
        assert result["run_id"] == run.run_id

    def test_waiting_user_status(self, repo):
        run = _make_run()
        repo.save(run)
        payload = {"requires_token": True, "message": "需要授权"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run(run.run_id, payload, message="q")
        updated = repo.get(run.run_id)
        assert updated is not None
        assert updated.status == "waiting_user"

    def test_failed_status(self, repo):
        run = _make_run()
        repo.save(run)
        payload = {"success": False, "message": "failed hard"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run(run.run_id, payload, message="q")
        updated = repo.get(run.run_id)
        assert updated is not None
        assert updated.status == "failed"


# ===========================================================================
# start_legacy_chat_run — lines 1484-1516
# ===========================================================================

class TestStartLegacyChatRun:
    def test_creates_run_with_running_status(self, repo):
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.start_legacy_chat_run(message="hello", user_id="u1", source="mobile")
        assert run.status == "running"
        assert run.metadata["source"] == "mobile"
        assert any(e.event_type == "run.created" for e in run.events)

    def test_creates_run_with_anonymous_user(self, repo):
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.start_legacy_chat_run(message="test")
        assert run.user_id == "anonymous"


# ===========================================================================
# _has_user_memory_marker
# ===========================================================================

class TestHasUserMemoryMarker:
    def test_marker_key_present(self):
        assert ct._has_user_memory_marker({"user_memory_rag": True}) is True

    def test_userMemoryHits_present(self):
        assert ct._has_user_memory_marker({"userMemoryHits": []}) is True

    def test_summary_with_UserMemoryRAG_text(self):
        assert ct._has_user_memory_marker({"summary": "UserMemoryRAG context"}) is True

    def test_prompt_memory_without_marker(self):
        assert ct._has_user_memory_marker({"prompt_memory": "generic context"}) is False

    def test_empty_dict(self):
        assert ct._has_user_memory_marker({}) is False


# ===========================================================================
# _append_retrieval_calls_to_final_output
# ===========================================================================

class TestAppendRetrievalCallsToFinalOutput:
    def test_empty_calls_does_nothing(self):
        run = _make_run()
        run.final_output = {"existing": "val"}
        ct._append_retrieval_calls_to_final_output(run)
        assert "retrieval_calls" not in run.final_output

    def test_appends_when_calls_present(self):
        run = _make_run()
        call = RetrievalCall(query="q", retriever="rag", source="ds", top_k=3)
        run.retrieval_calls.append(call)
        ct._append_retrieval_calls_to_final_output(run)
        assert "retrieval_calls" in run.final_output


# ===========================================================================
# _append_memory_references_to_final_output
# ===========================================================================

class TestAppendMemoryReferencesToFinalOutput:
    def test_empty_does_nothing(self):
        run = _make_run()
        run.final_output = {}
        ct._append_memory_references_to_final_output(run)
        assert "memory_references" not in run.final_output

    def test_appends_when_refs_present(self):
        run = _make_run()
        ref = MemoryReference(query="q", memory_type="user_memory", source="mem_rag", hits=[], summary="summ")
        run.memory_references.append(ref)
        ct._append_memory_references_to_final_output(run)
        assert "memory_references" in run.final_output


# ===========================================================================
# _append_artifacts_to_final_output
# ===========================================================================

class TestAppendArtifactsToFinalOutput:
    def test_empty_does_nothing(self):
        run = _make_run()
        run.final_output = {}
        ct._append_artifacts_to_final_output(run)
        assert "artifacts" not in run.final_output

    def test_appends_when_artifacts_present(self):
        run = _make_run()
        art = AgentArtifact(artifact_type="ocr_text", name="img", source="ocr")
        run.artifacts.append(art)
        run.final_output = {}
        ct._append_artifacts_to_final_output(run)
        assert "artifacts" in run.final_output

    def test_includes_dataset_ingests_if_in_metadata(self):
        run = _make_run()
        art = AgentArtifact(artifact_type="ocr_text", name="img", source="ocr")
        run.artifacts.append(art)
        run.metadata["dataset_ingests"] = [{"ds": "one"}]
        run.metadata["dataset_ingest_count"] = 1
        run.final_output = {}
        ct._append_artifacts_to_final_output(run)
        assert "dataset_ingests" in run.final_output
