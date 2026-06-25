"""Supplementary branch-coverage tests for chat_trace.py missing branches.

Targets branches not covered by test_chat_trace_cov.py:
- _trace_safe_value: long string truncation, non-dict fallthrough, dict truncation
- _iter_payload_dicts: seen-id skip, max-depth skip
- _iter_tool_call_payloads: autoAction, action==tool_call branches
- _candidate_tool_actions: empty/duplicate action, fallback defaults
- _extract_low_risk_tool_call: empty tool_id, non-dict params
- _iter_llm_trace_payloads: usage dict with model/provider
- _llm_call_from_trace: cost_units estimation, status normalization, empty trace
- _extract_llm_calls: None call skip, duplicate skip
- _refresh_llm_metadata: empty llm_calls
- _record_llm_usage_entry: failed status, wallet_debit branches, billing statuses
- _append_llm_calls_to_run: duplicate skip
- _retrieval_call_from_payload: empty payload
- _extract_retrieval_calls: None/duplicate skip
- _refresh_retrieval_metadata: empty calls
- _append_retrieval_calls_to_run: duplicate skip
- _has_user_memory_marker: UserMemoryRAG in summary
- _iter_memory_payloads: nested dict
- _first_list_value: no list found
- _memory_reference_from_payload: None branches
- _extract_memory_references: None/duplicate skip
- _append_memory_references_to_run: duplicate skip
- _iter_explicit_artifact_payloads: dict/list/single artifact
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.agent_orchestrator import chat_trace as ct
from app.application.agent_orchestrator.run_models import (
    AgentArtifact,
    AgentRun,
    LLMCall,
    MemoryReference,
    RetrievalCall,
)


@pytest.fixture(autouse=True)
def _ledger_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_BACKEND", raising=False)
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _make_run(**kwargs) -> AgentRun:
    defaults = {"user_id": "u1", "message": "hi", "status": "running", "intent": "test"}
    defaults.update(kwargs)
    return AgentRun(**defaults)


# ===========================================================================
# _trace_safe_value — missing branches [46,48], [53,61], [56,57]
# ===========================================================================


class TestTraceSafeValueBranches:
    def test_long_string_truncated_with_marker(self):
        """String longer than max gets truncated with marker (branch 46->48)."""
        s = "x" * (ct._MAX_TRACE_STRING_CHARS + 50)
        result = ct._trace_safe_value(s)
        assert result.endswith("...[truncated]")
        assert len(result) == ct._MAX_TRACE_STRING_CHARS + len("...[truncated]")

    def test_dict_truncated_sets_truncated_flag(self):
        """Dict with more items than max gets _truncated flag (branch 56->57)."""
        big = {str(i): i for i in range(ct._MAX_TRACE_DICT_ITEMS + 3)}
        result = ct._trace_safe_value(big)
        assert result.get("_truncated") is True

    def test_non_dict_non_list_falls_through_to_str(self):
        """Unknown type (not str/int/float/bool/None/list/dict) is stringified (branch 53->61)."""

        class Custom:
            def __str__(self):
                return "custom-string"

        result = ct._trace_safe_value(Custom())
        assert result == "custom-string"

    def test_dict_within_limit_no_truncation(self):
        """Dict within limit has no _truncated key."""
        small = {"a": 1, "b": 2}
        result = ct._trace_safe_value(small)
        assert "_truncated" not in result
        assert result == small

    def test_depth_limit_converts_to_str(self):
        """At depth >= 4, value is converted to truncated string."""
        nested = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = ct._trace_safe_value(nested, depth=4)
        assert isinstance(result, str)


# ===========================================================================
# _iter_payload_dicts — missing branches [115,116], [119,120]
# ===========================================================================


class TestIterPayloadDictsBranches:
    def test_seen_id_skipped(self):
        """Already-seen dict (by id) is skipped (branch 115->116)."""
        shared = {"key": "val"}
        payload = {"data": shared, "result": shared}
        results = list(ct._iter_payload_dicts(payload))
        # root + shared (shared only yielded once despite appearing in data+result)
        assert len(results) == 2
        # shared should appear only once in results (not twice)
        shared_count = sum(1 for r in results if "key" in r)
        assert shared_count == 1

    def test_max_depth_stops_recursion(self):
        """At max_depth, nested dicts are not explored (branch 119->120)."""
        deep = {"data": {"data": {"data": {"deep_key": "deep_val"}}}}
        results = list(ct._iter_payload_dicts(deep, max_depth=1))
        # Should yield root and first level, but not deeper
        assert len(results) >= 2

    def test_non_dict_nested_skipped(self):
        """Non-dict values for data/payload/result keys are skipped."""
        payload = {"data": "not-a-dict", "payload": 42, "result": None}
        results = list(ct._iter_payload_dicts(payload))
        assert len(results) == 1  # only root


# ===========================================================================
# _iter_tool_call_payloads — missing branches [135,136], [138,139]
# ===========================================================================


class TestIterToolCallPayloadsBranches:
    def test_auto_action_dict_with_tool_call_type(self):
        """autoAction dict with type=tool_call is yielded (branch 135->136)."""
        payload = {"autoAction": {"type": "tool_call", "tool_id": "t1"}}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) >= 1

    def test_auto_action_wrong_type_not_yielded(self):
        """autoAction with wrong type is not yielded."""
        payload = {"autoAction": {"type": "not_tool_call"}}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) == 0

    def test_action_equals_tool_call_with_tool_key(self):
        """action==tool_call with tool_key is yielded (branch 138->139)."""
        payload = {"action": "tool_call", "tool_key": "products", "params": {}}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) >= 1

    def test_action_equals_tool_call_without_tool_key_not_yielded(self):
        """action==tool_call without tool_key/tool_id is not yielded."""
        payload = {"action": "tool_call"}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) == 0

    def test_tool_call_dict_key_yielded(self):
        """toolCall dict key is yielded."""
        payload = {"toolCall": {"tool_id": "t1", "action": "query"}}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) >= 1

    def test_tool_call_underscore_key_yielded(self):
        """tool_call dict key is yielded."""
        payload = {"tool_call": {"tool_id": "t1"}}
        results = list(ct._iter_tool_call_payloads(payload))
        assert len(results) >= 1


# ===========================================================================
# _candidate_tool_actions — missing branches [151,-149], [161,164]
# ===========================================================================


class TestCandidateToolActionsBranches:
    def test_empty_action_added_skipped(self):
        """Empty/None action is not added (branch 151 false)."""
        result = ct._candidate_tool_actions("t1", None, {})
        assert result == []

    def test_duplicate_action_not_added(self):
        """Duplicate action is not added."""
        result = ct._candidate_tool_actions("t1", "query", {"action": "query"})
        assert result == ["query"]

    def test_nested_action_added(self):
        """Nested action from params is added."""
        result = ct._candidate_tool_actions("t1", "exec", {"action": "custom_action"})
        assert "exec" in result
        assert "custom_action" in result

    def test_fallback_defaults_for_business_db(self):
        """Fallback defaults added for business_db with execute action (branch 161->162)."""
        result = ct._candidate_tool_actions("business_db", "execute", {})
        assert "read" in result

    def test_fallback_defaults_for_customers(self):
        """Fallback defaults added for customers."""
        result = ct._candidate_tool_actions("customers", "exec", {})
        assert "query" in result

    def test_fallback_defaults_for_products(self):
        """Fallback defaults added for products."""
        result = ct._candidate_tool_actions("products", "run", {})
        assert "query" in result

    def test_fallback_defaults_for_materials(self):
        """Fallback defaults added for materials."""
        result = ct._candidate_tool_actions("materials", "view", {})
        assert "query" in result

    def test_fallback_defaults_for_shipment_records(self):
        """Fallback defaults added for shipment_records."""
        result = ct._candidate_tool_actions("shipment_records", "执行", {})
        assert "query" in result

    def test_no_fallback_for_unknown_tool(self):
        """Unknown tool_id with execute action returns just the raw action."""
        result = ct._candidate_tool_actions("unknown_tool", "execute", {})
        assert result == ["execute"]

    def test_specific_action_no_fallback(self):
        """Specific action (not execute) doesn't trigger fallback."""
        result = ct._candidate_tool_actions("business_db", "create", {})
        assert result == ["create"]


# ===========================================================================
# _extract_low_risk_tool_call — missing branches [176,177], [179,180]
# ===========================================================================


class TestExtractLowRiskToolCallBranches:
    def test_empty_tool_id_skipped(self):
        """Empty tool_id is skipped (branch 176->177)."""
        payload = {"toolCall": {"tool_id": "", "action": "query"}}
        result = ct._extract_low_risk_tool_call(payload)
        assert result is None

    def test_none_tool_id_skipped(self):
        """None tool_id is skipped."""
        payload = {"toolCall": {"tool_id": None, "action": "query"}}
        result = ct._extract_low_risk_tool_call(payload)
        assert result is None

    def test_non_dict_params_replaced_with_empty(self):
        """Non-dict params replaced with empty dict (branch 179->180)."""
        payload = {"toolCall": {"tool_id": "t1", "action": "query", "params": "not-a-dict"}}
        # This will go through validate_tool_call which may reject, but params coercion is tested
        with patch(
            "app.application.agent_orchestrator.tool_spec.validate_tool_call"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(ok=False, spec=None)
            ct._extract_low_risk_tool_call(payload)
            # Verify params was coerced to {}
            call_args = mock_validate.call_args
            assert call_args[0][2] == {}

    def test_name_key_used_as_tool_id(self):
        """name key is used as fallback for tool_id."""
        payload = {"toolCall": {"name": "products", "action": "query"}}
        with patch(
            "app.application.agent_orchestrator.tool_spec.validate_tool_call"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(ok=False, spec=None)
            ct._extract_low_risk_tool_call(payload)
            call_args = mock_validate.call_args
            assert call_args[0][0] == "products"


# ===========================================================================
# _iter_llm_trace_payloads — missing branches [223,225], [225,216], [225,226]
# ===========================================================================


class TestIterLlmTracePayloadsBranches:
    def test_usage_not_dict_skipped(self):
        """Non-dict usage is skipped (branch 223->225->216)."""
        payload = {"usage": "not-a-dict"}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) == 0

    def test_usage_dict_without_model_skipped(self):
        """Usage dict without model/provider is skipped (branch 225->216)."""
        payload = {"usage": {"prompt_tokens": 10}}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) == 0

    def test_usage_dict_with_model_yielded(self):
        """Usage dict with model is yielded (branch 225->226)."""
        payload = {"usage": {"prompt_tokens": 10}, "model": "gpt-4"}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) >= 1
        assert results[0]["model"] == "gpt-4"

    def test_usage_dict_with_provider_yielded(self):
        """Usage dict with provider is yielded."""
        payload = {"usage": {"total_tokens": 5}, "provider": "openai"}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) >= 1

    def test_usage_dict_with_provider_id_yielded(self):
        """Usage dict with provider_id is yielded."""
        payload = {"usage": {"total_tokens": 5}, "provider_id": "openai"}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) >= 1

    def test_xcagi_trace_key_yielded(self):
        """_xcagi_trace key is yielded."""
        payload = {"_xcagi_trace": {"model": "gpt-4", "prompt_tokens": 10}}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) >= 1

    def test_llm_trace_key_yielded(self):
        """llm_trace key is yielded."""
        payload = {"llm_trace": {"model": "gpt-4"}}
        results = list(ct._iter_llm_trace_payloads(payload))
        assert len(results) >= 1


# ===========================================================================
# _llm_call_from_trace — missing branches [273,274], [282,283], [285,288], [292,293]
# ===========================================================================


class TestLlmCallFromTraceBranches:
    def test_cost_units_estimated_when_zero(self):
        """cost_units estimated when not provided (branch 273->274)."""
        trace = {"model": "gpt-4", "prompt_tokens": 100, "completion_tokens": 50}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.cost_units > 0

    def test_cost_units_used_when_provided(self):
        """cost_units used when provided (branch 273 false)."""
        trace = {"model": "gpt-4", "cost_units": 999}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.cost_units == 999

    def test_status_normalized_to_completed(self):
        """Unknown status normalized to completed (branch 282->283)."""
        trace = {"model": "gpt-4", "status": "weird"}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.status == "completed"

    def test_status_failed_preserved(self):
        """Failed status preserved."""
        trace = {"model": "gpt-4", "status": "failed", "error": "oops"}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.status == "failed"

    def test_empty_trace_returns_none(self):
        """Empty trace returns None (branch 285->288)."""
        result = ct._llm_call_from_trace({})
        assert result is None

    def test_trace_with_only_error_returns_call(self):
        """Trace with only error returns a call."""
        trace = {"error": "something went wrong"}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.error == "something went wrong"

    def test_call_id_added_when_present(self):
        """call_id added to kwargs when present (branch 292->293)."""
        trace = {"model": "gpt-4", "call_id": "call-123"}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.call_id == "call-123"

    def test_call_id_not_added_when_absent(self):
        """call_id not in kwargs when absent."""
        trace = {"model": "gpt-4"}
        result = ct._llm_call_from_trace(trace)
        assert result is not None
        # call_id should be auto-generated
        assert result.call_id  # has a default

    def test_billing_status_defaults_to_metered(self):
        """billing_status defaults to 'metered' when cost_units > 0."""
        trace = {"model": "gpt-4", "cost_units": 10}
        result = ct._llm_call_from_trace(trace)
        assert result.billing_status == "metered"

    def test_billing_status_defaults_to_unmetered(self):
        """billing_status defaults to 'unmetered' when no cost_units."""
        trace = {"model": "gpt-4"}
        result = ct._llm_call_from_trace(trace)
        assert result.billing_status == "unmetered"

    def test_billing_source_defaults_to_estimated(self):
        """billing_source defaults to 'estimated_token_units'."""
        trace = {"model": "gpt-4"}
        result = ct._llm_call_from_trace(trace)
        assert result.billing_source == "estimated_token_units"


# ===========================================================================
# _extract_llm_calls — missing branches [317,318], [320,321]
# ===========================================================================


class TestExtractLlmCallsBranches:
    def test_none_call_skipped(self):
        """None call is skipped (branch 317->318)."""
        payload = {"_xcagi_trace": {}}  # empty trace -> None call
        result = ct._extract_llm_calls(payload)
        assert result == []

    def test_duplicate_call_skipped(self):
        """Duplicate call (same signature) is skipped (branch 320->321)."""
        trace = {"model": "gpt-4", "prompt_tokens": 10}
        payload = {
            "_xcagi_trace": trace,
            "llm_trace": trace,  # same trace, same signature
        }
        result = ct._extract_llm_calls(payload)
        assert len(result) == 1


# ===========================================================================
# _refresh_llm_metadata — missing branch [338,-327]
# ===========================================================================


class TestRefreshLlmMetadataBranches:
    def test_empty_llm_calls_no_last_call_metadata(self):
        """Empty llm_calls doesn't set llm_provider/llm_model (branch 338 false)."""
        run = _make_run()
        run.llm_calls = []
        ct._refresh_llm_metadata(run)
        assert "llm_provider" not in run.metadata
        assert "llm_model" not in run.metadata

    def test_with_llm_calls_sets_last_call_metadata(self):
        """With llm_calls, last call provider/model set."""
        run = _make_run()
        run.llm_calls = [LLMCall(provider_id="openai", provider="openai", model="gpt-4")]
        ct._refresh_llm_metadata(run)
        assert run.metadata["llm_provider"] == "openai"
        assert run.metadata["llm_model"] == "gpt-4"


# ===========================================================================
# _record_llm_usage_entry — missing branches [352,353], [400,402], [437,438]
# ===========================================================================


class TestRecordLlmUsageEntryBranches:
    def test_failed_status_returns_none(self):
        """Failed status returns None (branch 352->353)."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="failed", error="err")
        result = ct._record_llm_usage_entry(run, call)
        assert result is None

    def test_wallet_debit_empty_skips_metadata(self):
        """Empty wallet_debit doesn't add to call metadata (branch 400 false)."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.return_value = {
                "billing_status": "recorded",
                "cost_units": 5,
                "wallet_debit": None,
            }
            result = ct._record_llm_usage_entry(run, call)
        assert result is not None
        assert "wallet_debit" not in call.metadata

    def test_billing_status_market_debit_failed(self):
        """billing_status=market_debit_failed sets run to failed (branch 437->438)."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.return_value = {
                "billing_status": "market_debit_failed",
                "cost_units": 5,
                "wallet_debit": {},
            }
            ct._record_llm_usage_entry(run, call)
        assert run.status == "failed"
        assert "wallet debit failed" in run.error.lower()

    def test_billing_status_recorded(self):
        """billing_status=recorded adds billing.recorded event."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.return_value = {
                "billing_status": "recorded",
                "cost_units": 5,
                "wallet_debit": {},
            }
            ct._record_llm_usage_entry(run, call)
        events = [e for e in run.events if e.event_type == "billing.recorded"]
        assert len(events) >= 1

    def test_billing_status_debited_with_balance(self):
        """billing_status=debited with wallet balance sets metadata."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.return_value = {
                "billing_status": "debited",
                "cost_units": 5,
                "wallet_debit": {
                    "balance_after_units": 1000,
                    "balance_after_yuan": 9.9,
                },
            }
            ct._record_llm_usage_entry(run, call)
        assert run.metadata["model_wallet_balance_units"] == 1000
        assert run.metadata["model_wallet_balance_yuan"] == 9.9

    def test_billing_status_insufficient_balance(self):
        """billing_status=insufficient_balance sets run to failed."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.return_value = {
                "billing_status": "insufficient_balance",
                "cost_units": 5,
                "wallet_debit": {"balance_after_units": 0},
            }
            ct._record_llm_usage_entry(run, call)
        assert run.status == "failed"
        assert "insufficient" in run.error.lower()

    def test_record_model_usage_error_swallowed(self):
        """RECOVERABLE_ERRORS from record_model_usage are swallowed."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed", cost_units=5)
        with patch("app.infrastructure.billing.model_usage.record_model_usage") as mock_rec:
            mock_rec.side_effect = ConnectionError("ledger down")
            result = ct._record_llm_usage_entry(run, call)
        assert result is None
        assert run.metadata["model_usage_ledger_status"] == "failed"


# ===========================================================================
# _append_llm_calls_to_run — missing branch [450,451]
# ===========================================================================


class TestAppendLlmCallsToRunBranches:
    def test_duplicate_call_skipped(self):
        """Duplicate call signature is skipped (branch 450->451)."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed")
        run.llm_calls.append(call)
        with patch.object(ct, "_record_llm_usage_entry") as mock_rec:
            ct._append_llm_calls_to_run(run, [call])
        mock_rec.assert_not_called()

    def test_new_call_appended(self):
        """New call is appended and usage recorded."""
        run = _make_run()
        call = LLMCall(provider_id="openai", model="gpt-4", status="completed")
        with patch.object(ct, "_record_llm_usage_entry") as mock_rec:
            ct._append_llm_calls_to_run(run, [call])
        assert len(run.llm_calls) == 1
        mock_rec.assert_called_once()


# ===========================================================================
# _retrieval_call_from_payload — missing branch [542,543]
# ===========================================================================


class TestRetrievalCallFromPayloadBranches:
    def test_empty_payload_returns_none(self):
        """Empty payload (no chunks/citations/error) returns None (branch 542->543)."""
        result = ct._retrieval_call_from_payload({}, default_query="q")
        assert result is None

    def test_with_error_returns_failed_call(self):
        """With error, returns failed call."""
        result = ct._retrieval_call_from_payload({"rag_error": "retriever down"}, default_query="q")
        assert result is not None
        assert result.status == "failed"
        assert result.error == "retriever down"

    def test_with_chunks_returns_completed_call(self):
        """With chunks, returns completed call."""
        result = ct._retrieval_call_from_payload(
            {"chunks": [{"text": "chunk1"}], "query": "search"}, default_query="default"
        )
        assert result is not None
        assert result.status == "completed"
        assert len(result.chunks) == 1
        assert result.query == "search"

    def test_with_citations_returns_call(self):
        """With citations, returns call."""
        result = ct._retrieval_call_from_payload(
            {"citations": [{"source": "doc1"}]}, default_query="q"
        )
        assert result is not None
        assert len(result.citations) == 1

    def test_default_query_used_when_no_query(self):
        """Default query used when payload has no query."""
        result = ct._retrieval_call_from_payload(
            {"chunks": [{"text": "x"}]}, default_query="fallback-query"
        )
        assert result.query == "fallback-query"

    def test_top_k_from_payload(self):
        """top_k read from payload."""
        result = ct._retrieval_call_from_payload(
            {"chunks": [{"text": "x"}], "top_k": 5}, default_query="q"
        )
        assert result.top_k == 5

    def test_top_k_defaults_to_chunk_count(self):
        """top_k defaults to chunk count when not specified."""
        result = ct._retrieval_call_from_payload(
            {"chunks": [{"text": "x"}, {"text": "y"}, {"text": "z"}]}, default_query="q"
        )
        assert result.top_k == 3


# ===========================================================================
# _extract_retrieval_calls — missing branches [592,593], [595,596]
# ===========================================================================


class TestExtractRetrievalCallsBranches:
    def test_none_call_skipped(self):
        """None call is skipped (branch 592->593)."""
        payload = {"chunks": None, "citations": None, "rag_error": None, "rag_enabled": None}
        result = ct._extract_retrieval_calls(payload)
        assert result == []

    def test_duplicate_call_skipped(self):
        """Duplicate call signature is skipped (branch 595->596)."""
        item = {"chunks": [{"text": "x"}], "query": "q"}
        payload = {"data": item, "result": item}
        result = ct._extract_retrieval_calls(payload)
        assert len(result) <= 1


# ===========================================================================
# _refresh_retrieval_metadata — missing branch [606,-602]
# ===========================================================================


class TestRefreshRetrievalMetadataBranches:
    def test_empty_retrieval_calls_no_metadata(self):
        """Empty retrieval_calls doesn't set retriever/retrieval_source (branch 606 false)."""
        run = _make_run()
        run.retrieval_calls = []
        ct._refresh_retrieval_metadata(run)
        assert "retriever" not in run.metadata
        assert "retrieval_source" not in run.metadata

    def test_with_calls_sets_last_call_metadata(self):
        """With calls, last call retriever/source set."""
        run = _make_run()
        run.retrieval_calls = [
            RetrievalCall(query="q", retriever="rag", source="dataset1", chunks=[], citations=[])
        ]
        ct._refresh_retrieval_metadata(run)
        assert run.metadata["retriever"] == "rag"
        assert run.metadata["retrieval_source"] == "dataset1"


# ===========================================================================
# _append_retrieval_calls_to_run — missing branch [616,617]
# ===========================================================================


class TestAppendRetrievalCallsToRunBranches:
    def test_duplicate_call_skipped(self):
        """Duplicate retrieval call is skipped (branch 616->617)."""
        run = _make_run()
        call = RetrievalCall(query="q", retriever="rag", source="s", chunks=[], citations=[])
        run.retrieval_calls.append(call)
        ct._append_retrieval_calls_to_run(run, [call])
        assert len(run.retrieval_calls) == 1

    def test_new_call_appended(self):
        """New retrieval call is appended."""
        run = _make_run()
        call = RetrievalCall(query="q", retriever="rag", source="s", chunks=[], citations=[])
        ct._append_retrieval_calls_to_run(run, [call])
        assert len(run.retrieval_calls) == 1


# ===========================================================================
# _has_user_memory_marker — missing branch [690,691]
# ===========================================================================


class TestHasUserMemoryMarkerBranches:
    def test_user_memory_rag_in_summary(self):
        """'UserMemoryRAG' in summary string returns True (branch 690->691)."""
        item = {"summary": "Some UserMemoryRAG context here"}
        assert ct._has_user_memory_marker(item) is True

    def test_user_memory_rag_in_memory_summary(self):
        """'UserMemoryRAG' in memory_summary returns True."""
        item = {"memory_summary": "UserMemoryRAG result"}
        assert ct._has_user_memory_marker(item) is True

    def test_user_memory_rag_in_prompt_memory(self):
        """'UserMemoryRAG' in prompt_memory returns True."""
        item = {"prompt_memory": "UserMemoryRAG data"}
        assert ct._has_user_memory_marker(item) is True

    def test_user_memory_rag_in_context(self):
        """'UserMemoryRAG' in context returns True."""
        item = {"context": "UserMemoryRAG info"}
        assert ct._has_user_memory_marker(item) is True

    def test_no_marker_returns_false(self):
        """No marker keys and no UserMemoryRAG returns False."""
        item = {"summary": "just a summary", "context": "some context"}
        assert ct._has_user_memory_marker(item) is False

    def test_marker_key_present(self):
        """Marker key presence returns True."""
        assert ct._has_user_memory_marker({"user_memory_rag": {}}) is True
        assert ct._has_user_memory_marker({"userMemoryRag": {}}) is True
        assert ct._has_user_memory_marker({"user_memory_hits": []}) is True
        assert ct._has_user_memory_marker({"userMemoryHits": []}) is True
        assert ct._has_user_memory_marker({"user_memory_error": "err"}) is True
        assert ct._has_user_memory_marker({"userMemoryError": "err"}) is True


# ===========================================================================
# _iter_memory_payloads — missing branch [707,708]
# ===========================================================================


class TestIterMemoryPayloadsBranches:
    def test_nested_dict_yielded(self):
        """Nested user_memory_rag dict is yielded (branch 707->708)."""
        payload = {"user_memory_rag": {"summary": "mem"}}
        results = list(ct._iter_memory_payloads(payload))
        assert len(results) >= 1

    def test_nested_camel_dict_yielded(self):
        """Nested userMemoryRag dict is yielded."""
        payload = {"userMemoryRag": {"summary": "mem"}}
        results = list(ct._iter_memory_payloads(payload))
        assert len(results) >= 1

    def test_memory_reference_key_yielded(self):
        """memory_reference dict is yielded."""
        payload = {"memory_reference": {"hits": []}}
        results = list(ct._iter_memory_payloads(payload))
        assert len(results) >= 1

    def test_non_dict_nested_skipped(self):
        """Non-dict nested value is skipped (root has marker key so it's yielded)."""
        payload = {"user_memory_rag": "not-a-dict"}
        results = list(ct._iter_memory_payloads(payload))
        # Root is yielded because it has the marker key, but nested non-dict is not
        assert len(results) == 1
        # The nested non-dict value is not yielded as a separate item
        assert results[0] == payload


# ===========================================================================
# _first_list_value — missing branches [712,716], [714,712]
# ===========================================================================


class TestFirstListValueBranches:
    def test_no_list_found_returns_empty(self):
        """No list value found returns empty list (branch 712->716)."""
        result = ct._first_list_value({"key1": "str", "key2": 42}, ("key1", "key2", "key3"))
        assert result == []

    def test_first_list_returned(self):
        """First list value is returned (branch 714->712)."""
        result = ct._first_list_value({"key1": [1, 2], "key2": [3, 4]}, ("key1", "key2"))
        assert result == [1, 2]

    def test_second_key_list_returned_when_first_not_list(self):
        """Second key's list returned when first key is not a list."""
        result = ct._first_list_value({"key1": "str", "key2": [3, 4]}, ("key1", "key2"))
        assert result == [3, 4]

    def test_empty_list_returned(self):
        """Empty list is returned as-is."""
        result = ct._first_list_value({"key1": []}, ("key1",))
        assert result == []


# ===========================================================================
# _memory_reference_from_payload — missing branches [757,758], [759,760]
# ===========================================================================


class TestMemoryReferenceFromPayloadBranches:
    def test_no_marker_no_hits_no_summary_returns_none(self):
        """No marker, no hits, no UserMemoryRAG in summary returns None (branch 757->758)."""
        result = ct._memory_reference_from_payload({"summary": "just text"}, default_query="q")
        assert result is None

    def test_marker_but_no_content_returns_none(self):
        """Has marker but no hits/summary/error returns None (branch 759->760)."""
        result = ct._memory_reference_from_payload({"user_memory_rag": True}, default_query="q")
        assert result is None

    def test_with_hits_returns_reference(self):
        """With hits returns a reference."""
        result = ct._memory_reference_from_payload(
            {"user_memory_hits": [{"chunk_id": "c1"}], "query": "q"}, default_query="default"
        )
        assert result is not None
        assert len(result.hits) == 1
        assert result.query == "q"

    def test_with_summary_returns_reference(self):
        """With summary returns a reference."""
        result = ct._memory_reference_from_payload(
            {"user_memory_rag_summary": "memory summary"}, default_query="q"
        )
        assert result is not None
        assert result.summary == "memory summary"

    def test_with_error_returns_failed_reference(self):
        """With error returns failed reference."""
        result = ct._memory_reference_from_payload(
            {"user_memory_error": "memory error"}, default_query="q"
        )
        assert result is not None
        assert result.status == "failed"
        assert result.error == "memory error"

    def test_summary_with_user_memory_rag_marker(self):
        """Summary containing UserMemoryRAG triggers reference creation."""
        result = ct._memory_reference_from_payload(
            {"summary": "UserMemoryRAG: recalled 3 items"}, default_query="q"
        )
        assert result is not None


# ===========================================================================
# _extract_memory_references — missing branches [816,817], [819,820]
# ===========================================================================


class TestExtractMemoryReferencesBranches:
    def test_none_reference_skipped(self):
        """None reference is skipped (branch 816->817)."""
        payload = {"user_memory_rag": True}  # marker but no content -> None
        result = ct._extract_memory_references(payload)
        assert result == []

    def test_duplicate_reference_skipped(self):
        """Duplicate reference signature is skipped (branch 819->820)."""
        item = {"user_memory_hits": [{"chunk_id": "c1"}], "query": "q"}
        payload = {"data": item, "result": item}
        result = ct._extract_memory_references(payload)
        assert len(result) <= 1


# ===========================================================================
# _append_memory_references_to_run — missing branch [843,844]
# ===========================================================================


class TestAppendMemoryReferencesToRunBranches:
    def test_duplicate_reference_skipped(self):
        """Duplicate memory reference is skipped (branch 843->844)."""
        run = _make_run()
        ref = MemoryReference(
            query="q", memory_type="user_memory", source="s", hits=[], summary="sum"
        )
        run.memory_references.append(ref)
        ct._append_memory_references_to_run(run, [ref])
        assert len(run.memory_references) == 1

    def test_new_reference_appended(self):
        """New memory reference is appended."""
        run = _make_run()
        ref = MemoryReference(
            query="q", memory_type="user_memory", source="s", hits=[], summary="sum"
        )
        ct._append_memory_references_to_run(run, [ref])
        assert len(run.memory_references) == 1


# ===========================================================================
# _iter_explicit_artifact_payloads — missing branches [891,892], [893,894]
# ===========================================================================


class TestIterExplicitArtifactPayloadsBranches:
    def test_artifacts_dict_yielded(self):
        """artifacts as dict is yielded (branch 891->892)."""
        payload = {"artifacts": {"type": "doc", "name": "test"}}
        results = list(ct._iter_explicit_artifact_payloads(payload))
        assert len(results) >= 1

    def test_artifacts_list_yielded(self):
        """artifacts as list yields each dict (branch 893->894)."""
        payload = {"artifacts": [{"name": "a1"}, {"name": "a2"}]}
        results = list(ct._iter_explicit_artifact_payloads(payload))
        assert len(results) >= 2

    def test_artifact_single_dict_yielded(self):
        """artifact single dict is yielded."""
        payload = {"artifact": {"name": "single"}}
        results = list(ct._iter_explicit_artifact_payloads(payload))
        assert len(results) >= 1

    def test_artifacts_list_with_non_dict_skipped(self):
        """Non-dict items in artifacts list are skipped."""
        payload = {"artifacts": ["str", 42, {"name": "valid"}]}
        results = list(ct._iter_explicit_artifact_payloads(payload))
        assert len(results) >= 1

    def test_no_artifacts_returns_empty(self):
        """No artifacts keys returns empty."""
        payload = {"other": "value"}
        results = list(ct._iter_explicit_artifact_payloads(payload))
        assert len(results) == 0


# ===========================================================================
# _coerce_trace_int / _coerce_trace_float
# ===========================================================================


class TestCoerceTraceInt:
    def test_none_returns_zero(self):
        assert ct._coerce_trace_int(None) == 0

    def test_int_returns_int(self):
        assert ct._coerce_trace_int(42) == 42

    def test_string_number_returns_int(self):
        assert ct._coerce_trace_int("42") == 42

    def test_invalid_string_returns_zero(self):
        assert ct._coerce_trace_int("abc") == 0

    def test_float_returns_int(self):
        assert ct._coerce_trace_int(3.7) == 3

    def test_empty_string_returns_zero(self):
        assert ct._coerce_trace_int("") == 0


class TestCoerceTraceFloat:
    def test_none_returns_zero(self):
        assert ct._coerce_trace_float(None) == 0.0

    def test_float_returns_float(self):
        assert ct._coerce_trace_float(3.14) == 3.14

    def test_string_number_returns_float(self):
        assert ct._coerce_trace_float("2.5") == 2.5

    def test_invalid_string_returns_zero(self):
        assert ct._coerce_trace_float("abc") == 0.0

    def test_int_returns_float(self):
        assert ct._coerce_trace_float(5) == 5.0


# ===========================================================================
# _payload_data
# ===========================================================================


class TestPayloadData:
    def test_dict_data_returned(self):
        assert ct._payload_data({"data": {"key": "val"}}) == {"key": "val"}

    def test_non_dict_data_returns_empty(self):
        assert ct._payload_data({"data": "str"}) == {}

    def test_missing_data_returns_empty(self):
        assert ct._payload_data({}) == {}


# ===========================================================================
# _extract_legacy_tool_records
# ===========================================================================


class TestExtractLegacyToolRecords:
    def test_legacy_tool_records_key(self):
        payload = {"legacy_tool_records": [{"id": 1}, {"id": 2}]}
        result = ct._extract_legacy_tool_records(payload)
        assert len(result) == 2

    def test_tool_records_key(self):
        payload = {"tool_records": [{"id": 1}]}
        result = ct._extract_legacy_tool_records(payload)
        assert len(result) == 1

    def test_underscore_tool_records_key(self):
        payload = {"_tool_records": [{"id": 1}]}
        result = ct._extract_legacy_tool_records(payload)
        assert len(result) == 1

    def test_non_list_records_returns_empty(self):
        payload = {"legacy_tool_records": "not-a-list"}
        result = ct._extract_legacy_tool_records(payload)
        assert result == []

    def test_filters_non_dict_records(self):
        payload = {"legacy_tool_records": [{"id": 1}, "str", 42, {"id": 2}]}
        result = ct._extract_legacy_tool_records(payload)
        assert len(result) == 2

    def test_no_records_returns_empty(self):
        payload = {"other": "value"}
        result = ct._extract_legacy_tool_records(payload)
        assert result == []
