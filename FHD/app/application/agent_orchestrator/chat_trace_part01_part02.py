# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def _record_llm_usage_entry(
    run: _facade().AgentRun, call: _facade().LLMCall
) -> dict[str, _facade().Any] | None:
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
    except _facade().RECOVERABLE_ERRORS as exc:
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
    raw_wallet_debit = entry.get("wallet_debit")
    wallet_debit: dict[str, _facade().Any] = (
        dict(raw_wallet_debit) if isinstance(raw_wallet_debit, dict) else {}
    )
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
            run.metadata["model_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
        if "balance_after_yuan" in wallet_debit:
            run.metadata["model_wallet_balance_yuan"] = (wallet_debit or {}).get(
                "balance_after_yuan"
            )
        run.add_event("billing.debited", "LLM 用量已从模型钱包扣减", event_payload)
    elif call.billing_status == "insufficient_balance":
        run.status = "failed"
        run.error = "AI wallet balance insufficient"
        run.metadata["model_wallet_balance_units"] = (wallet_debit or {}).get(
            "balance_after_units", 0
        )
        run.add_event("billing.insufficient_balance", run.error, event_payload)
    elif call.billing_status == "market_debit_failed":
        run.status = "failed"
        run.error = "AI market wallet debit failed"
        run.add_event("billing.debit_failed", run.error, event_payload)
    else:
        run.add_event("billing.recorded", "LLM 用量已写入模型账本", event_payload)
    return entry


def _append_llm_calls_to_run(run: _facade().AgentRun, calls: list[_facade().LLMCall]) -> None:
    existing = {_facade()._llm_call_signature(call) for call in run.llm_calls}
    for call in calls:
        signature = _facade()._llm_call_signature(call)
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
        _facade()._record_llm_usage_entry(run, call)
    if run.llm_calls:
        _facade()._refresh_llm_metadata(run)


def _append_llm_calls_to_final_output(run: _facade().AgentRun) -> None:
    if not run.llm_calls:
        return
    final_output = dict(run.final_output or {})
    _facade()._refresh_ai_cost_metadata(run)
    final_output["llm_calls"] = [call.to_dict() for call in run.llm_calls]
    final_output["llm_token_total"] = run.metadata.get("llm_token_total", 0)
    final_output["llm_cost_units_total"] = run.metadata.get("llm_cost_units_total", 0)
    final_output["ai_cost_units_total"] = run.metadata.get("ai_cost_units_total", 0)
    run.final_output = final_output


def _retrieval_signature(call: _facade().RetrievalCall) -> tuple[_facade().Any, ...]:
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


def _iter_retrieval_payloads(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
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
    item: dict[str, _facade().Any], *, default_query: str
) -> _facade().RetrievalCall | None:
    raw_chunks = item.get("chunks")
    raw_citations = item.get("citations")
    chunks = [
        dict(_facade()._trace_safe_value(chunk))
        for chunk in (raw_chunks if isinstance(raw_chunks, list) else [])
        if isinstance(chunk, dict)
    ]
    citations = [
        dict(_facade()._trace_safe_value(citation))
        for citation in (raw_citations if isinstance(raw_citations, list) else [])
        if isinstance(citation, dict)
    ]
    error = str(item.get("rag_error") or item.get("retrieval_error") or item.get("error") or "")
    if not chunks and (not citations) and (not error):
        return None
    status: str = "failed" if error else "completed"
    query = str(item.get("query") or item.get("user_message") or default_query or "")
    retriever = str(item.get("retriever") or item.get("retriever_id") or "rag")
    source = str(
        item.get("dataset_id")
        or item.get("source")
        or item.get("document_id")
        or item.get("knowledge_source")
        or ""
    )
    top_k = _facade()._coerce_trace_int(item.get("top_k")) or len(chunks)
    return _facade().RetrievalCall(
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
            "raw_trace": _facade()._trace_safe_value(
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


def _extract_retrieval_calls(
    payload: dict[str, _facade().Any], *, query: str = ""
) -> list[_facade().RetrievalCall]:
    calls: list[_facade().RetrievalCall] = []
    seen: set[tuple[_facade().Any, ...]] = set()
    for item in _facade()._iter_retrieval_payloads(payload):
        call = _facade()._retrieval_call_from_payload(item, default_query=query)
        if call is None:
            continue
        signature = _facade()._retrieval_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append(call)
    return calls


def _refresh_retrieval_metadata(run: _facade().AgentRun) -> None:
    run.metadata["retrieval_call_count"] = len(run.retrieval_calls)
    run.metadata["retrieval_chunk_count"] = sum(len(call.chunks) for call in run.retrieval_calls)
    run.metadata["citation_count"] = sum(len(call.citations) for call in run.retrieval_calls)
    if run.retrieval_calls:
        last_call = run.retrieval_calls[-1]
        run.metadata["retriever"] = last_call.retriever
        run.metadata["retrieval_source"] = last_call.source


def _append_retrieval_calls_to_run(
    run: _facade().AgentRun, calls: list[_facade().RetrievalCall]
) -> None:
    existing = {_facade()._retrieval_signature(call) for call in run.retrieval_calls}
    for call in calls:
        signature = _facade()._retrieval_signature(call)
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
        _facade()._refresh_retrieval_metadata(run)


def _append_retrieval_calls_to_final_output(run: _facade().AgentRun) -> None:
    if not run.retrieval_calls:
        return
    final_output = dict(run.final_output or {})
    final_output["retrieval_calls"] = [call.to_dict() for call in run.retrieval_calls]
    final_output["retrieval_chunk_count"] = run.metadata.get("retrieval_chunk_count", 0)
    final_output["citation_count"] = run.metadata.get("citation_count", 0)
    run.final_output = final_output


def _memory_reference_signature(reference: _facade().MemoryReference) -> tuple[_facade().Any, ...]:
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


def _has_user_memory_marker(item: dict[str, _facade().Any]) -> bool:
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
