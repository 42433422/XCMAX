"""Persist the returned original graph before its terminal transaction or recovery.

Node PRODUCED receipts alone never authorize completion after a restart.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable, cast

from sqlalchemy import String
from sqlalchemy import cast as sql_cast
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from modstore_server.eventing.db_outbox import enqueue
from modstore_server.models import (
    OutboxEvent,
    WorkflowExecution,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.strategic_portfolio import digest
from modstore_server.workflow_customer_delivery import (
    _event,
    _native_artifacts,
    _stored_contract,
    delivery_nodes,
    load_produced_delivery,
)

RETURNED_EVENT = "workflow.customer.graph_returned"


@dataclass(frozen=True)
class ReturnedCustomerWorkflow:
    """Only constructed after the real graph returned and JSON encoding succeeded."""

    execution_id: int
    workflow_id: int
    user_id: int
    started_at: datetime
    input_json: str
    graph_fingerprint: str
    output_json: str
    completed_at: datetime


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _original_delivery(
    db: Session, returned: ReturnedCustomerWorkflow, *, verify_files: bool = True
) -> Any:
    execution, binding, contract = _stored_contract(db, returned.execution_id)
    if (
        execution.user_id != returned.user_id
        or execution.workflow_id != returned.workflow_id
        or _utc(execution.started_at) != _utc(returned.started_at)
        or execution.input_data != returned.input_json
        or binding.get("graph_fingerprint") != returned.graph_fingerprint
        or (binding.get("assignment") or {}).get("measurement_scope")
        != WORKFLOW_CUSTOMER_MEASUREMENT
    ):
        raise ValueError("customer finalization does not own the original execution")
    produced = load_produced_delivery(db, contract, verify_files=verify_files)
    results = produced.get("nodes") or [produced]
    output = json.loads(returned.output_json)
    snapshots = output.get("nodes") if isinstance(output, dict) else None
    graph = db.scalars(
        select(WorkflowNode).where(WorkflowNode.workflow_id == returned.workflow_id)
    ).all()
    if not isinstance(snapshots, dict):
        raise ValueError("customer finalization has no returned graph nodes")
    for node in graph:
        saved = snapshots.get(str(node.id)) or {}
        if any(
            saved.get(key) != value
            for key, value in {
                "id": node.id,
                "name": node.name,
                "type": node.node_type,
            }.items()
        ) or not isinstance(saved.get("output"), dict):
            raise ValueError("customer finalization did not return every original graph node")
        if node.node_type == "end" and snapshots.get("prev") != saved:
            raise ValueError("customer finalization did not return the original end node")
    for delivery, result in zip(delivery_nodes(contract), results, strict=True):
        saved = snapshots[str(delivery["node_id"])]["output"]
        if (
            saved.get("employee_id") != delivery["employee_id"]
            or saved.get("task") != delivery["task"]
            or digest(saved.get("employee_result")) != result.get("native_result_sha256")
            or ("node_output" in result and saved != result["node_output"])
            or _native_artifacts(delivery, saved.get("employee_result"), verify_files=False)
            != [
                {key: value for key, value in artifact.items() if key != "storage"}
                for artifact in result.get("artifacts", [])
            ]
            or _utc(datetime.fromisoformat(result["completed_at"])) > _utc(returned.completed_at)
        ):
            raise ValueError("customer finalization has no matching returned native result")
    return execution


def _returned_payload(db: Session, returned: ReturnedCustomerWorkflow) -> dict[str, Any]:
    execution = _original_delivery(db, returned)
    if execution.status != "running" or execution.completed_at is not None:
        raise ValueError("customer finalization cannot replace an existing terminal")
    _execution, _binding, contract = _stored_contract(db, returned.execution_id)
    payload = {
        "protocol": "workflow.customer.graph-return.v1",
        "contract_sha256": contract["contract_sha256"],
        **asdict(returned),
        "started_at": _utc(returned.started_at).isoformat(),
        "completed_at": _utc(returned.completed_at).isoformat(),
    }
    return {**payload, "receipt_sha256": digest(payload)}


def _persist_return(db: Session, returned: ReturnedCustomerWorkflow) -> None:
    payload = _returned_payload(db, returned)
    event_id = f"{RETURNED_EVENT}:{returned.execution_id}"
    enqueue(db, RETURNED_EVENT, str(returned.execution_id), payload, event_id=event_id)
    event = _event(db, event_id)
    if event is None or json.loads(event.payload_json) != payload:
        raise ValueError("customer finalization already has a different graph return")
    db.commit()


def _load_return(db: Session, execution_id: int) -> ReturnedCustomerWorkflow:
    event = _event(db, f"{RETURNED_EVENT}:{execution_id}")
    if (
        event is None
        or event.event_name != RETURNED_EVENT
        or event.aggregate_id != str(execution_id)
        or event.producer != "modstore-python"
    ):
        raise ValueError("customer workflow has no original durable graph return")
    payload = json.loads(event.payload_json)
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    _execution, _binding, contract = _stored_contract(db, execution_id)
    if (
        payload.get("protocol") != "workflow.customer.graph-return.v1"
        or payload.get("receipt_sha256") != digest(unsigned)
        or payload.get("contract_sha256") != contract["contract_sha256"]
        or payload.get("execution_id") != execution_id
    ):
        raise ValueError("customer workflow durable graph return changed")
    fields = {key: payload[key] for key in ReturnedCustomerWorkflow.__dataclass_fields__}
    for key in ("started_at", "completed_at"):
        fields[key] = datetime.fromisoformat(fields[key])
    return ReturnedCustomerWorkflow(**fields)


def _snapshot(execution: Any) -> dict[str, Any]:
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "input_data": json.loads(execution.input_data),
        "output_data": json.loads(execution.output_data),
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat(),
    }


def _write_terminal(
    db: Session, returned: ReturnedCustomerWorkflow, *, recovering: bool
) -> dict[str, Any]:
    from modstore_server.workflow_execution_feedback import complete_execution_feedback

    if _load_return(db, returned.execution_id) != ReturnedCustomerWorkflow(
        **{
            **asdict(returned),
            "started_at": _utc(returned.started_at),
            "completed_at": _utc(returned.completed_at),
        }
    ):
        raise ValueError("customer finalization differs from its durable graph return")
    execution = _original_delivery(db, returned)
    if recovering and execution.status == "completed":
        if (
            execution.output_data == returned.output_json
            and execution.error_message in (None, "")
            and execution.completed_at is not None
            and _utc(execution.completed_at) == _utc(returned.completed_at)
        ):
            return _snapshot(execution)  # Prior COMMIT succeeded; do not repeat feedback or COMMIT.
        raise ValueError("customer finalization found a different existing terminal")
    updated = db.execute(
        update(WorkflowExecution)
        .where(
            WorkflowExecution.id == returned.execution_id,
            WorkflowExecution.user_id == returned.user_id,
            WorkflowExecution.workflow_id == returned.workflow_id,
            WorkflowExecution.started_at == returned.started_at,
            WorkflowExecution.input_data == returned.input_json,
            WorkflowExecution.status == "running",
            WorkflowExecution.completed_at.is_(None),
        )
        .values(
            status="completed",
            error_message=None,
            output_data=returned.output_json,
            completed_at=returned.completed_at,
        )
    )
    if cast(CursorResult[Any], updated).rowcount != 1:
        raise ValueError("customer finalization cannot replace an existing terminal")
    db.refresh(execution)
    complete_execution_feedback(db, execution)
    snapshot = _snapshot(execution)
    db.commit()
    return snapshot


def finalize_returned_customer_workflow(
    db: Session,
    returned: ReturnedCustomerWorkflow,
    *,
    session_factory: Callable[[], Session],
) -> dict[str, Any]:
    """Commit the actual graph return, then retry only its original terminal write."""
    try:
        _persist_return(db, returned)
        return _write_terminal(db, returned, recovering=False)
    except SQLAlchemyError as original:
        try:
            db.rollback()
            with session_factory() as recovery_db:
                if _event(recovery_db, f"{RETURNED_EVENT}:{returned.execution_id}") is None:
                    _persist_return(recovery_db, returned)
                return _write_terminal(recovery_db, returned, recovering=True)
        except RECOVERABLE_ERRORS as recovery_error:
            raise original from recovery_error


def recover_returned_customer_workflows(
    *,
    limit: int = 100,
    after: int = 0,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    """Resume durable graph returns without invoking any employee, graph or billing."""
    factory = session_factory or get_session_factory()
    limit = max(1, min(int(limit), 1000))
    with factory() as db:
        rows = db.execute(
            select(OutboxEvent.id, WorkflowExecution.id)
            .join(
                WorkflowExecution,
                OutboxEvent.aggregate_id == sql_cast(WorkflowExecution.id, String),
            )
            .where(
                OutboxEvent.event_name == RETURNED_EVENT,
                OutboxEvent.id > after,
                WorkflowExecution.status == "running",
                WorkflowExecution.completed_at.is_(None),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
        ).all()
    result = {
        "checked": len(rows),
        "completed": 0,
        "blocked": 0,
        "next_cursor": int(rows[-1][0]) if len(rows) == limit else 0,
    }
    for _event_id, execution_id in rows:
        try:
            with factory() as db:
                returned = _load_return(db, int(execution_id))
                _write_terminal(db, returned, recovering=True)
            result["completed"] += 1
        except RECOVERABLE_ERRORS:
            result["blocked"] += 1
    return result
