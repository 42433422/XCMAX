# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def _trace_safe_value(value: _facade().Any, *, depth: int = 0) -> _facade().Any:
    if depth >= 4:
        return str(value)[: _facade()._MAX_TRACE_STRING_CHARS]
    if isinstance(value, str):
        if len(value) <= _facade()._MAX_TRACE_STRING_CHARS:
            return value
        return value[: _facade()._MAX_TRACE_STRING_CHARS] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [
            _trace_safe_value(item, depth=depth + 1)
            for item in value[: _facade()._MAX_TRACE_LIST_ITEMS]
        ]
    if isinstance(value, dict):
        safe: dict[str, _facade().Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= _facade()._MAX_TRACE_DICT_ITEMS:
                safe["_truncated"] = True
                break
            safe[str(key)] = _trace_safe_value(item, depth=depth + 1)
        return safe
    return str(value)[: _facade()._MAX_TRACE_STRING_CHARS]


def _resolved_user_id(
    *, runtime_context: dict[str, _facade().Any] | None, user_id: str | None
) -> str:
    context = runtime_context or {}
    candidates = (
        context.get("local_user_id"),
        context.get("actor_id"),
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


def _payload_data(payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _payload_status(payload: dict[str, _facade().Any]) -> _facade().RunStatus:
    data = _facade()._payload_data(payload)
    if payload.get("requires_token") or data.get("requires_token"):
        return "waiting_user"
    if payload.get("success") is False:
        return "failed"
    return "completed"


def _payload_error_message(payload: dict[str, _facade().Any]) -> str:
    data = _facade()._payload_data(payload)
    return str(
        payload.get("message")
        or payload.get("error")
        or data.get("message")
        or data.get("error")
        or "Chat run failed"
    )


def _iter_payload_dicts(
    payload: dict[str, _facade().Any], *, max_depth: int = 3
) -> _facade().Iterator[dict[str, _facade().Any]]:
    stack: list[tuple[dict[str, _facade().Any], int]] = [(payload, 0)]
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


def _iter_tool_call_payloads(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
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
    tool_id: str, raw_action: _facade().Any, params: dict[str, _facade().Any]
) -> list[str]:
    actions: list[str] = []

    def add(value: _facade().Any) -> None:
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
        for fallback in _facade()._LEGACY_EXECUTE_READ_DEFAULTS.get(tool_id, ()):
            add(fallback)
    return actions


def _extract_low_risk_tool_call(
    payload: dict[str, _facade().Any],
) -> tuple[str, str, dict[str, _facade().Any], dict[str, _facade().Any]] | None:
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    for tool_call in _facade()._iter_tool_call_payloads(payload):
        tool_id = str(
            tool_call.get("tool_id") or tool_call.get("tool_key") or tool_call.get("name") or ""
        ).strip()
        if not tool_id:
            continue
        params = tool_call.get("params")
        if not isinstance(params, dict):
            params = {}
        for action in _facade()._candidate_tool_actions(tool_id, tool_call.get("action"), params):
            validation = validate_tool_call(tool_id, action, params)
            spec = validation.spec
            if not validation.ok or spec is None:
                continue
            if spec.risk != "low" or not spec.idempotent:
                continue
            return (spec.tool_id, spec.action, dict(params), dict(tool_call))
    return None


def _extract_legacy_tool_records(
    payload: dict[str, _facade().Any],
) -> list[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
        for key in ("legacy_tool_records", "_tool_records", "tool_records"):
            records = item.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
    return []


def _coerce_trace_int(value: _facade().Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_trace_float(value: _facade().Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iter_llm_trace_payloads(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
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


def _llm_call_signature(call: _facade().LLMCall) -> tuple[_facade().Any, ...]:
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


def _llm_call_from_trace(trace: dict[str, _facade().Any]) -> _facade().LLMCall | None:
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
    prompt_tokens = _facade()._coerce_trace_int(
        trace.get("prompt_tokens") or trace.get("promptTokens")
    )
    completion_tokens = _facade()._coerce_trace_int(
        trace.get("completion_tokens") or trace.get("completionTokens")
    )
    total_tokens = _facade()._coerce_trace_int(
        trace.get("total_tokens") or trace.get("totalTokens")
    )
    latency_ms = _facade()._coerce_trace_float(trace.get("latency_ms") or trace.get("latencyMs"))
    cost_units = _facade()._coerce_trace_int(trace.get("cost_units") or trace.get("costUnits"))
    if not cost_units:
        cost_units = estimate_llm_cost_units(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    billing_status = str(trace.get("billing_status") or trace.get("billingStatus") or "").strip()
    billing_source = str(trace.get("billing_source") or trace.get("billingSource") or "").strip()
    status: str = "failed" if str(trace.get("status") or "completed") == "failed" else "completed"
    error = str(trace.get("error") or "")
    if not any(
        (provider_id, provider, model, prompt_tokens, completion_tokens, total_tokens, error)
    ):
        return None
    kwargs: dict[str, _facade().Any] = {}
    call_id = str(trace.get("call_id") or trace.get("callId") or "").strip()
    if call_id:
        kwargs["call_id"] = call_id
    return _facade().LLMCall(
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
        metadata={"raw_trace": _facade()._trace_safe_value(trace)},
        **kwargs,
    )


def _extract_llm_calls(payload: dict[str, _facade().Any]) -> list[_facade().LLMCall]:
    calls: list[_facade().LLMCall] = []
    seen: set[tuple[_facade().Any, ...]] = set()
    for trace in _facade()._iter_llm_trace_payloads(payload):
        call = _facade()._llm_call_from_trace(trace)
        if call is None:
            continue
        signature = _facade()._llm_call_signature(call)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append(call)
    return calls


def _refresh_llm_metadata(run: _facade().AgentRun) -> None:
    run.metadata["llm_call_count"] = len(run.llm_calls)
    run.metadata["llm_prompt_tokens_total"] = sum(
        int(call.prompt_tokens or 0) for call in run.llm_calls
    )
    run.metadata["llm_completion_tokens_total"] = sum(
        int(call.completion_tokens or 0) for call in run.llm_calls
    )
    run.metadata["llm_token_total"] = sum(int(call.total_tokens or 0) for call in run.llm_calls)
    run.metadata["llm_cost_units_total"] = sum(int(call.cost_units or 0) for call in run.llm_calls)
    _facade()._refresh_ai_cost_metadata(run)
    if run.llm_calls:
        last_call = run.llm_calls[-1]
        run.metadata["llm_provider"] = last_call.provider or last_call.provider_id
        run.metadata["llm_model"] = last_call.model


def _refresh_ai_cost_metadata(run: _facade().AgentRun) -> None:
    run.metadata["ai_cost_units_total"] = int(run.metadata.get("cost_units_total") or 0) + int(
        run.metadata.get("llm_cost_units_total") or 0
    )
    _facade().refresh_ai_budget_metadata(run)
