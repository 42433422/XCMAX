"""工作流触发执行：供 Cron / 公开 Webhook / NeuroBus 事件共用（配额一致）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from modstore_server.models import Workflow, WorkflowExecution, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_engine import execute_workflow
from modstore_server.workflow_sandbox_state import (
    GRAPH_GUARD_FAILED,
    workflow_graph_fingerprint,
)


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

    with get_session_factory()() as db:
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
        binding: dict[str, Any] = {}
        output: dict[str, Any]
        try:
            binding = begin_execution_feedback(db, execution) or {}
            db.commit()
            if binding.get("blocked"):
                raise ValueError(binding["blocked"])
            graph_guard: dict[str, Any] = (
                {"expected_graph_fingerprint": binding["graph_fingerprint"]} if binding else {}
            )
            if binding.get("customer_delivery"):
                graph_guard["execution_id"] = int(execution.id)
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
            db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution.id)
                .values(
                    status="failed",
                    error_message=str(exc),
                    completed_at=datetime.now(UTC),
                    output_data=json.dumps(getattr(exc, "evidence", {}), ensure_ascii=False),
                )
            )
            db.refresh(execution)
            complete_execution_feedback(db, execution)
            db.commit()
            if real_sandbox and (binding.get("blocked") or str(exc) == GRAPH_GUARD_FAILED):
                return {
                    "ok": False,
                    "validate_only": False,
                    "errors": [str(exc)],
                    "warnings": [],
                    "steps": [],
                    "output": {},
                }
            raise
        failed = real_sandbox and output.get("ok") is not True
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
                output_data=json.dumps(output, ensure_ascii=False),
                completed_at=datetime.now(UTC),
            )
        )
        db.refresh(execution)
        complete_execution_feedback(db, execution)
        db.commit()
    return output
