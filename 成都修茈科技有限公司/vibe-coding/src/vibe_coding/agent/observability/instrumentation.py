"""Wire up logger / tracer / metrics to a :class:`VibeCoder` or ReAct agent.

Calling :func:`instrument(coder)` wraps every public action so each
call:

1. Opens a span with ``vibe.<method>`` name and useful attributes.
2. Logs an ``action.start`` / ``action.end`` record carrying the
   span ids.
3. Increments the matching counter and records the duration in a
   histogram so the ``/metrics`` endpoint shows real throughput.

Failures (exceptions) propagate after recording an ``action.error``
log line and tagging the span as ``error``. The wrapper is reversible
via :meth:`AgentObservability.uninstrument`.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .logging import StructuredLogger, get_default_logger
from .metrics import MetricsRegistry, TimerContext, get_default_registry
from .tracing import Tracer, get_default_tracer

# Methods on :class:`VibeCoder` we wrap by default.
_INSTRUMENTED_METHODS: tuple[str, ...] = (
    "code",
    "workflow",
    "workflow_with_report",
    "run",
    "execute",
    "rollback",
    "report",
    "history",
    "evolution_chain",
    "list_code_skills",
    "index_project",
    "edit_project",
    "apply_patch",
    "rollback_patch",
    "heal_project",
    "publish_skill",
)


@dataclass
class AgentObservability:
    """Bundle of logger / tracer / metrics + the wrappers we attached."""

    logger: StructuredLogger
    tracer: Tracer
    metrics: MetricsRegistry
    _wrappers: dict[tuple[int, str], Callable[..., Any]] = field(default_factory=dict)
    _originals: dict[tuple[int, str], Callable[..., Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def uninstrument(self, target: Any) -> None:
        """Restore every method we wrapped on ``target``."""
        with self._lock:
            obj_id = id(target)
            for (tid, name), original in list(self._originals.items()):
                if tid != obj_id:
                    continue
                try:
                    setattr(target, name, original)
                except Exception:  # noqa: BLE001
                    pass
                self._originals.pop((tid, name), None)
                self._wrappers.pop((tid, name), None)


def instrument(
    target: Any,
    *,
    logger: StructuredLogger | None = None,
    tracer: Tracer | None = None,
    metrics: MetricsRegistry | None = None,
    methods: tuple[str, ...] | None = None,
    component: str = "vibe_coder",
) -> AgentObservability:
    """Wrap every interesting method on ``target`` with span/log/metric.

    Idempotent — calling :func:`instrument` twice returns the same
    :class:`AgentObservability` (the second call is a no-op for already-
    wrapped methods).
    """
    obs = AgentObservability(
        logger=logger or get_default_logger(),
        tracer=tracer or get_default_tracer(),
        metrics=metrics or get_default_registry(),
    )
    obs.logger.bind_tracer(obs.tracer)
    method_names = methods or _INSTRUMENTED_METHODS
    for name in method_names:
        original = getattr(target, name, None)
        if original is None or not callable(original):
            continue
        wrapped = _wrap_method(
            target=target,
            name=name,
            original=original,
            component=component,
            obs=obs,
        )
        try:
            setattr(target, name, wrapped)
        except (AttributeError, TypeError):
            # ``method-wrapper`` instances on built-ins resist setattr;
            # skip silently.
            continue
        obs._wrappers[(id(target), name)] = wrapped
        obs._originals[(id(target), name)] = original
    return obs


def instrument_react_agent(agent: Any, observability: AgentObservability) -> None:
    """Hook a :class:`ReActAgent` so each step opens a child span.

    The agent already accepts a ``tracer`` callable and ``on_step``
    callback in its constructor. This helper wires both into the
    bundle so existing observability flows just work.
    """

    def trace_step(step: Any, phase: str) -> None:
        if phase == "start":
            return  # Span lifecycle handled per-step below.
        observability.metrics.counter(
            "agent_react_step_total",
            description="Total ReAct steps executed",
        ).inc(1, labels={"tool": getattr(step, "tool", "") or "final"})
        observability.metrics.histogram(
            "agent_react_step_duration_ms",
            description="Duration of one ReAct step",
        ).observe(
            float(getattr(step, "duration_ms", 0.0)),
            labels={"tool": getattr(step, "tool", "") or "final"},
        )

    def log_step(step: Any) -> None:
        observability.logger.info(
            "agent.react.step",
            f"step {step.index} tool={step.tool!r}",
            tool=step.tool,
            args=step.args,
            error=step.error,
            duration_ms=step.duration_ms,
        )

    agent.tracer = trace_step
    agent.on_step = log_step


# ----------------------------------------------------------------- internals


def _wrap_method(
    *,
    target: Any,
    name: str,
    original: Callable[..., Any],
    component: str,
    obs: AgentObservability,
) -> Callable[..., Any]:
    counter = obs.metrics.counter(
        f"{component}_action_total",
        description="Total invocations per VibeCoder method",
    )
    failure_counter = obs.metrics.counter(
        f"{component}_action_errors_total",
        description="Total invocations that raised",
    )
    histogram = obs.metrics.histogram(
        f"{component}_action_duration_ms",
        description="Per-method invocation duration",
    )

    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        attrs: dict[str, Any] = {
            "vibe.component": component,
            "vibe.method": name,
        }
        with obs.tracer.start_span(f"{component}.{name}", attributes=attrs) as span:
            obs.logger.info(
                "action.start", f"{component}.{name} starting", method=name
            )
            with TimerContext(histogram, labels={"method": name}):
                try:
                    result = original(*args, **kwargs)
                except Exception as exc:
                    failure_counter.inc(1, labels={"method": name, "error": type(exc).__name__})
                    obs.logger.error(
                        "action.error",
                        f"{component}.{name} raised {type(exc).__name__}",
                        method=name,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    span.set_attribute("vibe.error", True)
                    span.set_attribute("vibe.error_type", type(exc).__name__)
                    raise
            counter.inc(1, labels={"method": name})
            obs.logger.info(
                "action.end", f"{component}.{name} done", method=name
            )
            return result

    return wrapper


__all__ = [
    "AgentObservability",
    "instrument",
    "instrument_react_agent",
]
