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
        # At/over depth 4 the recursion stops and the value is stringified
        # rather than walked, so a dict comes back as its repr string.
        result = ct._trace_safe_value({"key": "val"}, depth=4)
        assert result == str({"key": "val"})

    def test_depth_limit_truncates_long_repr(self):
        # The stringified value is also capped at _MAX_TRACE_STRING_CHARS.
        big = {"k": "x" * (ct._MAX_TRACE_STRING_CHARS + 500)}
        result = ct._trace_safe_value(big, depth=4)
        assert isinstance(result, str)
        assert len(result) == ct._MAX_TRACE_STRING_CHARS

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
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=0
        ):
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
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=10
        ):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.model == "gpt-4"
        assert result.provider_id == "openai"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150
        # estimate is used because trace carries no explicit cost_units
        assert result.cost_units == 10
        assert result.billing_status == "metered"
        assert result.billing_source == "estimated_token_units"
        assert result.status == "completed"
        # raw trace is stashed in metadata for downstream auditing
        assert result.metadata["raw_trace"]["model"] == "gpt-4"

    def test_camel_case_fields(self):
        trace = {
            "providerId": "azure",
            "modelName": "gpt-4o",
            "promptTokens": 200,
            "completionTokens": 100,
            "totalTokens": 300,
        }
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=20
        ):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        # camelCase keys must be parsed into every snake_case field
        assert result.provider_id == "azure"
        # provider falls back to provider_id when no explicit provider given
        assert result.provider == "azure"
        assert result.model == "gpt-4o"
        assert result.prompt_tokens == 200
        assert result.completion_tokens == 100
        assert result.total_tokens == 300
        # cost_units comes from the estimate (no explicit cost_units in trace)
        assert result.cost_units == 20
        # non-zero cost flips billing_status to "metered"
        assert result.billing_status == "metered"

    def test_invalid_status_normalized(self):
        trace = {
            "provider": "anthropic",
            "model": "claude-3",
            "total_tokens": 100,
            "status": "weird_status",
        }
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=5
        ):
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
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=3
        ):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.call_id == "cid-abc"

    def test_error_field_creates_call_marked_unmetered(self):
        # An error alone (no tokens) is enough to materialize a call object.
        trace = {"error": "timeout", "provider": "openai", "model": "gpt-4"}
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=0
        ):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.error == "timeout"
        # zero cost_units -> billing_status defaults to "unmetered"
        assert result.cost_units == 0
        assert result.billing_status == "unmetered"
        # status is not in the trace, so it normalizes to "completed"
        assert result.status == "completed"

    def test_explicit_cost_units_bypasses_estimate(self):
        trace = {
            "provider": "openai",
            "model": "gpt-4",
            "total_tokens": 100,
            "cost_units": 5,
        }
        estimate = MagicMock(return_value=999)
        with patch("app.infrastructure.billing.model_usage.estimate_llm_cost_units", estimate):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        # explicit cost_units > 0 -> estimator must NOT be consulted
        estimate.assert_not_called()
        assert result.cost_units == 5
        assert result.billing_status == "metered"

    def test_call_id_absent_generates_default(self):
        # When no call_id is in the trace, the dataclass default kicks in.
        trace = {"provider": "openai", "model": "gpt-4", "total_tokens": 10}
        with patch(
            "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=1
        ):
            result = ct._llm_call_from_trace(trace)
        assert result is not None
        assert result.call_id.startswith("llm_")


# ===========================================================================
# _append_llm_calls_to_run / _refresh_llm_metadata — lines 446-473
# ===========================================================================


class TestAppendLlmCallsToRun:
    def test_skips_duplicate_calls(self, repo):
        run = _make_run()
        # Pre-populate run.llm_calls with a call so its signature is in existing
        pre_call = LLMCall(
            provider_id="openai",
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            billing_status="unmetered",
        )
        run.llm_calls.append(pre_call)
        # Now try to append another call with the same signature
        dup_call = LLMCall(
            provider_id="openai",
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            billing_status="unmetered",
        )
        entry = {
            "billing_status": "unmetered",
            "billing_source": "est",
            "cost_units": 0,
            "usage_id": "u1",
            "usage_key": "k1",
        }
        record = MagicMock(return_value=entry)
        with patch("app.infrastructure.billing.model_usage.record_model_usage", record):
            ct._append_llm_calls_to_run(run, [dup_call])
        # The duplicate (identical signature) must be skipped entirely:
        assert len(run.llm_calls) == 1
        # the originally-appended object is preserved, not the duplicate
        assert run.llm_calls[0] is pre_call
        # no billing recorded and no llm.completed event emitted for a skip
        record.assert_not_called()
        assert not any(e.event_type == "llm.completed" for e in run.events)

    def test_adds_new_calls_and_refreshes_metadata(self, repo):
        run = _make_run()
        call = LLMCall(
            provider_id="openai",
            provider="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_units=10,
        )
        with patch(
            "app.infrastructure.billing.model_usage.record_model_usage",
            return_value={
                "billing_status": "metered",
                "billing_source": "est",
                "cost_units": 10,
                "usage_id": "uid1",
                "usage_key": "k1",
            },
        ):
            ct._append_llm_calls_to_run(run, [call])
        # call appended
        assert run.llm_calls == [call]
        # metadata aggregates token + cost totals across all calls
        assert run.metadata["llm_call_count"] == 1
        assert run.metadata["llm_model"] == "gpt-4"
        assert run.metadata["llm_provider"] == "openai"
        assert run.metadata["llm_prompt_tokens_total"] == 100
        assert run.metadata["llm_completion_tokens_total"] == 50
        assert run.metadata["llm_token_total"] == 150
        assert run.metadata["llm_cost_units_total"] == 10
        # an llm.completed event is emitted for a successful call
        completed = [e for e in run.events if e.event_type == "llm.completed"]
        assert len(completed) == 1
        assert completed[0].data["model"] == "gpt-4"
        assert completed[0].data["total_tokens"] == 150


# ===========================================================================
# _record_llm_usage_entry billing branches — lines 351-443
# ===========================================================================


class TestRecordLlmUsageEntry:
    def test_non_completed_returns_none_and_no_side_effects(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10, status="failed")
        record = MagicMock()
        with patch("app.infrastructure.billing.model_usage.record_model_usage", record):
            result = ct._record_llm_usage_entry(run, call)
        # a non-completed call short-circuits before touching the ledger
        assert result is None
        record.assert_not_called()
        assert "model_usage_ledger_status" not in run.metadata
        assert run.events == []

    def test_debited_status_sets_balance_and_emits_event(self):
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
            result = ct._record_llm_usage_entry(run, call)
        # returned entry is the ledger result
        assert result is entry
        # wallet balances mirrored into run metadata
        assert run.metadata["model_wallet_balance_units"] == 950
        assert run.metadata["model_wallet_balance_yuan"] == "9.50"
        # billing fields on the call are overwritten from the ledger entry
        assert call.billing_status == "debited"
        assert call.billing_source == "wallet"
        # usage ledger trail recorded on the call + run metadata accounting
        assert call.metadata["usage_ledger"]["usage_id"] == "u1"
        assert call.metadata["usage_ledger"]["status"] == "recorded"
        assert run.metadata["model_usage_ledger_status"] == "recorded"
        assert run.metadata["model_usage_entry_count"] == 1
        assert run.metadata["model_usage_cost_units_total"] == 5
        # a debited event (not the generic recorded one) is emitted
        debited = [e for e in run.events if e.event_type == "billing.debited"]
        assert len(debited) == 1
        assert debited[0].data["cost_units"] == 5
        # run stays unaffected (not failed) on a successful debit
        assert run.status == "running"

    def test_insufficient_balance_fails_run_with_error(self):
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
        assert run.error == "AI wallet balance insufficient"
        assert run.metadata["model_wallet_balance_units"] == 0
        assert any(e.event_type == "billing.insufficient_balance" for e in run.events)
        # the generic recorded event must NOT be emitted on this failure branch
        assert not any(e.event_type == "billing.recorded" for e in run.events)

    def test_market_debit_failed_fails_run_with_error(self):
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
        assert run.error == "AI market wallet debit failed"
        assert any(e.event_type == "billing.debit_failed" for e in run.events)

    def test_billing_record_failure_adds_event_and_marks_metadata(self):
        run = _make_run()
        call = LLMCall(provider_id="x", provider="x", model="m", total_tokens=10)
        # RuntimeError is in RECOVERABLE_ERRORS, so it is swallowed (tracing must
        # never break the chat response) but recorded as a failure event.
        with patch(
            "app.infrastructure.billing.model_usage.record_model_usage",
            side_effect=RuntimeError("ledger down"),
        ):
            result = ct._record_llm_usage_entry(run, call)
        assert result is None
        assert run.metadata["model_usage_ledger_status"] == "failed"
        failed = [e for e in run.events if e.event_type == "billing.record_failed"]
        assert len(failed) == 1
        assert failed[0].data["error"] == "ledger down"
        # the run itself is NOT failed by a ledger write error
        assert run.status == "running"

    def test_unmetered_billing_emits_recorded_event(self):
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
        # the generic recorded event fires for unmetered usage
        recorded = [e for e in run.events if e.event_type == "billing.recorded"]
        assert len(recorded) == 1
        # no wallet/failure side effects on the unmetered path
        assert "model_wallet_balance_units" not in run.metadata
        assert run.status == "running"
        # wallet_debit None coerces to {} so no wallet_debit metadata on the call
        assert "wallet_debit" not in call.metadata


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
        # query defaults from the supplied default_query when item has none
        assert result.query == "query"
        # retriever defaults to "rag" when unspecified
        assert result.retriever == "rag"

    def test_with_chunks(self):
        item = {"chunks": [{"text": "chunk1", "chunk_index": 0}]}
        result = ct._retrieval_call_from_payload(item, default_query="find something")
        assert result is not None
        assert result.status == "completed"
        assert result.error == ""
        assert len(result.chunks) == 1
        # the chunk content is carried through verbatim
        assert result.chunks[0]["text"] == "chunk1"
        assert result.chunks[0]["chunk_index"] == 0
        # top_k falls back to chunk count when not provided
        assert result.top_k == 1
        # default_query is adopted as the query
        assert result.query == "find something"

    def test_with_citations(self):
        item = {"citations": [{"source": "doc.pdf", "text": "ref"}]}
        result = ct._retrieval_call_from_payload(item, default_query="q")
        assert result is not None
        assert result.status == "completed"
        assert len(result.citations) == 1
        assert result.citations[0]["source"] == "doc.pdf"
        # citations-only (no chunks) => top_k stays 0 since no chunks to count
        assert result.top_k == 0

    def test_top_k_explicit_overrides_chunk_count(self):
        item = {"chunks": [{"text": "c"}], "top_k": 5}
        result = ct._retrieval_call_from_payload(item, default_query="q")
        assert result is not None
        # explicit top_k=5 wins over the (1) chunk count
        assert result.top_k == 5

    def test_source_resolved_from_dataset_id(self):
        item = {"chunks": [{"text": "c"}], "dataset_id": "ds-42"}
        result = ct._retrieval_call_from_payload(item, default_query="q")
        assert result is not None
        assert result.source == "ds-42"


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
        assert result.status == "completed"
        # hits carried through with content intact
        assert len(result.hits) == 1
        assert result.hits[0]["chunk_id"] == "c1"
        assert result.hits[0]["content"] == "some memory"
        # default query adopted, default memory_type/source applied
        assert result.query == "search"
        assert result.memory_type == "user_memory"
        assert result.source == "user_memory_rag"
        # hit_count metadata reflects number of hits
        assert result.metadata["hit_count"] == 1

    def test_with_error(self):
        item = {"user_memory_error": "memory fetch failed", "user_memory_rag": True}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None
        assert result.status == "failed"
        assert result.error == "memory fetch failed"
        assert result.hits == []

    def test_with_userMemoryRag_marker(self):
        item = {
            "userMemoryRag": True,
            "userMemoryRagSummary": "summary text",
        }
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None
        # camelCase summary key is read
        assert result.summary == "summary text"
        assert result.status == "completed"
        assert result.query == "q"

    def test_summary_containing_UserMemoryRAG_token(self):
        # No explicit marker key, but the literal "UserMemoryRAG" inside the
        # summary text is itself a recognized marker.
        item = {"summary": "UserMemoryRAG context loaded"}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is not None
        assert result.summary == "UserMemoryRAG context loaded"
        assert result.status == "completed"

    def test_summary_without_marker_token_returns_none(self):
        # A summary without the special token and no marker key -> not a memory ref.
        item = {"summary": "just a plain summary"}
        result = ct._memory_reference_from_payload(item, default_query="q")
        assert result is None


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
        # uri taken from file_path, text + confidence surfaced in preview
        assert result.uri == "/img.jpg"
        assert result.preview["text"] == "OCR text"
        assert result.preview["confidence"] == 0.95
        # default source/name applied
        assert result.source == "ocr"
        assert result.name == "ocr_result"
        assert result.metadata["parser_used"] == "ocr"

    def test_with_analysis_dict(self):
        item = {"text": "OCR", "analysis": {"key": "val"}, "file_path": "/p.png"}
        result = ct._artifact_from_ocr_payload(item)
        assert result is not None
        assert result.artifact_type == "ocr_text"
        # the analysis dict is preserved in the preview
        assert result.preview["analysis"] == {"key": "val"}
        # no structured_data -> no extracted fields
        assert result.fields == []

    def test_with_structured_data_extracts_fields(self):
        item = {
            "text": "Invoice data",
            "structured_data": {"amount": "100", "date": "2024-01-01"},
            "file_path": "/invoice.jpg",
        }
        result = ct._artifact_from_ocr_payload(item)
        assert result is not None
        assert result.artifact_type == "ocr_text"
        # each structured_data entry becomes a {name, value} field
        assert {"name": "amount", "value": "100"} in result.fields
        assert {"name": "date", "value": "2024-01-01"} in result.fields
        assert len(result.fields) == 2
        # structured_data echoed into preview
        assert result.preview["structured_data"]["amount"] == "100"


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
        # saved_name drives both name and uri fallbacks
        assert result.name == "test.db"
        assert result.uri == "test.db"
        assert result.metadata["parser_used"] == "sqlite_db"

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
        # each table becomes a field with its column list preserved
        by_name = {f["name"]: f["columns"] for f in result.fields}
        assert by_name["users"] == ["id", "name"]
        assert by_name["orders"] == ["id", "user_id"]


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
        assert (
            ct._artifact_type_from_document("file.bin", "application/vnd.ms-officedocument")
            == "office_document"
        )

    def test_artifact_type_fallback(self):
        assert (
            ct._artifact_type_from_document("file.bin", "application/octet-stream")
            == "document_file"
        )

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
        assert result.name == "report.pdf"
        # .pdf name => pdf_document type and pdf mime inferred
        assert result.artifact_type == "pdf_document"
        assert result.mime_type == "application/pdf"

    def test_with_document_nested(self):
        item = {"document": {"download_url": "http://x.com/f.docx", "file_name": "f.docx"}}
        result = ct._artifact_from_generated_document_payload(item)
        assert result is not None
        assert result.name == "f.docx"
        # nested document fields resolve uri + office_document classification
        assert result.uri == "http://x.com/f.docx"
        assert result.artifact_type == "office_document"
        assert "wordprocessingml" in result.mime_type

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
        # record_count derived from len(sample_rows)
        assert result.preview["record_count"] == 2
        assert result.name == "report.xlsx"
        # excel spreadsheet mime applied by default
        assert "spreadsheetml" in result.mime_type
        assert result.metadata["parser_used"] == "excel_analysis"

    def test_fields_filtered(self):
        item = {
            "preview_data": {"sheet_name": "S1"},
            "fields": [{"name": "col1"}, "not_a_dict", {"name": "col2"}],
        }
        result = ct._artifact_from_excel_analysis_payload(item)
        assert result is not None
        # the non-dict entry is dropped; only the two dict fields survive in order
        assert result.fields == [{"name": "col1"}, {"name": "col2"}]


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
        # run_id + agent_run_id stamped at both root and data level
        run_id = result["run_id"]
        assert run_id.startswith("run_")
        assert result["agent_run_id"] == run_id
        assert result["data"]["run_id"] == run_id
        assert result["data"]["agent_run_id"] == run_id
        # the attached id corresponds to a real persisted run
        persisted = repo.get(run_id)
        assert persisted is not None
        assert persisted.user_id == "u1"
        # original payload content preserved
        assert result["response"] == "done"


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
        waiting = [e for e in run.events if e.event_type == "step.waiting_user"]
        assert len(waiting) == 1
        # token_name is propagated into the waiting event payload
        assert waiting[0].data["token_name"] == "api_key"
        # run is persisted to the repository and resolves the explicit user
        assert repo.get(run.run_id) is not None
        assert run.user_id == "u1"

    def test_failed_status(self, repo):
        payload = {"success": False, "message": "error occurred", "error": "crashed"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            run = ct.create_chat_trace_run(payload, message="test", user_id="u1")
        assert run.status == "failed"
        # error message is derived from the payload "message" field
        assert run.error == "error occurred"
        assert any(e.event_type == "run.failed" for e in run.events)
        # success path event must not appear
        assert not any(e.event_type == "run.completed" for e in run.events)

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
            with patch(
                "app.infrastructure.billing.model_usage.record_model_usage",
                return_value={
                    "billing_status": "unmetered",
                    "billing_source": "est",
                    "cost_units": 0,
                    "usage_id": "u1",
                    "usage_key": "k1",
                },
            ):
                with patch(
                    "app.infrastructure.billing.model_usage.estimate_llm_cost_units", return_value=5
                ):
                    run = ct.create_chat_trace_run(payload, message="test", user_id="u2")
        assert run.status == "completed"
        # the _xcagi_trace was actually extracted into a recorded LLM call
        assert len(run.llm_calls) == 1
        captured = run.llm_calls[0]
        assert captured.model == "gpt-4"
        assert captured.provider == "openai"
        assert captured.total_tokens == 100
        assert captured.prompt_tokens == 70
        assert captured.completion_tokens == 30
        # token totals rolled up into run metadata + final_output
        assert run.metadata["llm_token_total"] == 100
        assert run.metadata["llm_call_count"] == 1
        assert run.final_output["llm_token_total"] == 100
        assert len(run.final_output["llm_calls"]) == 1

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
        # the chunk was extracted into a retrieval call keyed off the message
        assert len(run.retrieval_calls) == 1
        retrieval = run.retrieval_calls[0]
        assert retrieval.query == "search query"
        assert len(retrieval.chunks) == 1
        assert retrieval.chunks[0]["text"] == "chunk1"
        # retrieval metadata + final_output reflect the captured chunk
        assert run.metadata["retrieval_chunk_count"] == 1
        assert run.final_output["retrieval_chunk_count"] == 1
        assert any(e.event_type == "rag.retrieved" for e in run.events)


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

    def test_run_not_found_falls_back_to_attach_with_fresh_run(self, repo):
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run("nonexistent-run-id", payload, message="q")
        # falls through to attach_chat_trace_run, which mints a brand-new run id
        new_id = result["run_id"]
        assert new_id != "nonexistent-run-id"
        assert new_id.startswith("run_")
        assert result["agent_run_id"] == new_id
        # the requested id was never in the repo; the freshly-created one is
        assert repo.get("nonexistent-run-id") is None
        assert repo.get(new_id) is not None

    def test_with_existing_run(self, repo):
        run = _make_run()
        repo.save(run)
        payload = {"success": True, "response": "done"}
        with patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ):
            result = ct.finalize_legacy_chat_run(run.run_id, payload, message="q")
        # the existing run is reused (id unchanged) and marked completed
        assert result["run_id"] == run.run_id
        updated = repo.get(run.run_id)
        assert updated is not None
        assert updated.status == "completed"
        assert any(e.event_type == "run.completed" for e in updated.events)
        assert any(e.event_type == "planner.completed" for e in updated.events)

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
        assert any(e.event_type == "step.waiting_user" for e in updated.events)
        # run_id is echoed back onto the returned payload
        assert result["run_id"] == run.run_id

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
        # error message is taken from the payload when the run carries none
        assert updated.error == "failed hard"
        assert any(e.event_type == "run.failed" for e in updated.events)
        assert result["run_id"] == run.run_id


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
        # the existing final_output is left untouched
        assert run.final_output == {"existing": "val"}

    def test_appends_when_calls_present(self):
        run = _make_run()
        call = RetrievalCall(query="q", retriever="rag", source="ds", top_k=3)
        run.retrieval_calls.append(call)
        run.metadata["retrieval_chunk_count"] = 7
        run.metadata["citation_count"] = 2
        ct._append_retrieval_calls_to_final_output(run)
        # the call is serialized into final_output
        assert len(run.final_output["retrieval_calls"]) == 1
        assert run.final_output["retrieval_calls"][0]["query"] == "q"
        assert run.final_output["retrieval_calls"][0]["top_k"] == 3
        # aggregate counts copied from metadata
        assert run.final_output["retrieval_chunk_count"] == 7
        assert run.final_output["citation_count"] == 2


# ===========================================================================
# _append_memory_references_to_final_output
# ===========================================================================


class TestAppendMemoryReferencesToFinalOutput:
    def test_empty_does_nothing(self):
        run = _make_run()
        run.final_output = {"keep": 1}
        ct._append_memory_references_to_final_output(run)
        assert "memory_references" not in run.final_output
        assert run.final_output == {"keep": 1}

    def test_appends_when_refs_present(self):
        run = _make_run()
        ref = MemoryReference(
            query="q",
            memory_type="user_memory",
            source="mem_rag",
            hits=[{"chunk_id": "c1"}, {"chunk_id": "c2"}],
            summary="summ",
        )
        run.memory_references.append(ref)
        run.metadata["memory_hit_count"] = 2
        ct._append_memory_references_to_final_output(run)
        assert len(run.final_output["memory_references"]) == 1
        serialized = run.final_output["memory_references"][0]
        assert serialized["query"] == "q"
        assert serialized["summary"] == "summ"
        assert run.final_output["memory_hit_count"] == 2


# ===========================================================================
# _append_artifacts_to_final_output
# ===========================================================================


class TestAppendArtifactsToFinalOutput:
    def test_empty_does_nothing(self):
        run = _make_run()
        run.final_output = {"x": 1}
        ct._append_artifacts_to_final_output(run)
        assert "artifacts" not in run.final_output
        assert run.final_output == {"x": 1}

    def test_appends_when_artifacts_present(self):
        run = _make_run()
        art = AgentArtifact(artifact_type="ocr_text", name="img", source="ocr")
        run.artifacts.append(art)
        run.final_output = {}
        ct._append_artifacts_to_final_output(run)
        assert run.final_output["artifact_count"] == 1
        assert len(run.final_output["artifacts"]) == 1
        assert run.final_output["artifacts"][0]["artifact_type"] == "ocr_text"
        assert run.final_output["artifacts"][0]["name"] == "img"
        # no dataset ingests recorded -> key absent
        assert "dataset_ingests" not in run.final_output

    def test_includes_dataset_ingests_if_in_metadata(self):
        run = _make_run()
        art = AgentArtifact(artifact_type="ocr_text", name="img", source="ocr")
        run.artifacts.append(art)
        run.metadata["dataset_ingests"] = [{"ds": "one"}]
        run.metadata["dataset_ingest_count"] = 1
        run.final_output = {}
        ct._append_artifacts_to_final_output(run)
        # dataset ingest metadata is mirrored into final_output
        assert run.final_output["dataset_ingests"] == [{"ds": "one"}]
        assert run.final_output["dataset_ingest_count"] == 1
