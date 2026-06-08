"""Optional circuit breaker wrapper for HTTP cross-domain clients."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def call_with_circuit(
    name: str,
    fn: Callable[[], T],
    *,
    fail_max: int | None = None,
) -> T:
    """Invoke ``fn`` behind ``pybreaker.CircuitBreaker`` when dependency is installed."""

    raw = (os.environ.get("MODSTORE_CIRCUIT_FAIL_MAX") or "").strip()
    fm = fail_max if fail_max is not None else (int(raw) if raw.isdigit() else 5)
    try:
        import pybreaker  # type: ignore[import-not-found]

        br = pybreaker.CircuitBreaker(fail_max=fm, name=f"modstore:{name}")
        return br.call(fn)
    except Exception:  # noqa: BLE001
        return fn()


def observe_circuit_state(name: str, state: str) -> None:
    """Hook for Prometheus counters (optional)."""

    logger.debug("circuit %s -> %s", name, state)


__all__ = ["call_with_circuit", "observe_circuit_state"]
