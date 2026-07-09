"""
LLM call extraction and billing trace helpers.

Split from ``chat_trace.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app.application.agent_orchestrator._chat_trace_facade import module as _chat_trace_facade
from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
from app.application.agent_orchestrator.chat_trace_common import (
    _coerce_trace_float,
    _coerce_trace_int,
    _iter_payload_dicts,
    _trace_safe_value,
)
from app.application.agent_orchestrator.run_models import AgentRun, LLMCall
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
        _chat_trace_facade()._record_llm_usage_entry(run, call)
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

