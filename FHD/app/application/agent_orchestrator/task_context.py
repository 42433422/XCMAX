"""Durable task identity and workspace metadata for AgentRun."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from math import isfinite
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid4, uuid5

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun


def ensure_run_trace(run: AgentRun, *, bind: bool = False, live: bool = True) -> dict[str, str]:
    """Bind durable observations to server context, never caller-supplied task fields."""
    from app.neuro_bus.tracer import NeuroTracer, get_trace_context
    from app.utils.operational_errors import BOUNDARY_ERRORS

    current = get_trace_context() if live else {}
    if bind and not run.metadata.get("trace_id"):
        if not current.get("trace_id"):
            try:
                anchor = NeuroTracer().start_span("agent.run.created", tags={"run_id": run.run_id})
                try:
                    with anchor.context():
                        current = get_trace_context()
                finally:
                    anchor.finish()
            except BOUNDARY_ERRORS:
                # Business task creation remains available if optional SDK
                # setup fails; a generated correlation is unsampled by default.
                pass
        run.metadata["trace_id"] = current.get("trace_id") or uuid4().hex
        run.metadata["span_id"] = current.get("span_id") or uuid4().hex[:16]
        for key in ("request_id", "trace_flags", "trace_state"):
            if key in current:
                run.metadata[key] = current[key]
    context = {
        key: str(run.metadata[key])
        for key in ("trace_id", "span_id", "request_id", "trace_flags", "trace_state")
        if run.metadata.get(key)
    }
    # Older persisted runs must keep exact CAS evidence. Canonicalize the
    # observation view deterministically without rewriting their old snapshot.
    for key, length in (("trace_id", 32), ("span_id", 16)):
        raw = context.get(key, "")
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", raw) or int(raw, 16) == 0:
            context[key] = uuid5(NAMESPACE_URL, f"xcagi.{key}:{raw or run.run_id}").hex[:length]
    if current.get("trace_id") == context["trace_id"]:
        context.update(current)
    context.setdefault("trace_flags", "00")
    context["run_id"] = run.run_id
    task = run.metadata.get("task_context")
    task = task if isinstance(task, dict) else {}
    context["task_id"] = str(task.get("task_id") or run.run_id)
    return context


@contextmanager
def observe_run_phase(run: AgentRun, phase: str) -> Iterator[None]:
    """Measure active segments; persisted totals never subtract clocks across restarts."""
    from app.neuro_bus.tracer import NeuroTracer, SpanStatus, TraceContext, get_trace_context
    from app.utils.operational_errors import BOUNDARY_ERRORS

    with ExitStack() as scopes:
        span = None
        try:
            context = ensure_run_trace(run)
            scopes.enter_context(
                TraceContext(
                    trace_id=context["trace_id"],
                    span_id=context.get("span_id"),
                    request_id=get_trace_context().get("request_id") or context.get("request_id"),
                    trace_flags=context.get("trace_flags"),
                    trace_state=context.get("trace_state"),
                )
            )
            span = NeuroTracer().start_span(f"agent.{phase}", tags={"run_id": run.run_id})
            scopes.enter_context(span.context())
        except BOUNDARY_ERRORS:
            scopes.close()
            span = None
        error_type = ""
        try:
            yield
        except BaseException as exc:
            error_type = type(exc).__name__
            raise
        finally:
            try:
                if span is not None:
                    failed = bool(error_type) or run.status in {"failed", "blocked", "rejected"}
                    cancelled = run.status == "cancelled" or error_type in {
                        "CancelledError",
                        "GeneratorExit",
                    }
                    span.finish(
                        SpanStatus.CANCELLED
                        if cancelled
                        else SpanStatus.ERROR
                        if failed
                        else SpanStatus.OK
                    )
                    duration = span.duration_ms or 0.0
                    previous = run.metadata.get("active_duration_ms")
                    previous = (
                        previous
                        if isinstance(previous, (int, float))
                        and not isinstance(previous, bool)
                        and isfinite(previous)
                        and previous >= 0
                        else 0
                    )
                    total = round(previous + duration, 3)
                    run.metadata["active_duration_ms"] = total
                    details: dict[str, Any] = {
                        "phase": phase,
                        "phase_duration_ms": duration,
                        "duration_ms": total,
                        "duration_scope": "active",
                        "status": run.status,
                        "parent_span_id": span.parent_id or "",
                    }
                    if cancelled:
                        details.update(error_code="agent_phase_cancelled", error_type=error_type)
                    elif failed:
                        details.update(
                            error_code="agent_phase_failed"
                            if error_type
                            else "agent_run_" + run.status,
                            error_type=error_type,
                        )
                    run.add_event("run.observed", "执行阶段观测已记录", details)
            except BOUNDARY_ERRORS:
                # Optional telemetry must not replace a business exception or
                # cause a committed tool to be retried.
                pass


def _text(value: Any, *, limit: int = 512) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _positive_int(value: Any, *, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def build_task_context(
    run: AgentRun,
    runtime_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize caller context into a stable, non-secret task descriptor."""
    context = dict(runtime_context or {})
    existing = run.metadata.get("task_context")
    previous = dict(existing) if isinstance(existing, dict) else {}

    conversation_id = _text(
        context.get("conversation_id")
        or context.get("session_id")
        or previous.get("conversation_id"),
        limit=160,
    )
    parent_run_id = _text(
        context.get("parent_run_id") or previous.get("parent_run_id"),
        limit=96,
    )
    root_run_id = _text(
        context.get("root_run_id") or previous.get("root_run_id") or run.run_id,
        limit=96,
    )
    workspace_id = _text(
        context.get("workspace_id")
        or context.get("workspace")
        or context.get("mod_id")
        or previous.get("workspace_id"),
        limit=160,
    )
    workspace_path = _text(
        context.get("worktree_path")
        or context.get("workspace_path")
        or context.get("cwd")
        or previous.get("workspace_path"),
        limit=1024,
    )
    isolation = _text(
        context.get("workspace_isolation")
        or previous.get("isolation")
        or ("worktree" if context.get("worktree_path") else "business_workspace"),
        limit=48,
    )
    title = _text(
        context.get("task_title") or previous.get("title") or run.message,
        limit=80,
    )
    if len(title) == 80 and len(str(context.get("task_title") or run.message or "").strip()) > 80:
        title = title.rstrip() + "…"

    task_context = {
        "task_id": _text(
            context.get("task_id") or previous.get("task_id") or run.run_id,
            limit=160,
        ),
        "title": title or f"智能任务 {run.run_id[-8:]}",
        "conversation_id": conversation_id,
        "root_run_id": root_run_id,
        "parent_run_id": parent_run_id,
        "attempt": _positive_int(
            context.get("task_attempt") or previous.get("attempt"),
        ),
        "workspace_id": workspace_id,
        "workspace_path": workspace_path,
        "isolation": isolation,
    }
    turn_id = _text(context.get("turn_id") or previous.get("turn_id"), limit=160)
    if turn_id:
        task_context["turn_id"] = turn_id
    return task_context


def apply_task_context(
    run: AgentRun,
    runtime_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach a durable task descriptor without recording secrets or tool tokens."""
    task_context = build_task_context(run, runtime_context)
    run.metadata["task_context"] = task_context
    ensure_run_trace(run, bind=True)
    return task_context


def task_context_of(run: AgentRun) -> dict[str, Any]:
    existing = run.metadata.get("task_context")
    if isinstance(existing, dict):
        return dict(existing)
    runtime = run.metadata.get("runtime_context")
    return build_task_context(run, runtime if isinstance(runtime, dict) else {})


__all__ = ["apply_task_context", "build_task_context", "task_context_of"]
