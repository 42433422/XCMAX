"""Finish one already-returned customer graph after a terminal SQL failure.

This is an in-process consumer of the caller's actual, serialized graph result.
The native PRODUCED event alone never authorizes completion after a restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from modstore_server.models import WorkflowExecution
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.strategic_portfolio import digest
from modstore_server.workflow_customer_delivery import (
    ARTIFACT_SOURCE,
    CLAIM_EVENT,
    PRODUCED_EVENT,
    START_EVENT,
    _event,
    _stored_contract,
    read_artifact_bytes,
)


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


def _original_delivery(db: Session, returned: ReturnedCustomerWorkflow) -> Any:
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
    identity = {
        key: contract[key]
        for key in ("execution_id", "workflow_id", "user_id", "node_id", "contract_sha256")
    }
    records = {}
    for name in (START_EVENT, CLAIM_EVENT, PRODUCED_EVENT):
        suffix = str(returned.execution_id)
        if name != START_EVENT:
            suffix += f":{contract['node_id']}"
        row = _event(db, f"{name}:{suffix}")
        if (
            row is None
            or row.event_name != name
            or row.aggregate_id != str(returned.execution_id)
            or row.producer != "modstore-python"
        ):
            raise ValueError("customer finalization requires its original native receipts")
        records[name] = json.loads(row.payload_json)
    if records[CLAIM_EVENT] != {
        key: identity[key] for key in ("execution_id", "node_id", "contract_sha256")
    }:
        raise ValueError("customer finalization claim no longer matches its contract")
    produced = records[PRODUCED_EVENT]
    if (
        any(produced.get(key) != value for key, value in identity.items())
        or not isinstance(produced.get("artifacts"), list)
        or not produced["artifacts"]
        or _utc(datetime.fromisoformat(produced["completed_at"])) > _utc(returned.completed_at)
    ):
        raise ValueError("customer finalization has no matching completed native delivery")
    artifacts = set()
    for artifact in produced["artifacts"]:
        expected = (
            f"workflow-file-{returned.execution_id}-{contract['node_id']}-"
            + digest(artifact["output_path"])[:24]
        )
        if (
            artifact.get("artifact_id") != expected
            or artifact.get("source") != ARTIFACT_SOURCE
            or expected in artifacts
        ):
            raise ValueError("customer finalization artifact identity changed")
        read_artifact_bytes(contract, artifact)
        artifacts.add(expected)
    return execution


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
    """Retry only the original terminal transaction once, never business execution."""
    try:
        return _write_terminal(db, returned, recovering=False)
    except SQLAlchemyError as original:
        try:
            db.rollback()
            with session_factory() as recovery_db:
                return _write_terminal(recovery_db, returned, recovering=True)
        except RECOVERABLE_ERRORS as recovery_error:
            raise original from recovery_error
