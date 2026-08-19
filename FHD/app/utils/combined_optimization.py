"""Composition factory for XCAGI performance decorators."""

from __future__ import annotations

from collections.abc import Callable


def combined_optimization(
    cache_ttl: int = 0,
    rate_limit: int = 0,
    monitor_slow_ms: float = 0,
    dedup_window: int = 0,
    circuit_failures: int = 0,
    retry_times: int = 0,
):
    """Compose only the optimization policies enabled by positive values."""

    def decorator(func: Callable) -> Callable:
        # Resolve through the compatibility module so callers can patch or
        # extend any individual decorator without changing composition.
        from app.utils import decorators

        decorated = func
        if retry_times > 0:
            decorated = decorators.retry(max_retries=retry_times)(decorated)
        if circuit_failures > 0:
            decorated = decorators.circuit_breaker(failure_threshold=circuit_failures)(decorated)
        if dedup_window > 0:
            decorated = decorators.deduplicated(window_seconds=dedup_window)(decorated)
        if rate_limit > 0:
            decorated = decorators.rate_limited(max_requests=rate_limit)(decorated)
        if cache_ttl > 0:
            decorated = decorators.cached(ttl=cache_ttl)(decorated)
        if monitor_slow_ms > 0:
            decorated = decorators.monitored(slow_threshold_ms=monitor_slow_ms)(decorated)
        return decorated

    return decorator
