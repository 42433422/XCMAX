# mypy: disable-error-code="arg-type, assignment"
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowExecution,
    get_session_factory,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from modstore_server.quota_middleware import require_llm_credit
from modstore_server.workflow_api.schemas import WorkflowExecuteBody

logger = logging.getLogger(__name__)

router = APIRouter()
_DB_SESSION = Depends(get_db)
_CURRENT_USER = Depends(_get_current_user)


@router.post("/{workflow_id}/execute", summary="执行工作流")
async def execute_workflow(
    workflow_id: int,
    body: WorkflowExecuteBody,
    request: Request,
    db: Session = _DB_SESSION,
    user: User = _CURRENT_USER,
):
    from modstore_server.workflow_engine import execute_workflow as engine_execute

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    if not workflow.is_active:
        raise HTTPException(400, "工作流未激活")

    sf = get_session_factory()
    with sf() as qdb:
        require_llm_credit(qdb, user.id, 1)
    execution = WorkflowExecution(
        workflow_id=workflow_id,
        user_id=user.id,
        status="running",
        input_data=json.dumps(body.input_data or {}),
    )
    execution_input_json = str(execution.input_data)
    owner_user_id = int(user.id)
    execution_id = None
    execution_started_at = None
    initial_commit_attempted = False

    from modstore_server.workflow_execution_feedback import (
        GRAPH_GUARD_FAILED,
        begin_execution_feedback,
        complete_execution_feedback,
    )

    failure_message: str | None = None
    public_failure_message = ""
    binding: dict[str, Any] = {}
    returned_customer = None
    failed_execution = None
    try:
        db.add(execution)
        db.flush()
        execution_id = int(execution.id)
        execution_started_at = execution.started_at
        initial_commit_attempted = True
        db.commit()
        db.refresh(execution)
        binding = begin_execution_feedback(db, execution) or {}
        db.commit()
        if binding.get("blocked"):
            raise ValueError(binding["blocked"])
        output_data = engine_execute(
            workflow_id,
            body.input_data or {},
            user_id=user.id,
            **({"expected_graph_fingerprint": binding["graph_fingerprint"]} if binding else {}),
            **({"execution_id": execution.id} if binding.get("customer_delivery") else {}),
        )
        output_json = json.dumps(output_data)
        completed_at = datetime.now(UTC)
        if binding.get("customer_delivery") is True:
            from modstore_server.workflow_customer_finalization import ReturnedCustomerWorkflow

            # Do not dirty the ORM terminal before its identity/status CAS;
            # billing and feedback queries may otherwise autoflush it.
            returned_customer = ReturnedCustomerWorkflow(
                execution_id=execution_id,
                workflow_id=workflow_id,
                user_id=owner_user_id,
                started_at=execution_started_at,
                input_json=execution_input_json,
                graph_fingerprint=binding["graph_fingerprint"],
                output_json=output_json,
                completed_at=completed_at,
            )
        else:
            execution.status = "completed"
            execution.output_data = output_json
            execution.completed_at = completed_at
        # 统一计费 + 防免费洞：删计次后，java 后端经 JavaWallet 结算、python 后端扣钱包，
        # 永不免费（见 llm_billing.bill_internal_llm_floor）。
        try:
            from modstore_server.llm_billing import (
                authorization_header,
                bill_internal_llm_floor,
            )

            await bill_internal_llm_floor(
                authorization_header(request),
                user_id=user.id,
                label=f"workflow:{workflow_id}",
            )
        except BOUNDARY_ERRORS as bill_err:
            logger.warning(
                "workflow execute billing failed (user=%s wf=%s): %s",
                user.id,
                workflow_id,
                bill_err,
            )
    except RECOVERABLE_ERRORS as e:
        returned_customer = None
        failure_message = str(e)
        public_failure_message = "工作流执行失败，请查看执行记录"
        if isinstance(e, ValueError):
            if failure_message == GRAPH_GUARD_FAILED:
                public_failure_message = GRAPH_GUARD_FAILED
            elif (
                failure_message
                == binding.get("blocked")
                == "workflow_experiment_graph_no_longer_approved"
            ):
                public_failure_message = "workflow_experiment_graph_no_longer_approved"
        try:
            db.rollback()
            if initial_commit_attempted:
                from modstore_server.workflow_event_runner import persist_workflow_failure

                recorded, failed_execution = persist_workflow_failure(
                    session_factory=sf,
                    execution_id=execution_id,
                    workflow_id=workflow_id,
                    user_id=owner_user_id,
                    started_at=execution_started_at,
                    error=e,
                    completed_at=datetime.now(UTC),
                )
            else:
                recorded = False
        except RECOVERABLE_ERRORS as recording_error:
            raise e from recording_error
        if not recorded:
            if failed_execution is not None:
                raise HTTPException(409, "执行记录状态已变化，请查看执行记录") from e
            raise HTTPException(500, public_failure_message) from e
    completed_customer = None
    if returned_customer is not None:
        from modstore_server.workflow_customer_finalization import (
            finalize_returned_customer_workflow,
        )

        completed_customer = finalize_returned_customer_workflow(
            db, returned_customer, session_factory=sf
        )
    elif failed_execution is None:
        complete_execution_feedback(db, execution)
        db.commit()

    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import (
            WORKFLOW_EXECUTION_COMPLETED,
            WORKFLOW_EXECUTION_FAILED,
        )

        event_name = (
            WORKFLOW_EXECUTION_FAILED
            if failed_execution is not None
            else WORKFLOW_EXECUTION_COMPLETED
        )
        if failed_execution is not None:
            event_data = {**failed_execution, "error": public_failure_message}
        elif completed_customer is not None:
            event_data = {
                "workflow_id": workflow_id,
                "execution_id": execution_id,
                "user_id": owner_user_id,
                "status": completed_customer["status"],
                "error": "",
                "started_at": completed_customer["started_at"],
                "completed_at": completed_customer["completed_at"],
            }
        else:
            event_data = {
                "workflow_id": int(workflow_id),
                "execution_id": int(execution.id),
                "user_id": int(user.id),
                "status": execution.status,
                "error": public_failure_message,
                "started_at": execution.started_at.isoformat(),
                "completed_at": (
                    execution.completed_at.isoformat() if execution.completed_at else ""
                ),
            }
        webhook_dispatcher.publish_event(
            event_name,
            aggregate_id=str(execution_id),
            data=event_data,
            source="modstore-workflow-api",
        )
    except RECOVERABLE_ERRORS:
        pass

    if failure_message is not None:
        raise HTTPException(500, public_failure_message)

    if completed_customer is not None:
        return completed_customer
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": json.loads(execution.input_data),
        "output_data": json.loads(execution.output_data or "{}"),
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


@router.get("/{workflow_id}/executions", summary="获取工作流执行记录")
async def get_workflow_executions(
    workflow_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = _DB_SESSION,
    user: User = _CURRENT_USER,
):
    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    executions = (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return [
        {
            "id": e.id,
            "status": e.status,
            "input_data": json.loads(e.input_data or "{}"),
            "output_data": json.loads(e.output_data or "{}"),
            "error_message": e.error_message,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
        }
        for e in executions
    ]


@router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(
    execution_id: int,
    db: Session = _DB_SESSION,
    user: User = _CURRENT_USER,
):
    execution = (
        db.query(WorkflowExecution)
        .join(Workflow)
        .filter(
            WorkflowExecution.id == execution_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(404, "执行记录不存在")

    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": json.loads(execution.input_data or "{}"),
        "output_data": json.loads(execution.output_data or "{}"),
        "error_message": execution.error_message,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }
