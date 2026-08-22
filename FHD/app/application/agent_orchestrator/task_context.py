"""Durable task identity and workspace metadata for AgentRun."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun


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
    return task_context


def task_context_of(run: AgentRun) -> dict[str, Any]:
    existing = run.metadata.get("task_context")
    if isinstance(existing, dict):
        return dict(existing)
    runtime = run.metadata.get("runtime_context")
    return build_task_context(run, runtime if isinstance(runtime, dict) else {})


__all__ = ["apply_task_context", "build_task_context", "task_context_of"]
