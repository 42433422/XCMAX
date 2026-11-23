"""工作流触发执行：供 Cron / 公开 Webhook / NeuroBus 事件共用（配额一致）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from modstore_server.models import Workflow, WorkflowExecution, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_engine import execute_workflow
from modstore_server.workflow_sandbox_state import (
    GRAPH_GUARD_FAILED,
    workflow_graph_fingerprint,
)


def _failure_snapshot(execution: Any) -> dict[str, Any]:
    return {
        "execution_id": int(execution.id),
        "workflow_id": int(execution.workflow_id),
        "user_id": int(execution.user_id),
        "status": execution.status,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else "",
    }


def persist_workflow_failure(
    *,
    session_factory: Callable[[], Session],
    execution_id: int,
    workflow_id: int,
    user_id: int,
    started_at: datetime,
    error: Exception,
    completed_at: datetime,
) -> tuple[bool, dict[str, Any] | None]:
    """After caller rollback, finish only its original durable running identity."""
    from modstore_server.workflow_execution_feedback import complete_execution_feedback

    identity = (
        WorkflowExecution.id == execution_id,
        WorkflowExecution.workflow_id == workflow_id,
        WorkflowExecution.user_id == user_id,
        WorkflowExecution.started_at == started_at,
    )
    error_message = str(error)
    output_json = json.dumps(getattr(error, "evidence", {}), ensure_ascii=False)
    try:
        with session_factory() as terminal_db:
            updated = terminal_db.execute(
                update(WorkflowExecution)
                .where(
                    *identity,
                    WorkflowExecution.status == "running",
                    WorkflowExecution.completed_at.is_(None),
                )
                .values(
                    status="failed",
                    error_message=error_message,
                    completed_at=completed_at,
                    output_data=output_json,
                )
            )
            if cast(CursorResult[Any], updated).rowcount != 1:
                existing = terminal_db.query(WorkflowExecution).filter(*identity).one_or_none()
                return False, _failure_snapshot(existing) if existing is not None else None
            terminal = terminal_db.query(WorkflowExecution).filter(*identity).one()
            complete_execution_feedback(terminal_db, terminal)
            snapshot = _failure_snapshot(terminal)
            terminal_db.commit()
            return True, snapshot
    except SQLAlchemyError as recording_error:
        # A lost terminal COMMIT response is resolved by exact readback only.
        # Never repeat feedback, invent a missing run, or overwrite another terminal.
        try:
            with session_factory() as read_db:
                confirmed = (
                    read_db.query(WorkflowExecution)
                    .filter(
                        *identity,
                        WorkflowExecution.status == "failed",
                        WorkflowExecution.error_message == error_message,
                        WorkflowExecution.output_data == output_json,
                        WorkflowExecution.completed_at == completed_at,
                    )
                    .one_or_none()
                )
                if confirmed is not None:
                    return True, _failure_snapshot(confirmed)
        except RECOVERABLE_ERRORS as read_error:
            raise recording_error from read_error
        raise


def run_workflow_for_trigger(
    *, workflow_id: int, user_id: int, input_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """执行一次工作流并扣减 ``llm_calls`` 配额（与 ``workflow_scheduler`` 语义对齐）。"""
    sf = get_session_factory()
    with sf() as qdb:
        require_llm_credit(qdb, user_id, 1)
    output = run_recorded_workflow(workflow_id=workflow_id, user_id=user_id, input_data=input_data)
    with sf() as qdb2:
        consume_llm_credit(qdb2, user_id, 1)
    return {"ok": True, "result": output}


def run_recorded_workflow(
    *,
    workflow_id: int,
    user_id: int,
    input_data: dict[str, Any] | None = None,
    real_sandbox: bool = False,
) -> dict[str, Any]:
    """The actual run and experiment receipt; billing remains at each existing caller."""
    from modstore_server.workflow_execution_feedback import (
        begin_execution_feedback,
        complete_execution_feedback,
    )

    session_factory = get_session_factory()
    with session_factory() as db:
        workflow = db.get(Workflow, workflow_id)
        if (
            workflow is None
            or workflow.user_id != user_id
            or (not real_sandbox and not workflow.is_active)
        ):
            raise ValueError("工作流不存在、未激活或无权访问")
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            user_id=user_id,
            status="running",
            input_data=json.dumps(input_data or {}, ensure_ascii=False),
        )
        db.add(execution)
        db.flush()
        execution_id = int(execution.id)
        execution_started_at = cast(datetime, execution.started_at)
        execution_input_json = str(execution.input_data)
        start_commit_attempted = False
        binding: dict[str, Any] = {}
        output: dict[str, Any]
        try:
            binding = begin_execution_feedback(db, execution) or {}
            start_commit_attempted = True
            db.commit()
            if binding.get("blocked"):
                raise ValueError(binding["blocked"])
            graph_guard: dict[str, Any] = (
                {"expected_graph_fingerprint": binding["graph_fingerprint"]} if binding else {}
            )
            if binding.get("customer_delivery"):
                graph_guard["execution_id"] = execution_id
            if real_sandbox:
                from modstore_server.workflow_engine import workflow_engine

                if not graph_guard:
                    graph_guard = {
                        "expected_graph_fingerprint": workflow_graph_fingerprint(db, workflow_id)
                    }
                output = workflow_engine.run_sandbox(
                    db,
                    workflow,
                    input_data or {},
                    mock_employees=False,
                    validate_only=False,
                    user_id=user_id,
                    **graph_guard,
                )
                output["graph_fingerprint"] = graph_guard["expected_graph_fingerprint"]
            else:
                output = execute_workflow(
                    workflow_id,
                    input_data or {},
                    user_id=user_id,
                    **graph_guard,
                )
        except RECOVERABLE_ERRORS as exc:
            try:
                db.rollback()
                if start_commit_attempted:
                    persist_workflow_failure(
                        session_factory=session_factory,
                        execution_id=execution_id,
                        workflow_id=workflow_id,
                        user_id=user_id,
                        started_at=execution_started_at,
                        error=exc,
                        completed_at=datetime.now(UTC),
                    )
            except RECOVERABLE_ERRORS as recording_error:
                raise exc from recording_error
            public_guard = None
            if isinstance(exc, ValueError):
                if str(exc) == GRAPH_GUARD_FAILED:
                    public_guard = GRAPH_GUARD_FAILED
                elif (
                    str(exc)
                    == binding.get("blocked")
                    == "workflow_experiment_graph_no_longer_approved"
                ):
                    public_guard = "workflow_experiment_graph_no_longer_approved"
            if real_sandbox and public_guard is not None:
                return {
                    "ok": False,
                    "validate_only": False,
                    "errors": [public_guard],
                    "warnings": [],
                    "steps": [],
                    "output": {},
                }
            raise
        failed = real_sandbox and output.get("ok") is not True
        output_json = json.dumps(output, ensure_ascii=False)
        completed_at = datetime.now(UTC)
        if not real_sandbox and binding.get("customer_delivery") is True:
            from modstore_server.workflow_customer_finalization import (
                ReturnedCustomerWorkflow,
                finalize_returned_customer_workflow,
            )

            finalize_returned_customer_workflow(
                db,
                ReturnedCustomerWorkflow(
                    execution_id=execution_id,
                    workflow_id=workflow_id,
                    user_id=user_id,
                    started_at=execution_started_at,
                    input_json=execution_input_json,
                    graph_fingerprint=binding["graph_fingerprint"],
                    output_json=output_json,
                    completed_at=completed_at,
                ),
                session_factory=session_factory,
            )
            return output
        db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution.id)
            .values(
                status="failed" if failed else "completed",
                error_message=(
                    (
                        "; ".join(str(error) for error in output.get("errors", []))
                        or "workflow_sandbox_failed"
                    )
                    if failed
                    else None
                ),
                output_data=output_json,
                completed_at=completed_at,
            )
        )
        db.refresh(execution)
        complete_execution_feedback(db, execution)
        db.commit()
    return output
