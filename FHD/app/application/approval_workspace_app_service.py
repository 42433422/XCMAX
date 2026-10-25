"""Public approval workspace API and late-bound application composition.

HTTP and Mod callers retain their existing entrypoints. Query, authorization,
decision, and execution components receive only their declared dependencies.
"""

from __future__ import annotations

import json
import logging
import os as os
import secrets
from datetime import datetime
from typing import TYPE_CHECKING, cast

from fastapi import Body, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.approval_workspace.access import (
    AI_WORKFLOW_BUSINESS_TYPE as AI_WORKFLOW_BUSINESS_TYPE,
)
from app.application.approval_workspace.access import (
    AI_WORKFLOW_NODE_NAME as AI_WORKFLOW_NODE_NAME,
)
from app.application.approval_workspace.access import (
    FINAL_STATUSES,
    normalize_statuses,
    resolve_actor,
)
from app.application.approval_workspace.access import (
    allow_x_user_id_header as _allow_x_user_id_header,
)
from app.application.approval_workspace.access import (
    can_review_workflow as _can_review_ai_workflow_request,
)
from app.application.approval_workspace.access import (
    is_workflow_request as _is_ai_workflow_request,
)
from app.application.approval_workspace.access import (
    next_node as _next_node,
)
from app.application.approval_workspace.access import (
    node_has_reviewer as _node_query_for_user,
)
from app.application.approval_workspace.decisions import ApprovalDecisions, advance_request
from app.application.approval_workspace.flow_catalog import FlowCatalog
from app.application.approval_workspace.outcomes import persist_outcome, safe_node_count
from app.application.approval_workspace.presentation import request_to_dict
from app.application.approval_workspace.protocols import (
    AgentContinuation,
    ApprovalAccess,
    ApprovalNodes,
    DecisionEffects,
    JsonObject,
    PendingApprovals,
    WorkflowActions,
    WorkflowBackends,
    WorkflowRunner,
    WorkspaceResponse,
)
from app.application.approval_workspace.queries import ApprovalQueries
from app.application.approval_workspace.repository import (
    ApprovalRepository,
)
from app.application.approval_workspace.repository import (
    ordered_nodes as _ordered_nodes,
)
from app.application.approval_workspace.repository import (
    workflow_audit_node as _ai_workflow_audit_node,
)
from app.application.approval_workspace.request_lifecycle import RequestLifecycle
from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
from app.application.mobile_push_app_service import notify_mobile_user
from app.db.models.approval import ApprovalAction as ApprovalAction
from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest
from app.db.models.approval import ApprovalRecord as ApprovalRecord
from app.db.models.approval import ApprovalStatus as ApprovalStatus
from app.db.models.user import User
from app.db.session import get_db
from app.domain.app_pure.approval_notifications import completed_workflow_notification
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.workflow_types import WorkflowRunResult

logger = logging.getLogger(__name__)
_FINAL_STATUSES = FINAL_STATUSES
_normalize_statuses = normalize_statuses
_persist_ai_workflow_outcome = persist_outcome
_safe_workflow_node_count = safe_node_count


def _resolve_actor(
    request: Request, x_user_id: str | None = None, fallback: int | None = None
) -> int | None:
    from app.infrastructure.auth.dependencies import resolve_session_user

    return resolve_actor(
        request,
        x_user_id,
        fallback,
        session_user=resolve_session_user,
        allow_header=_allow_x_user_id_header,
    )


def _audit(db: Session, *, actor: int | None, action: str, payload: JsonObject) -> None:
    try:
        db.execute(
            text(
                "INSERT INTO ai_action_audit (actor, action, payload) VALUES (:actor, :action, :payload)"
            ),
            {
                "actor": str(actor) if actor is not None else None,
                "action": action,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            },
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("ai_action_audit 写入失败 action=%s type=%s", action, type(exc).__name__)


def _generate_request_no() -> str:
    return f"APR{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


def _request_to_dict(req: ApprovalRequest, *, include_records: bool = False) -> JsonObject:
    return request_to_dict(
        req, include_records=include_records, is_workflow=_is_ai_workflow_request
    )


def _close_request_if_needed(
    db: Session,
    *,
    req: ApprovalRequest,
    nodes: list[ApprovalFlowNode],
    approver_id: int,
    approver_name: str | None,
) -> tuple[str, int | None]:
    return advance_request(
        db,
        req=req,
        nodes=nodes,
        approver_id=approver_id,
        approver_name=approver_name,
        next_node=_next_node,
    )


def _approval_backend() -> PendingApprovals:
    from app.application.workflow import get_approval_service

    return get_approval_service()


def _pending_snapshot(request_id: str) -> JsonObject | None:
    from app.application.workflow.approval_persistence import load_durable_workflow_snapshot

    return load_durable_workflow_snapshot(request_id, allow_terminal=False)


def _execution_snapshot(request_id: str) -> JsonObject | None:
    from app.application.workflow.approval_persistence import load_workflow_snapshot_for_execution

    return load_workflow_snapshot_for_execution(request_id)


def _workflow_engine() -> WorkflowRunner:
    from app.application.workflow import WorkflowEngine
    from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval

    return WorkflowEngine(tool_dispatcher=_dispatch_tool_for_approval)


def _agent_executor() -> AgentContinuation:
    from app.application.agent_orchestrator import AgentOrchestrator

    return AgentOrchestrator()


def _load_agent_run(run_id: str) -> AgentRun | None:
    from app.application.agent_orchestrator import get_agent_run_repository

    return get_agent_run_repository().get(run_id)


def _legacy_approval_trace(
    request_id: str,
    context: JsonObject,
    result: WorkflowRunResult | None = None,
    *,
    run_before_restore: AgentRun | None = None,
) -> str:
    from app.application.agent_orchestrator.chat_trace import resolve_legacy_approval

    if result is None and run_before_restore is None:
        return resolve_legacy_approval(request_id, context)
    return resolve_legacy_approval(
        request_id, context, result, run_before_restore=run_before_restore
    )


def _workflow_bridge() -> WorkflowApprovalBridge:
    return WorkflowApprovalBridge(
        WorkflowBackends(
            _approval_backend,
            _pending_snapshot,
            _execution_snapshot,
            _workflow_engine,
            _agent_executor,
            _load_agent_run,
            _legacy_approval_trace,
        ),
        RECOVERABLE_ERRORS,
        logger,
    )


def _has_pending_ai_workflow(request_no: str | None) -> bool:
    return _workflow_bridge().has_pending(request_no)


def _resume_pending_ai_workflow_after_approval(
    *, request_no: str, opinion: str, approved_by: str = ""
) -> JsonObject | None:
    return _workflow_bridge().resume(
        request_no=request_no, opinion=opinion, approved_by=approved_by
    )


def _drop_pending_ai_workflow_after_rejection(*, request_no: str, reason: str) -> JsonObject | None:
    return _workflow_bridge().reject(request_no=request_no, reason=reason)


def _project_workflow(run_id: str, request_id: str) -> None:
    from app.application.business_harness_projection import project_terminal_run_to_conversation

    project_terminal_run_to_conversation(run_id, approval_request_id=request_id)


def _active_users(db: Session) -> list[User]:
    from app.db.models import User

    return cast(list[User], db.query(User).filter(User.is_active == True).all())


def _roster_products() -> object:
    from app.application import get_product_app_service

    result = get_product_app_service().get_products(page=1, per_page=50)
    products: object = result.get("data", []) if result.get("success") else []
    return products


def _repository() -> ApprovalRepository:
    return ApprovalRepository(lambda: get_db())


def _access() -> ApprovalAccess:
    return ApprovalAccess(
        _resolve_actor,
        _is_ai_workflow_request,
        _can_review_ai_workflow_request,
        _node_query_for_user,
    )


def _queries() -> ApprovalQueries:
    return ApprovalQueries(
        _repository(),
        _access(),
        _request_to_dict,
        _has_pending_ai_workflow,
        _active_users,
        _roster_products,
        RECOVERABLE_ERRORS,
    )


def _requests() -> RequestLifecycle:
    return RequestLifecycle(
        _repository(), _access(), _audit, _request_to_dict, _ordered_nodes, _generate_request_no
    )


def _flows() -> FlowCatalog:
    return FlowCatalog(
        _repository(), _access(), _audit, ApprovalFlow, ApprovalFlowNode, utc_now_naive
    )


def _decisions() -> ApprovalDecisions:
    return ApprovalDecisions(
        _repository(),
        _access(),
        ApprovalNodes(
            _ordered_nodes, _ai_workflow_audit_node, _next_node, _close_request_if_needed
        ),
        WorkflowActions(
            _has_pending_ai_workflow,
            _resume_pending_ai_workflow_after_approval,
            _drop_pending_ai_workflow_after_rejection,
        ),
        DecisionEffects(
            _audit, notify_mobile_user, _project_workflow, completed_workflow_notification
        ),
        _request_to_dict,
        _approve_ai_workflow_request_without_node,
    )


def _approve_ai_workflow_request_without_node(
    db: Session, *, req: ApprovalRequest, actor: int, approver_name: str | None, opinion: str
) -> WorkspaceResponse:
    return _decisions().approve_workflow(
        db, req=req, actor=actor, approver_name=approver_name, opinion=opinion
    )


def process_approval_timeouts_endpoint():
    from app.application.workflow.approval_service import process_approval_timeouts

    result = process_approval_timeouts()
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


# Preserve the HTTP response contract: mixed dict/JSONResponse endpoints have no inferred model.
def list_requests(
    approver_id: int | None = Query(default=None),
    applicant_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    business_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    return _queries().list_requests(
        approver_id, applicant_id, status, business_type, page, page_size
    )


def get_request_detail(request_id: int):
    return _queries().get_request_detail(request_id)


def get_approval_users():
    return _queries().get_approval_users()


def check_approver_orphan(user_id: int):
    return _queries().check_approver_orphan(user_id)


def list_flows(
    is_active: bool | None = Query(default=None), business_type: str | None = Query(default=None)
):
    return _queries().list_flows(is_active, business_type)


def get_flow_detail(flow_id: int):
    return _queries().get_flow_detail(flow_id)


def submit_request(
    request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _requests().submit_request(request, body, x_user_id)


def cleanup_requests(
    request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _requests().cleanup_requests(request, body, x_user_id)


def withdraw_request(
    request_id: int,
    http_request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _requests().withdraw_request(request_id, http_request, body, x_user_id)


def delete_request(
    request_id: int,
    http_request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _requests().delete_request(request_id, http_request, x_user_id)


def approve_request(
    request_id: int,
    http_request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _decisions().approve_request(request_id, http_request, body, x_user_id)


def reject_request(
    request_id: int,
    http_request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _decisions().reject_request(request_id, http_request, body, x_user_id)


def create_flow(
    request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _flows().create_flow(request, body, x_user_id)


def update_flow(
    flow_id: int,
    request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _flows().update_flow(flow_id, request, body, x_user_id)


def toggle_flow_active(
    flow_id: int,
    request: Request,
    body: JsonObject = Body(default_factory=dict),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    return _flows().toggle_flow_active(flow_id, request, body, x_user_id)


def delete_flow(
    flow_id: int, request: Request, x_user_id: str | None = Header(default=None, alias="X-User-ID")
):
    return _flows().delete_flow(flow_id, request, x_user_id)
