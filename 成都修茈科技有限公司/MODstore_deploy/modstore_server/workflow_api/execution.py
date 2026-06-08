from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowExecution,
    get_session_factory,
)
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_api.schemas import WorkflowExecuteBody

router = APIRouter()


@router.post("/{workflow_id}/execute", summary="执行工作流")
async def execute_workflow(
    workflow_id: int,
    body: WorkflowExecuteBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
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

    execution = WorkflowExecution(
        workflow_id=workflow_id,
        user_id=user.id,
        status="running",
        input_data=json.dumps(body.input_data or {}),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    sf = get_session_factory()
    with sf() as qdb:
        require_llm_credit(qdb, user.id, 1)
    failure_message: Optional[str] = None
    try:
        output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)
        execution.status = "completed"
        execution.output_data = json.dumps(output_data)
        execution.completed_at = datetime.now(timezone.utc)
        try:
            with sf() as qdb2:
                consume_llm_credit(qdb2, user.id, 1)
        except Exception:
            pass
    except Exception as e:
        failure_message = str(e)
        execution.status = "failed"
        execution.error_message = failure_message
        execution.completed_at = datetime.now(timezone.utc)
    db.commit()

    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import (
            WORKFLOW_EXECUTION_COMPLETED,
            WORKFLOW_EXECUTION_FAILED,
        )

        event_name = WORKFLOW_EXECUTION_FAILED if failure_message else WORKFLOW_EXECUTION_COMPLETED
        webhook_dispatcher.publish_event(
            event_name,
            aggregate_id=str(execution.id),
            data={
                "workflow_id": int(workflow_id),
                "execution_id": int(execution.id),
                "user_id": int(user.id),
                "status": execution.status,
                "error": failure_message or "",
                "started_at": execution.started_at.isoformat(),
                "completed_at": (
                    execution.completed_at.isoformat() if execution.completed_at else ""
                ),
            },
            source="modstore-workflow-api",
        )
    except Exception:
        pass

    if failure_message is not None:
        raise HTTPException(500, failure_message)

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
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
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
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
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
