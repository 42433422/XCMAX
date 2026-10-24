"""Normalize completed responses and publish one best-effort roundtrip observation."""

from __future__ import annotations

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import Connection, Payload, ResponsePorts, Route


def _response_status_code(response: object, default: int = 200) -> int:
    raw = getattr(response, "status_code", default)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return default


def neuro_notify_ai_model_roundtrip(
    *, model: str, latency_ms: float, token_count: int, user_id: str
) -> None:
    from app.neuro_bus.application_neuro_bridge import neuro_notify_ai_model_roundtrip as notify

    notify(model=model, latency_ms=latency_ms, token_count=token_count, user_id=user_id)


def finish_completion(
    result: Payload,
    connection: Connection,
    route: Route,
    latency_ms: float,
    ports: ResponsePorts,
) -> Payload:
    used_provider = str(result.get("provider") or route[0])
    used_model = str(result.get("model") or route[1])
    try:
        raw_usage = result.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        try:
            count = int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            count = 0
        ports.notify(
            model=f"modstore:{used_provider}/{used_model}",
            latency_ms=latency_ms,
            token_count=count,
            user_id=str(connection.user_id or ""),
        )
    except RECOVERABLE_ERRORS:
        pass
    ports.logger.info(
        "[Modstore] 调用成功 [%.0fms], %s/%s key_source=%s billed=%s",
        latency_ms,
        used_provider,
        used_model,
        result.get("key_source", "unknown"),
        result.get("billed", False),
    )
    return ports.normalize(result, used_provider, used_model)
