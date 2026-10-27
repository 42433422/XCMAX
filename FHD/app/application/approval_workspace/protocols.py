"""Narrow dependencies shared by approval transactions and execution adapters."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlowNode, ApprovalRequest

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.workflow_types import PlanGraph, WorkflowRunResult

JsonObject = dict[str, Any]
WorkspaceResponse = JsonObject | JSONResponse
SessionFactory = Callable[[], AbstractContextManager[Session]]


class ActorResolver(Protocol):
    def __call__(
        self, request: Request, x_user_id: str | None = None, fallback: int | None = None
    ) -> int | None: ...


class RequestView(Protocol):
    def __call__(self, req: ApprovalRequest, *, include_records: bool = False) -> JsonObject: ...


class AuditWriter(Protocol):
    def __call__(
        self, db: Session, *, actor: int | None, action: str, payload: JsonObject
    ) -> None: ...


class AdvanceRequest(Protocol):
    def __call__(
        self,
        db: Session,
        *,
        req: ApprovalRequest,
        nodes: list[ApprovalFlowNode],
        approver_id: int,
        approver_name: str | None,
    ) -> tuple[str, int | None]: ...


class ApproveWithoutNode(Protocol):
    def __call__(
        self,
        db: Session,
        *,
        req: ApprovalRequest,
        actor: int,
        approver_name: str | None,
        opinion: str,
    ) -> WorkspaceResponse: ...


class ResumeWorkflow(Protocol):
    def __call__(
        self, *, request_no: str, opinion: str, approved_by: str = ""
    ) -> JsonObject | None: ...


class RejectWorkflow(Protocol):
    def __call__(self, *, request_no: str, reason: str) -> JsonObject | None: ...


@dataclass(frozen=True)
class ApprovalAccess:
    actor: ActorResolver
    is_workflow: Callable[[ApprovalRequest], bool]
    workflow_reviewer: Callable[[Session, ApprovalRequest, int], bool]
    node_reviewer: Callable[[ApprovalFlowNode | None, int], bool]


@dataclass(frozen=True)
class ApprovalNodes:
    ordered: Callable[[Session, int], list[ApprovalFlowNode]]
    audit_node: Callable[[Session, ApprovalRequest], ApprovalFlowNode | None]
    next_node: Callable[[list[ApprovalFlowNode], int], ApprovalFlowNode | None]
    advance: AdvanceRequest


@dataclass(frozen=True)
class WorkflowActions:
    pending: Callable[[str | None], bool]
    resume: ResumeWorkflow
    reject: RejectWorkflow


@dataclass(frozen=True)
class DecisionEffects:
    audit: AuditWriter
    notify: Callable[[int, str, str, dict[str, str]], object]
    project: Callable[[str, str], None]
    completed_notification: Callable[[ApprovalRequest], tuple[int, str, str, dict[str, str]]]


class PendingApprovals(Protocol):
    def approve(self, request_id: str, comment: str = "") -> bool: ...
    def reject(self, request_id: str, comment: str = "") -> bool: ...
    def get_pending_workflow(self, request_id: str) -> JsonObject | None: ...
    def remove_pending_workflow(self, request_id: str) -> JsonObject | None: ...


class AgentContinuation(Protocol):
    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: JsonObject | None = None,
    ) -> AgentRun | None: ...

    def cancel_run(self, run_id: str, *, requested_by: str = "") -> AgentRun | None: ...


class WorkflowRunner(Protocol):
    def run(
        self, plan: PlanGraph, runtime_context: JsonObject | None = None, max_retries: int = 1
    ) -> WorkflowRunResult: ...


class LegacyApprovalTrace(Protocol):
    def __call__(
        self,
        request_id: str,
        context: JsonObject,
        result: WorkflowRunResult | None = None,
        *,
        run_before_restore: AgentRun | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class WorkflowBackends:
    approvals: Callable[[], PendingApprovals]
    pending_snapshot: Callable[[str], JsonObject | None]
    execution_snapshot: Callable[[str], JsonObject | None]
    engine: Callable[[], WorkflowRunner]
    agent: Callable[[], AgentContinuation]
    load_run: Callable[[str], AgentRun | None]
    legacy_trace: LegacyApprovalTrace
