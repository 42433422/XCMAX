from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
from app.application.agent_orchestrator.run_models import (
    AgentArtifact,
    AgentRun,
    AgentStep,
    LLMCall,
    MemoryReference,
    RetrievalCall,
    RunStatus,
    ToolCall,
    artifact_from_dict,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MAX_TRACE_STRING_CHARS = 4000
_MAX_TRACE_LIST_ITEMS = 20
_MAX_TRACE_DICT_ITEMS = 40
_LEGACY_EXECUTE_READ_DEFAULTS = {
    "business_db": ("read",),
    "customers": ("query",),
    "materials": ("query",),
    "products": ("query",),
    "shipment_records": ("query",),
}


def _trace_safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:_MAX_TRACE_STRING_CHARS]
    if isinstance(value, str):
        if len(value) <= _MAX_TRACE_STRING_CHARS:
            return value
        return value[:_MAX_TRACE_STRING_CHARS] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_trace_safe_value(item, depth=depth + 1) for item in value[:_MAX_TRACE_LIST_ITEMS]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= _MAX_TRACE_DICT_ITEMS:
                safe["_truncated"] = True
                break
            safe[str(key)] = _trace_safe_value(item, depth=depth + 1)
        return safe
    return str(value)[:_MAX_TRACE_STRING_CHARS]


def _resolved_user_id(
    *,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
) -> str:
    context = runtime_context or {}
    candidates = (
        user_id,
        context.get("user_id"),
        context.get("userId"),
        context.get("uid"),
        context.get("username"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return "anonymous"


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _payload_status(payload: dict[str, Any]) -> RunStatus:
    data = _payload_data(payload)
    if payload.get("requires_token") or data.get("requires_token"):
        return "waiting_user"
    if payload.get("success") is False:
        return "failed"
    return "completed"


def _payload_error_message(payload: dict[str, Any]) -> str:
    data = _payload_data(payload)
    return str(
        payload.get("message")
        or payload.get("error")
        or data.get("message")
        or data.get("error")
        or "Chat run failed"
    )


def _iter_payload_dicts(payload: dict[str, Any], *, max_depth: int = 3) -> Iterator[dict[str, Any]]:
    stack: list[tuple[dict[str, Any], int]] = [(payload, 0)]
    seen: set[int] = set()
    while stack:
        item, depth = stack.pop(0)
        item_id = id(item)
        if item_id in seen:
            continue
        seen.add(item_id)
        yield item
        if depth >= max_depth:
            continue
        for key in ("data", "payload", "result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                stack.append((nested, depth + 1))


def _iter_tool_call_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("toolCall", "tool_call", "tool_call_payload"):
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate

        auto_action = item.get("autoAction") or item.get("auto_action")
        if isinstance(auto_action, dict) and auto_action.get("type") == "tool_call":
            yield auto_action

        if item.get("action") == "tool_call" and (item.get("tool_key") or item.get("tool_id")):
            yield item


def _candidate_tool_actions(
    tool_id: str,
    raw_action: Any,
    params: dict[str, Any],
) -> list[str]:
    actions: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in actions:
            actions.append(text)

    add(raw_action)
    nested_action = params.get("action")
    if nested_action:
        add(nested_action)
        return actions

    raw = str(raw_action or "").strip().lower()
    if not raw or raw in {"执行", "execute", "exec", "run", "view"}:
        for fallback in _LEGACY_EXECUTE_READ_DEFAULTS.get(tool_id, ()):
            add(fallback)
    return actions


def _extract_low_risk_tool_call(
    payload: dict[str, Any],
) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    for tool_call in _iter_tool_call_payloads(payload):
        tool_id = str(
            tool_call.get("tool_id") or tool_call.get("tool_key") or tool_call.get("name") or ""
        ).strip()
        if not tool_id:
            continue
        params = tool_call.get("params")
        if not isinstance(params, dict):
            params = {}
        for action in _candidate_tool_actions(tool_id, tool_call.get("action"), params):
            validation = validate_tool_call(tool_id, action, params)
            spec = validation.spec
            if not validation.ok or spec is None:
                continue
            if spec.risk != "low" or not spec.idempotent:
                continue
            return spec.tool_id, spec.action, dict(params), dict(tool_call)
    return None


def _extract_legacy_tool_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("legacy_tool_records", "_tool_records", "tool_records"):
            records = item.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
    return []


def _coerce_trace_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_trace_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iter_llm_trace_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        for key in ("_xcagi_trace", "llm_trace", "llmTrace", "model_trace"):
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate

        usage = item.get("usage")
        if not isinstance(usage, dict):
            continue
        if item.get("model") or item.get("provider") or item.get("provider_id"):
            trace = {
                "provider_id": item.get("provider_id"),
                "provider": item.get("provider"),
                "model": item.get("model"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
            yield trace


def _llm_call_signature(call: LLMCall) -> tuple[Any, ...]:
    return (
        call.provider_id,
        call.provider,
        call.model,
        call.prompt_tokens,
        call.completion_tokens,
        call.total_tokens,
        call.cost_units,
        round(float(call.latency_ms or 0), 2),
        call.billing_status,
        call.status,
        call.error,
    )


def _llm_call_from_trace(trace: dict[str, Any]) -> LLMCall | None:
    from app.infrastructure.billing.model_usage import estimate_llm_cost_units

    provider_id = str(trace.get("provider_id") or trace.get("providerId") or "").strip()
    provider = str(
        trace.get("provider")
        or trace.get("provider_name")
        or trace.get("providerName")
        or provider_id
    ).strip()
    model = str(
        trace.get("model") or trace.get("model_name") or trace.get("modelName") or ""
    ).strip()
    prompt_tokens = _coerce_trace_int(trace.get("prompt_tokens") or trace.get("promptTokens"))
    completion_tokens = _coerce_trace_int(
        trace.get("completion_tokens") or trace.get("completionTokens")
    )
    total_tokens = _coerce_trace_int(trace.get("total_tokens") or trace.get("totalTokens"))
    latency_ms = _coerce_trace_float(trace.get("latency_ms") or trace.get("latencyMs"))
    cost_units = _coerce_trace_int(trace.get("cost_units") or trace.get("costUnits"))
    if not cost_units:
        cost_units = estimate_llm_cost_units(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    billing_status = str(trace.get("billing_status") or trace.get("billingStatus") or "").strip()
    billing_source = str(trace.get("billing_source") or trace.get("billingSource") or "").strip()
    status = str(trace.get("status") or "completed")
    if status not in {"completed", "failed"}:
        status = "completed"
    error = str(trace.get("error") or "")
    if not any(
        (provider_id, provider, model, prompt_tokens, completion_tokens, total_tokens, error)
    ):
        return None

    kwargs: dict[str, Any] = {}
    call_id = str(trace.get("call_id") or trace.get("callId") or "").strip()
    if call_id:
        kwargs["call_id"] = call_id
    return LLMCall(
        provider_id=provider_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        cost_units=cost_units,
        billing_status=billing_status or ("metered" if cost_units else "unmetered"),
        billing_source=billing_source or "estimated_token_units",
        status=status,
        error=error,
        metadata={"raw_trace": _trace_safe_value(trace)},
        **kwargs,
    )


def _extract_llm_calls(payload: dict[str, Any]) -> list[LLMCall]:
    calls: list[LLMCall] = []
    seen: set[tuple[Any, ...]] = set()
    for trace in _iter_llm_trace_payloads(payload):
        call = _llm_call_from_trace(trace)
        if call is None:
            continue
        signature = _llm_call_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append(call)
    return calls


def _refresh_llm_metadata(run: AgentRun) -> None:
    run.metadata["llm_call_count"] = len(run.llm_calls)
    run.metadata["llm_prompt_tokens_total"] = sum(
        int(call.prompt_tokens or 0) for call in run.llm_calls
    )
    run.metadata["llm_completion_tokens_total"] = sum(
        int(call.completion_tokens or 0) for call in run.llm_calls
    )
    run.metadata["llm_token_total"] = sum(int(call.total_tokens or 0) for call in run.llm_calls)
    run.metadata["llm_cost_units_total"] = sum(int(call.cost_units or 0) for call in run.llm_calls)
    _refresh_ai_cost_metadata(run)
    if run.llm_calls:
        last_call = run.llm_calls[-1]
        run.metadata["llm_provider"] = last_call.provider or last_call.provider_id
        run.metadata["llm_model"] = last_call.model


def _refresh_ai_cost_metadata(run: AgentRun) -> None:
    run.metadata["ai_cost_units_total"] = int(run.metadata.get("cost_units_total") or 0) + int(
        run.metadata.get("llm_cost_units_total") or 0
    )
    refresh_ai_budget_metadata(run)


def _record_llm_usage_entry(run: AgentRun, call: LLMCall) -> dict[str, Any] | None:
    if call.status != "completed":
        return None
    try:
        from app.infrastructure.billing.model_usage import record_model_usage

        entry = record_model_usage(
            run_id=run.run_id,
            user_id=run.user_id,
            provider_id=call.provider_id,
            provider=call.provider,
            model=call.model,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            total_tokens=call.total_tokens,
            cost_units=call.cost_units,
            billing_status=call.billing_status,
            billing_source=call.billing_source,
            source="agent_run.llm_trace",
            usage_key=f"{run.run_id}:{call.call_id}",
            metadata={
                "llm_call_id": call.call_id,
                "channel": run.metadata.get("channel"),
                "source": run.metadata.get("source"),
                "trace_mode": run.metadata.get("trace_mode"),
            },
        )
    except RECOVERABLE_ERRORS as exc:
        run.metadata["model_usage_ledger_status"] = "failed"
        run.add_event(
            "billing.record_failed",
            "LLM 用量账本写入失败",
            {
                "call_id": call.call_id,
                "provider": call.provider or call.provider_id,
                "model": call.model,
                "cost_units": call.cost_units,
                "error": str(exc),
            },
        )
        return None
    call.billing_status = str(entry.get("billing_status") or call.billing_status)
    call.billing_source = str(entry.get("billing_source") or call.billing_source)
    call.metadata["usage_ledger"] = {
        "usage_id": entry.get("usage_id"),
        "usage_key": entry.get("usage_key"),
        "status": "recorded",
    }
    wallet_debit = entry.get("wallet_debit") if isinstance(entry.get("wallet_debit"), dict) else {}
    if wallet_debit:
        call.metadata["wallet_debit"] = wallet_debit
    run.metadata["model_usage_ledger_status"] = "recorded"
    run.metadata["model_usage_entry_count"] = (
        int(run.metadata.get("model_usage_entry_count") or 0) + 1
    )
    run.metadata["model_usage_cost_units_total"] = int(
        run.metadata.get("model_usage_cost_units_total") or 0
    ) + int(entry.get("cost_units") or 0)
    event_payload = {
        "usage_id": entry.get("usage_id"),
        "call_id": call.call_id,
        "provider": call.provider or call.provider_id,
        "model": call.model,
        "total_tokens": call.total_tokens,
        "cost_units": entry.get("cost_units"),
        "billing_status": call.billing_status,
        "billing_source": call.billing_source,
        "wallet_debit": wallet_debit,
    }
    if call.billing_status == "debited":
        if "balance_after_units" in wallet_debit:
            run.metadata["model_wallet_balance_units"] = wallet_debit.get(
                "balance_after_units",
                0,
            )
        if "balance_after_yuan" in wallet_debit:
            run.metadata["model_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")
        run.add_event("billing.debited", "LLM 用量已从模型钱包扣减", event_payload)
    elif call.billing_status == "insufficient_balance":
        run.status = "failed"
        run.error = "AI wallet balance insufficient"
        run.metadata["model_wallet_balance_units"] = wallet_debit.get(
            "balance_after_units",
            0,
        )
        run.add_event("billing.insufficient_balance", run.error, event_payload)
    elif call.billing_status == "market_debit_failed":
        run.status = "failed"
        run.error = "AI market wallet debit failed"
        run.add_event("billing.debit_failed", run.error, event_payload)
    else:
        run.add_event("billing.recorded", "LLM 用量已写入模型账本", event_payload)
    return entry


def _append_llm_calls_to_run(run: AgentRun, calls: list[LLMCall]) -> None:
    existing = {_llm_call_signature(call) for call in run.llm_calls}
    for call in calls:
        signature = _llm_call_signature(call)
        if signature in existing:
            continue
        existing.add(signature)
        run.llm_calls.append(call)
        run.add_event(
            "llm.completed" if call.status == "completed" else "llm.failed",
            f"记录 LLM 调用 {call.provider or call.provider_id}/{call.model}".rstrip("/"),
            {
                "call_id": call.call_id,
                "provider_id": call.provider_id,
                "provider": call.provider,
                "model": call.model,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "total_tokens": call.total_tokens,
                "latency_ms": call.latency_ms,
                "cost_units": call.cost_units,
                "billing_status": call.billing_status,
                "billing_source": call.billing_source,
            },
        )
        _record_llm_usage_entry(run, call)
    if run.llm_calls:
        _refresh_llm_metadata(run)


def _append_llm_calls_to_final_output(run: AgentRun) -> None:
    if not run.llm_calls:
        return
    final_output = dict(run.final_output or {})
    _refresh_ai_cost_metadata(run)
    final_output["llm_calls"] = [call.to_dict() for call in run.llm_calls]
    final_output["llm_token_total"] = run.metadata.get("llm_token_total", 0)
    final_output["llm_cost_units_total"] = run.metadata.get("llm_cost_units_total", 0)
    final_output["ai_cost_units_total"] = run.metadata.get("ai_cost_units_total", 0)
    run.final_output = final_output


def _retrieval_signature(call: RetrievalCall) -> tuple[Any, ...]:
    first_chunk = call.chunks[0] if call.chunks else {}
    first_citation = call.citations[0] if call.citations else {}
    return (
        call.query,
        call.retriever,
        call.source,
        len(call.chunks),
        len(call.citations),
        str(
            first_chunk.get("chunk_index") or first_chunk.get("id") or first_chunk.get("text") or ""
        )[:120],
        str(
            first_citation.get("source")
            or first_citation.get("chunk_index")
            or first_citation.get("text")
            or ""
        )[:120],
        call.status,
        call.error,
    )


def _iter_retrieval_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        chunks = item.get("chunks")
        citations = item.get("citations")
        rag_enabled = item.get("rag_enabled")
        rag_error = item.get("rag_error") or item.get("retrieval_error")
        if (
            isinstance(chunks, list)
            or isinstance(citations, list)
            or rag_enabled is True
            or rag_error
        ):
            yield item


def _retrieval_call_from_payload(
    item: dict[str, Any], *, default_query: str
) -> RetrievalCall | None:
    raw_chunks = item.get("chunks")
    raw_citations = item.get("citations")
    chunks = [
        dict(_trace_safe_value(chunk))
        for chunk in (raw_chunks if isinstance(raw_chunks, list) else [])
        if isinstance(chunk, dict)
    ]
    citations = [
        dict(_trace_safe_value(citation))
        for citation in (raw_citations if isinstance(raw_citations, list) else [])
        if isinstance(citation, dict)
    ]
    error = str(item.get("rag_error") or item.get("retrieval_error") or item.get("error") or "")
    if not chunks and not citations and not error:
        return None

    status = "failed" if error else "completed"
    query = str(item.get("query") or item.get("user_message") or default_query or "")
    retriever = str(item.get("retriever") or item.get("retriever_id") or "rag")
    source = str(
        item.get("dataset_id")
        or item.get("source")
        or item.get("document_id")
        or item.get("knowledge_source")
        or ""
    )
    top_k = _coerce_trace_int(item.get("top_k")) or len(chunks)
    return RetrievalCall(
        query=query,
        retriever=retriever,
        source=source,
        top_k=top_k,
        chunks=chunks,
        citations=citations,
        status=status,
        error=error,
        metadata={
            "rag_enabled": bool(item.get("rag_enabled", True)),
            "raw_trace": _trace_safe_value(
                {
                    key: item.get(key)
                    for key in (
                        "query",
                        "user_message",
                        "dataset_id",
                        "source",
                        "document_id",
                        "top_k",
                        "rag_enabled",
                        "rag_error",
                    )
                    if key in item
                }
            ),
        },
    )


def _extract_retrieval_calls(payload: dict[str, Any], *, query: str = "") -> list[RetrievalCall]:
    calls: list[RetrievalCall] = []
    seen: set[tuple[Any, ...]] = set()
    for item in _iter_retrieval_payloads(payload):
        call = _retrieval_call_from_payload(item, default_query=query)
        if call is None:
            continue
        signature = _retrieval_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append(call)
    return calls


def _refresh_retrieval_metadata(run: AgentRun) -> None:
    run.metadata["retrieval_call_count"] = len(run.retrieval_calls)
    run.metadata["retrieval_chunk_count"] = sum(len(call.chunks) for call in run.retrieval_calls)
    run.metadata["citation_count"] = sum(len(call.citations) for call in run.retrieval_calls)
    if run.retrieval_calls:
        last_call = run.retrieval_calls[-1]
        run.metadata["retriever"] = last_call.retriever
        run.metadata["retrieval_source"] = last_call.source


def _append_retrieval_calls_to_run(run: AgentRun, calls: list[RetrievalCall]) -> None:
    existing = {_retrieval_signature(call) for call in run.retrieval_calls}
    for call in calls:
        signature = _retrieval_signature(call)
        if signature in existing:
            continue
        existing.add(signature)
        run.retrieval_calls.append(call)
        citation_sources = [
            str(citation.get("source") or citation.get("chunk_index") or "")
            for citation in call.citations[:5]
        ]
        run.add_event(
            "rag.retrieved" if call.status == "completed" else "rag.failed",
            f"记录 RAG 检索 {call.retriever}",
            {
                "call_id": call.call_id,
                "query": call.query,
                "retriever": call.retriever,
                "source": call.source,
                "top_k": call.top_k,
                "chunk_count": len(call.chunks),
                "citation_count": len(call.citations),
                "citation_sources": citation_sources,
                "error": call.error,
            },
        )
    if run.retrieval_calls:
        _refresh_retrieval_metadata(run)


def _append_retrieval_calls_to_final_output(run: AgentRun) -> None:
    if not run.retrieval_calls:
        return
    final_output = dict(run.final_output or {})
    final_output["retrieval_calls"] = [call.to_dict() for call in run.retrieval_calls]
    final_output["retrieval_chunk_count"] = run.metadata.get("retrieval_chunk_count", 0)
    final_output["citation_count"] = run.metadata.get("citation_count", 0)
    run.final_output = final_output


def _memory_reference_signature(reference: MemoryReference) -> tuple[Any, ...]:
    first_hit = reference.hits[0] if reference.hits else {}
    return (
        reference.query,
        reference.memory_type,
        reference.source,
        len(reference.hits),
        reference.summary[:240],
        str(
            first_hit.get("chunk_id")
            or first_hit.get("id")
            or first_hit.get("content")
            or first_hit.get("text")
            or ""
        )[:120],
        reference.status,
        reference.error,
    )


def _has_user_memory_marker(item: dict[str, Any]) -> bool:
    marker_keys = {
        "user_memory_rag",
        "userMemoryRag",
        "user_memory_rag_summary",
        "userMemoryRagSummary",
        "user_memory_summary",
        "userMemorySummary",
        "user_memory_hits",
        "userMemoryHits",
        "user_memory_error",
        "userMemoryError",
    }
    if any(key in item for key in marker_keys):
        return True
    for key in ("summary", "memory_summary", "prompt_memory", "context"):
        value = item.get(key)
        if isinstance(value, str) and "UserMemoryRAG" in value:
            return True
    return False


def _iter_memory_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    nested_keys = (
        "user_memory_rag",
        "userMemoryRag",
        "memory_reference",
        "memoryReference",
    )
    for item in _iter_payload_dicts(payload):
        if _has_user_memory_marker(item):
            yield item
        for key in nested_keys:
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate


def _first_list_value(item: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return value
    return []


def _memory_reference_from_payload(
    item: dict[str, Any],
    *,
    default_query: str,
) -> MemoryReference | None:
    has_marker = _has_user_memory_marker(item)
    raw_hits = _first_list_value(
        item,
        (
            "user_memory_hits",
            "userMemoryHits",
            "memory_hits",
            "memoryHits",
            "hits",
        ),
    )
    hits = [
        dict(_trace_safe_value(hit))
        for hit in raw_hits
        if isinstance(hit, dict) and isinstance(_trace_safe_value(hit), dict)
    ]
    summary = str(
        item.get("user_memory_rag_summary")
        or item.get("userMemoryRagSummary")
        or item.get("user_memory_summary")
        or item.get("userMemorySummary")
        or item.get("memory_summary")
        or item.get("summary")
        or item.get("prompt_memory")
        or ""
    )
    error = str(
        item.get("user_memory_error")
        or item.get("userMemoryError")
        or item.get("memory_error")
        or item.get("memoryError")
        or ""
    )
    if not has_marker and not hits and "UserMemoryRAG" not in summary:
        return None
    if not hits and not summary and not error:
        return None

    query = str(
        item.get("query") or item.get("user_message") or item.get("message") or default_query or ""
    )
    memory_type = str(item.get("memory_type") or item.get("memoryType") or "user_memory")
    source = str(
        item.get("source")
        or item.get("memory_source")
        or item.get("memorySource")
        or item.get("index_id")
        or item.get("collection")
        or "user_memory_rag"
    )
    status = "failed" if error else "completed"
    return MemoryReference(
        query=query,
        memory_type=memory_type,
        source=source,
        hits=hits,
        summary=summary,
        status=status,
        error=error,
        metadata={
            "top_k": _coerce_trace_int(item.get("top_k") or item.get("topK")),
            "hit_count": len(hits),
            "raw_trace": _trace_safe_value(
                {
                    key: item.get(key)
                    for key in (
                        "query",
                        "user_message",
                        "source",
                        "memory_source",
                        "index_id",
                        "collection",
                        "top_k",
                        "user_memory_error",
                        "memory_error",
                    )
                    if key in item
                }
            ),
        },
    )


def _extract_memory_references(
    payload: dict[str, Any],
    *,
    query: str = "",
) -> list[MemoryReference]:
    references: list[MemoryReference] = []
    seen: set[tuple[Any, ...]] = set()
    for item in _iter_memory_payloads(payload):
        reference = _memory_reference_from_payload(item, default_query=query)
        if reference is None:
            continue
        signature = _memory_reference_signature(reference)
        if signature in seen:
            continue
        seen.add(signature)
        references.append(reference)
    return references


def _refresh_memory_metadata(run: AgentRun) -> None:
    run.metadata["memory_reference_count"] = len(run.memory_references)
    run.metadata["memory_hit_count"] = sum(
        len(reference.hits) for reference in run.memory_references
    )
    run.metadata["memory_sources"] = sorted(
        {reference.source for reference in run.memory_references if reference.source}
    )


def _append_memory_references_to_run(
    run: AgentRun,
    references: list[MemoryReference],
) -> None:
    existing = {_memory_reference_signature(reference) for reference in run.memory_references}
    for reference in references:
        signature = _memory_reference_signature(reference)
        if signature in existing:
            continue
        existing.add(signature)
        run.memory_references.append(reference)
        first_sources = [
            str(hit.get("source") or hit.get("chunk_id") or hit.get("id") or "")
            for hit in reference.hits[:5]
        ]
        run.add_event(
            "memory.recalled" if reference.status == "completed" else "memory.failed",
            f"记录用户记忆召回 {reference.memory_type}",
            {
                "reference_id": reference.reference_id,
                "query": reference.query,
                "memory_type": reference.memory_type,
                "source": reference.source,
                "hit_count": len(reference.hits),
                "summary_preview": reference.summary[:500],
                "hit_sources": first_sources,
                "error": reference.error,
            },
        )
    if run.memory_references:
        _refresh_memory_metadata(run)


def _append_memory_references_to_final_output(run: AgentRun) -> None:
    if not run.memory_references:
        return
    final_output = dict(run.final_output or {})
    final_output["memory_references"] = [reference.to_dict() for reference in run.memory_references]
    final_output["memory_hit_count"] = run.metadata.get("memory_hit_count", 0)
    run.final_output = final_output


def _artifact_signature(artifact: AgentArtifact) -> tuple[str, str, str, str, str]:
    return (
        artifact.artifact_type,
        artifact.name,
        artifact.uri,
        artifact.source,
        artifact.summary[:240],
    )


def _iter_explicit_artifact_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
        artifacts = item.get("artifacts")
        if isinstance(artifacts, dict):
            yield artifacts
        elif isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    yield artifact

        artifact = item.get("artifact")
        if isinstance(artifact, dict):
            yield artifact


def _artifact_from_ocr_payload(item: dict[str, Any]) -> AgentArtifact | None:
    text = str(item.get("text") or item.get("ocr_text") or "").strip()
    file_path = str(
        item.get("file_path") or item.get("image_path") or item.get("uri") or ""
    ).strip()
    has_ocr_shape = bool(text) and (
        "confidence" in item
        or "ocr_confidence" in item
        or "analysis" in item
        or "structured_data" in item
        or (isinstance(item.get("data"), dict) and "raw_text" in item.get("data", {}))
        or bool(file_path)
    )
    if not has_ocr_shape:
        return None

    structured = item.get("structured_data")
    if not isinstance(structured, dict):
        data = item.get("data")
        structured = data if isinstance(data, dict) else {}
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    confidence = item.get("confidence", item.get("ocr_confidence", 0))
    preview = {
        "text": text[:1000],
        "confidence": _coerce_trace_float(confidence),
        "structured_data": _trace_safe_value(structured),
        "analysis": _trace_safe_value(analysis),
    }
    fields = [
        {"name": key, "value": _trace_safe_value(value)}
        for key, value in structured.items()
        if value not in (None, "", [], {})
    ][:20]
    summary = str(item.get("message") or item.get("summary") or "OCR 解析结果").strip()
    return AgentArtifact(
        artifact_type="ocr_text",
        name=str(item.get("name") or item.get("filename") or "ocr_result"),
        source=str(item.get("source") or "ocr"),
        uri=file_path,
        mime_type=str(item.get("mime_type") or "image/*"),
        summary=summary,
        fields=fields,
        preview=preview,
        metadata={"parser_used": "ocr", "success": item.get("success")},
    )


def _artifact_from_file_analysis_payload(item: dict[str, Any]) -> AgentArtifact | None:
    if not any(key in item for key in ("parser_used", "suggested_use", "db_meta", "extension")):
        return None
    parser_used = str(item.get("parser_used") or "").strip()
    extension = str(item.get("extension") or "").strip().lower()
    suggested_use = str(item.get("suggested_use") or "").strip()
    saved_name = str(
        item.get("saved_name") or item.get("name") or item.get("filename") or ""
    ).strip()
    if not any((parser_used, extension, suggested_use, saved_name)):
        return None

    if parser_used == "sqlite_db" or extension == ".db" or suggested_use.endswith("_db"):
        artifact_type = "database_file"
    elif extension in {".xlsx", ".xls", ".xlsm"} or "excel" in parser_used:
        artifact_type = "excel_file"
    elif extension == ".pdf" or "pdf" in parser_used:
        artifact_type = "pdf_document"
    elif extension in {".doc", ".docx", ".ppt", ".pptx"} or "office" in parser_used:
        artifact_type = "office_document"
    else:
        artifact_type = "file_analysis"

    db_meta = item.get("db_meta") if isinstance(item.get("db_meta"), dict) else {}
    table_columns = (
        db_meta.get("table_columns") if isinstance(db_meta.get("table_columns"), dict) else {}
    )
    fields = [
        {"name": str(table), "columns": list(columns or [])[:40]}
        for table, columns in table_columns.items()
    ][:20]
    preview = {
        "parser_used": parser_used,
        "extension": extension,
        "suggested_use": suggested_use,
        "text_preview": str(item.get("text_preview") or "")[:1000],
        "db_meta": _trace_safe_value(db_meta),
        "unit_candidates": _trace_safe_value(item.get("unit_candidates") or []),
    }
    return AgentArtifact(
        artifact_type=artifact_type,
        name=saved_name or str(item.get("raw_filename") or item.get("filename") or "file_analysis"),
        source=str(item.get("source") or "file_analysis"),
        uri=str(item.get("file_path") or item.get("uri") or saved_name),
        mime_type=str(item.get("mime_type") or ""),
        summary=str(item.get("ai_summary") or item.get("message") or suggested_use or parser_used),
        fields=fields,
        preview=preview,
        metadata={
            "parser_used": parser_used,
            "extension": extension,
            "suggested_use": suggested_use,
            "success": item.get("success"),
        },
    )


def _mime_from_document_name(name: str, default: str = "") -> str:
    lowered = name.lower().strip()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lowered.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return default


def _artifact_type_from_document(name: str, mime_type: str) -> str:
    lowered_name = name.lower().strip()
    lowered_mime = mime_type.lower().strip()
    if lowered_name.endswith(".pdf") or lowered_mime == "application/pdf":
        return "pdf_document"
    if lowered_name.endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "office_document"
    if "officedocument" in lowered_mime:
        return "office_document"
    return "document_file"


def _artifact_from_generated_document_payload(item: dict[str, Any]) -> AgentArtifact | None:
    document = item.get("document")
    candidate = document if isinstance(document, dict) else item
    has_document_marker = isinstance(document, dict) or any(
        key in candidate
        for key in (
            "download_url",
            "pickup_token",
            "document_url",
            "doc_url",
        )
    )
    if not has_document_marker:
        return None

    name = str(
        candidate.get("file_name")
        or candidate.get("doc_name")
        or candidate.get("filename")
        or candidate.get("name")
        or ""
    ).strip()
    uri = str(
        candidate.get("download_url")
        or candidate.get("document_url")
        or candidate.get("doc_url")
        or candidate.get("file_path")
        or candidate.get("uri")
        or ""
    ).strip()
    pickup_token = str(candidate.get("pickup_token") or candidate.get("token") or "").strip()
    if not any((name, uri, pickup_token)):
        return None

    mime_type = str(candidate.get("mime_type") or candidate.get("mime") or "").strip()
    mime_type = mime_type or _mime_from_document_name(name)
    artifact_type = _artifact_type_from_document(name, mime_type)
    source = str(candidate.get("source") or item.get("source") or "generated_document")
    summary = str(
        candidate.get("summary") or candidate.get("message") or item.get("message") or "生成文档"
    ).strip()
    return AgentArtifact(
        artifact_type=artifact_type,
        name=name or uri or "generated_document",
        source=source,
        uri=uri,
        mime_type=mime_type,
        summary=summary,
        preview={
            "file_name": name,
            "download_url": uri,
            "pickup_token": pickup_token,
        },
        metadata={
            "pickup_token": pickup_token,
            "success": candidate.get("success", item.get("success")),
            "generator": source,
        },
    )


def _artifact_from_excel_analysis_payload(item: dict[str, Any]) -> AgentArtifact | None:
    preview_data = item.get("preview_data")
    if not isinstance(preview_data, dict):
        return None
    if not any(
        key in preview_data
        for key in ("sample_rows", "grid_preview", "file_path", "sheet_name", "selected_sheet_name")
    ):
        return None

    fields = item.get("fields")
    if not isinstance(fields, list):
        fields = []
    record_count = _coerce_trace_int(
        item.get("record_count")
        or preview_data.get("record_count")
        or len(preview_data.get("sample_rows") or [])
    )
    file_path = str(item.get("file_path") or preview_data.get("file_path") or "").strip()
    return AgentArtifact(
        artifact_type="excel_records",
        name=str(item.get("name") or preview_data.get("filename") or file_path or "excel_analysis"),
        source=str(item.get("source") or "excel_analysis"),
        uri=file_path,
        mime_type=str(
            item.get("mime_type")
            or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        summary=str(item.get("summary") or "Excel 解析结果"),
        fields=[field for field in fields if isinstance(field, dict)][:40],
        preview={
            "record_count": record_count,
            "preview_data": _trace_safe_value(preview_data),
        },
        metadata={"parser_used": "excel_analysis", "success": item.get("success")},
    )


def _iter_inferred_artifacts(payload: dict[str, Any]) -> Iterator[AgentArtifact]:
    for item in _iter_payload_dicts(payload):
        for key in ("ocr_result", "ocr", "recognized_text"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_ocr_payload(nested)
                if artifact is not None:
                    yield artifact

        for key in ("file_analysis", "analysis_result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_file_analysis_payload(nested)
                if artifact is not None:
                    yield artifact

        for key in ("document", "generated_document", "office_document"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_generated_document_payload({"document": nested})
                if artifact is not None:
                    yield artifact

        excel_analysis = item.get("excel_analysis")
        if isinstance(excel_analysis, dict):
            artifact = _artifact_from_excel_analysis_payload(excel_analysis)
            if artifact is not None:
                yield artifact

        for factory in (
            _artifact_from_ocr_payload,
            _artifact_from_file_analysis_payload,
            _artifact_from_generated_document_payload,
            _artifact_from_excel_analysis_payload,
        ):
            artifact = factory(item)
            if artifact is not None:
                yield artifact


def _extract_artifacts(payload: dict[str, Any]) -> list[AgentArtifact]:
    artifacts: list[AgentArtifact] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for explicit in _iter_explicit_artifact_payloads(payload):
        artifact = artifact_from_dict(explicit)
        if not artifact.artifact_type:
            continue
        signature = _artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)

    for artifact in _iter_inferred_artifacts(payload):
        if not artifact.artifact_type:
            continue
        signature = _artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    return artifacts


def _refresh_artifact_metadata(run: AgentRun) -> None:
    run.metadata["artifact_count"] = len(run.artifacts)
    run.metadata["artifact_types"] = sorted({artifact.artifact_type for artifact in run.artifacts})


def _append_artifacts_to_run(run: AgentRun, artifacts: list[AgentArtifact]) -> None:
    existing = {_artifact_signature(artifact) for artifact in run.artifacts}
    for artifact in artifacts:
        signature = _artifact_signature(artifact)
        if signature in existing:
            continue
        existing.add(signature)
        run.artifacts.append(artifact)
        run.add_event(
            "artifact.attached",
            f"Artifact 已附加: {artifact.artifact_type}",
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "name": artifact.name,
                "source": artifact.source,
                "uri": artifact.uri,
            },
        )
        ingest_artifact_to_dataset(run, artifact)
    if run.artifacts:
        _refresh_artifact_metadata(run)


def _append_artifacts_to_final_output(run: AgentRun) -> None:
    if not run.artifacts:
        return
    final_output = dict(run.final_output or {})
    final_output["artifacts"] = [artifact.to_dict() for artifact in run.artifacts]
    final_output["artifact_count"] = len(run.artifacts)
    if run.metadata.get("dataset_ingests"):
        final_output["dataset_ingests"] = run.metadata["dataset_ingests"]
        final_output["dataset_ingest_count"] = run.metadata.get("dataset_ingest_count", 0)
    run.final_output = final_output


def _normalized_record_payload(
    record: dict[str, Any],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    tool_id = str(
        record.get("tool_id") or record.get("tool_name") or record.get("tool_key") or ""
    ).strip()
    action = str(record.get("action") or "").strip() or "execute"
    params = record.get("params")
    output = record.get("output")
    return (
        tool_id,
        action,
        dict(params) if isinstance(params, dict) else {},
        dict(output)
        if isinstance(output, dict)
        else {"success": False, "message": str(output or "")},
    )


def _append_legacy_tool_records_to_run(
    run: AgentRun,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    node_outputs: dict[str, Any] = {}
    total_cost = 0
    for idx, record in enumerate(records, start=1):
        tool_id, action, params, output = _normalized_record_payload(record)
        if not tool_id:
            continue
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        spec = get_tool_action_spec(tool_id, action)
        node_id = f"legacy_{idx}_{tool_id}_{action}".replace(".", "_")
        step = AgentStep(
            node_id=node_id,
            tool_id=tool_id,
            action=getattr(spec, "action", action) if spec is not None else action,
            params=params,
            risk=getattr(spec, "risk", "medium") if spec is not None else "medium",
            idempotent=bool(getattr(spec, "idempotent", False)) if spec is not None else False,
            description="legacy planner 已执行工具调用",
            status="completed" if output.get("success") is not False else "failed",
            output=output,
            finished_at=utc_now_iso(),
        )
        call = ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=params,
            status="completed" if step.status == "completed" else "failed",
            output=output,
            error=""
            if step.status == "completed"
            else str(output.get("message") or output.get("error") or ""),
            cost_units=int(getattr(spec, "cost_units", 0) or 0),
            permission=str(getattr(spec, "permission", "") or ""),
            finished_at=step.finished_at,
            metadata={
                "observed": True,
                "legacy_tool_call_id": str(record.get("tool_call_id") or ""),
                "risk": step.risk,
                "idempotent": step.idempotent,
            },
        )
        run.steps.append(step)
        run.tool_calls.append(call)
        node_outputs[step.node_id] = output
        total_cost += call.cost_units
        run.add_event(
            "tool.started",
            f"观察到 legacy 工具 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": call.call_id,
                "cost_units": call.cost_units,
                "permission": call.permission,
                "observed": True,
            },
        )
        event_type = "tool.completed" if step.status == "completed" else "tool.failed"
        run.add_event(
            event_type,
            f"记录 legacy 工具 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": call.call_id,
                "cost_units": call.cost_units,
                "observed": True,
            },
        )
        _append_artifacts_to_run(run, _extract_artifacts(output))
    return node_outputs, total_cost


def _create_legacy_tool_records_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
    intent: str = "legacy_tool_chain",
) -> AgentRun | None:
    records = _extract_legacy_tool_records(payload)
    if not records:
        return None

    resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    status = _payload_status(payload)
    run = AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status=status,
        intent=str(intent or "legacy_tool_chain").strip() or "legacy_tool_chain",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "legacy_tool_records",
            "runtime_context": _trace_safe_value(runtime_context or {}),
        },
        final_output={"chat_payload": _trace_safe_value(payload)},
    )
    run.add_event(
        "run.created",
        "Legacy planner 工具调用已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip(), "observed": True},
    )

    node_outputs, total_cost = _append_legacy_tool_records_to_run(run, records)
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))

    if run.steps and status == "completed" and any(step.status == "failed" for step in run.steps):
        run.status = "failed"
        run.error = "legacy planner tool failed"
    run.metadata["tool_call_count"] = len(run.tool_calls)
    run.metadata["cost_units_total"] = total_cost
    run.final_output = {
        "chat_payload": _trace_safe_value(payload),
        "node_outputs": node_outputs,
        "tool_calls": [call.to_dict() for call in run.tool_calls],
        "cost_units_total": total_cost,
    }
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    if run.status == "failed":
        run.add_event("run.failed", run.error or "Legacy planner 工具调用失败", run.final_output)
    elif run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    else:
        run.add_event("run.completed", "Legacy planner 工具调用追踪完成", run.final_output)
    return repository.save(run)


def _create_tool_call_agent_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
) -> AgentRun | None:
    extracted = _extract_low_risk_tool_call(payload)
    if extracted is None:
        return None

    tool_id, action, params, raw_tool_call = extracted
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

    resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    runtime = dict(runtime_context or {})
    runtime.update(
        {
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "orchestrated_tool_call",
            "legacy_tool_call": _trace_safe_value(raw_tool_call),
        }
    )
    plan = PlanGraph(
        plan_id=f"compat-tool-{uuid4().hex[:12]}",
        intent=f"{tool_id}_{action}",
        todo_steps=[f"执行兼容工具 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=f"{tool_id}_{action}",
                tool_id=tool_id,
                action=action,
                params=params,
                risk="low",
                idempotent=True,
                description=f"兼容 toolCall 接管: {tool_id}.{action}",
            )
        ],
        risk_level="low",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "orchestrated_tool_call",
            "legacy_tool_call": _trace_safe_value(raw_tool_call),
        },
    )
    run = AgentOrchestrator(repository=repository).start_run_from_plan(
        user_id=resolved_user_id,
        message=str(message or ""),
        plan=plan,
        runtime_context=runtime,
        auto_execute=True,
    )
    run.metadata["channel"] = channel
    run.metadata["source"] = str(source or "").strip()
    run.metadata["trace_mode"] = "orchestrated_tool_call"
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    return repository.save(run)


def _attach_run_id(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    payload["run_id"] = run_id
    payload["agent_run_id"] = run_id
    data = payload.get("data")
    if isinstance(data, dict):
        data["run_id"] = run_id
        data["agent_run_id"] = run_id
    else:
        payload["data"] = {"run_id": run_id, "agent_run_id": run_id}
    return payload


def start_legacy_chat_run(
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> AgentRun:
    resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    run = AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status="running",
        intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "legacy_planner_run",
            "runtime_context": _trace_safe_value(runtime_context or {}),
        },
    )
    run.add_event(
        "run.created",
        "Legacy planner run 已创建",
        {"channel": channel, "source": str(source or "").strip()},
    )
    run.add_event(
        "planner.started",
        "Legacy planner 开始执行",
        {"channel": channel, "source": str(source or "").strip()},
    )
    return get_agent_run_repository().save(run)


def finalize_legacy_chat_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    repository = get_agent_run_repository()
    run = repository.get(run_id)
    if run is None:
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )

    status = _payload_status(payload)
    records = _extract_legacy_tool_records(payload)
    run.status = status
    run.error = ""
    run.metadata["channel"] = channel
    run.metadata["source"] = str(source or "").strip()
    run.metadata["trace_mode"] = "legacy_planner_run"
    run.metadata["runtime_context"] = _trace_safe_value(runtime_context or {})
    run.add_event(
        "planner.completed",
        "Legacy planner 执行完成",
        {"status": status, "observed_tool_records": len(records)},
    )

    node_outputs: dict[str, Any] = {}
    total_cost = 0
    if records:
        run.metadata["trace_mode"] = "legacy_planner_run_with_tools"
        node_outputs, total_cost = _append_legacy_tool_records_to_run(run, records)
        if status == "completed" and any(step.status == "failed" for step in run.steps):
            run.status = "failed"
            run.error = "legacy planner tool failed"

    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    run.metadata["tool_call_count"] = len(run.tool_calls)
    run.metadata["cost_units_total"] = total_cost
    run.final_output = {
        "chat_payload": _trace_safe_value(payload),
        "node_outputs": node_outputs,
        "tool_calls": [call.to_dict() for call in run.tool_calls],
        "cost_units_total": total_cost,
    }
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)

    if run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    elif run.status == "failed":
        run.error = run.error or _payload_error_message(payload)
        run.add_event("run.failed", run.error, run.final_output)
    else:
        run.add_event("run.completed", "Legacy planner run 执行完成", run.final_output)
    repository.save(run)
    return _attach_run_id(payload, run.run_id)


def create_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> AgentRun:
    repository = get_agent_run_repository()
    observed = _create_legacy_tool_records_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        repository=repository,
        intent=(
            str(intent or "").strip()
            if str(intent or "").strip() and str(intent or "").strip() != "legacy_chat_adapter"
            else "legacy_tool_chain"
        ),
    )
    if observed is not None:
        return observed

    orchestrated = _create_tool_call_agent_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        repository=repository,
    )
    if orchestrated is not None:
        return orchestrated

    status = _payload_status(payload)
    resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    text = str(payload.get("response") or _payload_data(payload).get("text") or "")

    run = AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status=status,
        intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "post_execution",
            "runtime_context": _trace_safe_value(runtime_context or {}),
        },
        final_output={"chat_payload": _trace_safe_value(payload)},
    )
    run.add_event(
        "run.created",
        "Chat 请求已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip()},
    )
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    if status == "waiting_user":
        run.add_event(
            "step.waiting_user",
            str(payload.get("message") or "等待用户授权"),
            {
                "token_name": payload.get("token_name") or _payload_data(payload).get("token_name"),
                "token_description": payload.get("token_description")
                or _payload_data(payload).get("token_description"),
            },
        )
    elif status == "failed":
        run.error = _payload_error_message(payload)
        run.add_event("run.failed", run.error, {"response_preview": text[:500]})
    else:
        run.add_event("run.completed", "Chat 响应已完成", {"response_preview": text[:500]})

    return repository.save(run)


def attach_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("run_id") or data.get("agent_run_id")):
        return payload
    if payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    except Exception:  # noqa: BLE001 - tracing must not break the chat response
        logger.exception("failed to attach AgentRun trace to chat response")
        return payload

    return _attach_run_id(payload, run.run_id)
