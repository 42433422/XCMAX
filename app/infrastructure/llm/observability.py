"""LLM 调用可观测 — trace_id、token、延迟、估算成本（token 钱包真相源）。"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.neuro_bus.tracer import current_trace

logger = logging.getLogger(__name__)

# USD / 1K tokens（可按模型表扩展）
_DEFAULT_COST_PER_1K = 0.002


@dataclass(frozen=True)
class LLMUsageEvent:
    trace_id: str
    provider_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    wallet_debit_id: str | None = None
    profile: str = "default"
    extra: dict[str, Any] = field(default_factory=dict)


def _trace_id() -> str:
    return current_trace.get() or str(uuid.uuid4())


def _parse_usage(raw: dict[str, Any] | None) -> tuple[int, int, int]:
    if not raw:
        return 0, 0, 0
    usage_obj = raw.get("usage")
    usage: dict[str, Any] = usage_obj if isinstance(usage_obj, dict) else {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return prompt, completion, total


def estimate_cost_usd(total_tokens: int, *, cost_per_1k: float = _DEFAULT_COST_PER_1K) -> float:
    return round((total_tokens / 1000.0) * cost_per_1k, 6)


def record_llm_usage(
    *,
    provider_id: str,
    model: str,
    raw: dict[str, Any] | None,
    latency_ms: float,
    profile: str = "default",
    wallet_debit_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> LLMUsageEvent:
    prompt, completion, total = _parse_usage(raw)
    event = LLMUsageEvent(
        trace_id=_trace_id(),
        provider_id=provider_id,
        model=model or "unknown",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        latency_ms=round(latency_ms, 2),
        estimated_cost_usd=estimate_cost_usd(total),
        wallet_debit_id=wallet_debit_id,
        profile=profile,
        extra=extra or {},
    )
    logger.info(
        "llm_usage trace_id=%s provider=%s model=%s tokens=%s latency_ms=%s cost_usd=%s wallet=%s",
        event.trace_id,
        event.provider_id,
        event.model,
        event.total_tokens,
        event.latency_ms,
        event.estimated_cost_usd,
        event.wallet_debit_id or "-",
        extra={
            "llm_observability": True,
            "prompt_tokens": event.prompt_tokens,
            "completion_tokens": event.completion_tokens,
            "profile": event.profile,
            **event.extra,
        },
    )
    return event


class LLMInvokeTimer:
    """Context manager for timed LLM calls."""

    def __init__(self) -> None:
        self._t0 = 0.0
        self.latency_ms = 0.0

    def __enter__(self) -> LLMInvokeTimer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.latency_ms = (time.perf_counter() - self._t0) * 1000.0
