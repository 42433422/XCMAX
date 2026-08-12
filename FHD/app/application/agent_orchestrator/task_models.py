"""Durable task and control-command models shared by API and repositories."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_context import task_context_of
from app.application.agent_orchestrator.task_progress import (
    fallback_task_progress_snapshot,
    progress_snapshot_of_task_metadata,
    task_progress_snapshot,
)

TaskAttention = Literal["", "approval_required", "blocked", "failed", "result_unread"]
TaskControlAction = Literal["pause", "cancel", "resume"]
TaskControlStatus = Literal["requested", "applied", "superseded", "rejected"]


def attention_for_status(status: str) -> TaskAttention:
    return {
        "waiting_user": "approval_required",
        "blocked": "blocked",
        "failed": "failed",
        "completed": "result_unread",
    }.get(str(status or ""), "")  # type: ignore[return-value]


def tenant_id_of_run(run: AgentRun) -> str:
    runtime = run.metadata.get("runtime_context")
    runtime = runtime if isinstance(runtime, dict) else {}
    return str(runtime.get("tenant_id") or "")


@dataclass
class AgentTask:
    task_id: str
    user_id: str
    title: str
    status: str = "queued"
    tenant_id: str = ""
    source: str = "agent"
    task_type: str = "agent"
    attention_state: TaskAttention = ""
    active_run_id: str = ""
    root_run_id: str = ""
    conversation_id: str = ""
    workspace_id: str = ""
    workspace_path: str = ""
    workspace_isolation: str = "business_workspace"
    attempt: int = 1
    run_count: int = 1
    archived_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        progress = progress_snapshot_of_task_metadata(self.metadata)
        if not progress:
            progress = fallback_task_progress_snapshot(
                status=self.status,
                attempt=self.attempt,
                updated_at=self.updated_at,
            )
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "title": self.title,
            "source": self.source,
            "task_type": self.task_type,
            "status": self.status,
            "attention_state": self.attention_state,
            "unread_count": int(self.attention_state == "result_unread"),
            "approval_required": self.attention_state == "approval_required",
            "active_run_id": self.active_run_id,
            "root_run_id": self.root_run_id,
            "conversation_id": self.conversation_id,
            "workspace_id": self.workspace_id,
            "workspace_path": self.workspace_path,
            "workspace_isolation": self.workspace_isolation,
            "attempt": self.attempt,
            "run_count": self.run_count,
            "progress": progress,
            "archived_at": self.archived_at,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TaskControlCommand:
    task_id: str
    run_id: str
    action: TaskControlAction
    requested_by: str = ""
    status: TaskControlStatus = "requested"
    command_id: str = field(default_factory=lambda: f"taskcmd_{uuid.uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    applied_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "action": self.action,
            "status": self.status,
            "requested_by": self.requested_by,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
        }


def task_from_run(run: AgentRun, *, existing: AgentTask | None = None) -> AgentTask:
    context = task_context_of(run)
    runtime = run.metadata.get("runtime_context")
    runtime = runtime if isinstance(runtime, dict) else {}
    task_id = str(context.get("task_id") or run.run_id)
    attempt = max(1, int(context.get("attempt") or 1))
    current = existing or AgentTask(
        task_id=task_id,
        user_id=run.user_id,
        title=str(context.get("title") or run.message or task_id),
        created_at=run.created_at,
    )
    if existing is not None and attempt < existing.attempt:
        return existing
    current.user_id = run.user_id
    current.tenant_id = str(runtime.get("tenant_id") or current.tenant_id or "")[:128]
    current.title = str(context.get("title") or current.title or run.message or task_id)[:160]
    current.source = str(runtime.get("source") or current.source or "agent")[:48]
    current.task_type = str(runtime.get("task_type") or current.task_type or "agent")[:48]
    current.status = str(run.status or "queued")
    current.attention_state = attention_for_status(current.status)
    is_new_run = existing is not None and existing.active_run_id != run.run_id
    current.active_run_id = run.run_id
    current.root_run_id = str(current.root_run_id or context.get("root_run_id") or run.run_id)
    current.conversation_id = str(context.get("conversation_id") or "")[:160]
    current.workspace_id = str(context.get("workspace_id") or "")[:160]
    current.workspace_path = str(context.get("workspace_path") or "")
    current.workspace_isolation = str(context.get("isolation") or "business_workspace")[:48]
    if existing is not None and attempt > existing.attempt:
        current.archived_at = ""
    current.attempt = attempt
    current.run_count = max(current.run_count + int(is_new_run), attempt)
    current.metadata = {
        **dict(current.metadata or {}),
        "task_model_version": int(runtime.get("task_model_version") or 1),
        "task_request": dict(run.metadata.get("task_request") or {}),
        "task_request_fingerprint": str(run.metadata.get("task_request_fingerprint") or ""),
        "progress": task_progress_snapshot(run),
    }
    current.updated_at = run.updated_at
    return current


def agent_task_from_dict(data: dict[str, Any]) -> AgentTask:
    return AgentTask(
        task_id=str(data.get("task_id") or ""),
        user_id=str(data.get("user_id") or ""),
        tenant_id=str(data.get("tenant_id") or ""),
        title=str(data.get("title") or ""),
        source=str(data.get("source") or "agent"),
        task_type=str(data.get("task_type") or "agent"),
        status=str(data.get("status") or "queued"),
        attention_state=str(data.get("attention_state") or ""),  # type: ignore[arg-type]
        active_run_id=str(data.get("active_run_id") or ""),
        root_run_id=str(data.get("root_run_id") or ""),
        conversation_id=str(data.get("conversation_id") or ""),
        workspace_id=str(data.get("workspace_id") or ""),
        workspace_path=str(data.get("workspace_path") or ""),
        workspace_isolation=str(data.get("workspace_isolation") or "business_workspace"),
        attempt=max(1, int(data.get("attempt") or 1)),
        run_count=max(1, int(data.get("run_count") or 1)),
        archived_at=str(data.get("archived_at") or ""),
        metadata=dict(data.get("metadata") or {}),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        updated_at=str(data.get("updated_at") or "") or utc_now_iso(),
    )


def task_control_from_dict(data: dict[str, Any]) -> TaskControlCommand:
    return TaskControlCommand(
        command_id=str(data.get("command_id") or "") or f"taskcmd_{uuid.uuid4().hex}",
        task_id=str(data.get("task_id") or ""),
        run_id=str(data.get("run_id") or ""),
        action=str(data.get("action") or "pause"),  # type: ignore[arg-type]
        status=str(data.get("status") or "requested"),  # type: ignore[arg-type]
        requested_by=str(data.get("requested_by") or ""),
        metadata=dict(data.get("metadata") or {}),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
        applied_at=str(data.get("applied_at") or ""),
    )


__all__ = [
    "AgentTask",
    "TaskControlCommand",
    "agent_task_from_dict",
    "attention_for_status",
    "task_control_from_dict",
    "task_from_run",
    "tenant_id_of_run",
]
