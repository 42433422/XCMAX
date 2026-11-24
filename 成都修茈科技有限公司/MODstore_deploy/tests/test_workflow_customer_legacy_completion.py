"""Read actual pre-upgrade completions without promoting unfinished old deliveries.

The golden rows were captured by running the original delivery/finalizer sources
at 4b55ade (source hashes recorded in the fixture) with the real archived CSV
employee, original workflow runner, and customer receipt APIs. No new-protocol
fields are deleted to manufacture legacy records. Only its temporary workspace
and the resulting contract identity are rebound to this test's own directory.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import DateTime, create_engine
from sqlalchemy import event as sql_event
from sqlalchemy.orm import sessionmaker

from modstore_server import customer_value_lifecycle_api as customer_api
from modstore_server import workflow_customer_delivery as delivery
from modstore_server import workflow_customer_delivery_api as delivery_api
from modstore_server import workflow_customer_feedback as feedback
from modstore_server import workflow_customer_finalization as finalization
from modstore_server.db import db_base
from modstore_server.models import (
    CustomerValueReceipt,
    OutboxEvent,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from modstore_server.strategic_portfolio import digest
from tests import test_workflow_customer_delivery as original

experiment_run = original.experiment_run
workflow_experiment = original.workflow_experiment
execution_experiment = original.execution_experiment
customer_workflow = original.customer_workflow


@pytest.fixture
def legacy_completion(tmp_path, monkeypatch):
    path = Path(__file__).with_name("fixtures") / "workflow_customer_legacy_completed.json"
    raw = path.read_text()
    captured = json.loads(raw)
    assert captured["provenance"]["commit"] == "4b55ade7e56106d12dd472ed9e9f9dd889799976"
    workspace = tmp_path / "workspaces" / str(captured["user"]["id"])
    rows = json.loads(raw.replace(captured["workspace"], str(workspace)))
    binding = json.loads(rows["events"][0]["payload_json"])
    contract = binding["customer_delivery"]
    contract["execution_binding"]["input_sha256"] = digest(contract["input_data"])
    contract["contract_sha256"] = digest(
        {key: value for key, value in contract.items() if key != "contract_sha256"}
    )
    for event in rows["events"]:
        payload = json.loads(event["payload_json"])
        if event["event_name"] == delivery.START_EVENT:
            payload = binding
        else:
            payload["contract_sha256"] = contract["contract_sha256"]
        event["payload_json"] = json.dumps(payload)
    produced = json.loads(rows["events"][-1]["payload_json"])
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    @sql_event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(engine, expire_on_commit=False)
    models = (
        (User, "user"),
        (Workflow, "workflow"),
        (WorkflowNode, "nodes"),
        (WorkflowEdge, "edges"),
        (WorkflowExecution, "execution"),
        (OutboxEvent, "events"),
        (CustomerValueReceipt, "customer_receipts"),
    )
    for model, _key in models:
        model.__table__.create(engine)
    with factory() as db:
        for model, key in models:
            records = rows[key] if isinstance(rows[key], list) else [rows[key]]
            for record in records:
                for column in model.__table__.columns:
                    if isinstance(column.type, DateTime) and column.name in record:
                        record[column.name] = datetime.fromisoformat(record[column.name])
                db.add(model(**record))
            db.flush()  # Honor original FKs even without ORM relationship cascades.
        db.commit()
        user = db.get(User, rows["user"]["id"])
    artifact = produced["artifacts"][0]
    output = workspace / artifact["output_path"]
    output.parent.mkdir(parents=True)
    content = base64.b64decode(rows["artifact_base64"])
    output.write_bytes(content)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "workspaces" / "{user_id}"))
    monkeypatch.setattr(db_base, "get_session_factory", lambda: factory)
    monkeypatch.setattr(delivery_api, "get_session_factory", lambda: factory)

    def original_payment(order_no, user_id):
        assert (order_no, user_id) == (rows["order"]["out_trade_no"], user.id)
        return rows["order"]

    monkeypatch.setattr(customer_api, "_authoritative_order", original_payment)
    yield SimpleNamespace(
        factory=factory,
        binding=binding,
        contract=contract,
        produced=produced,
        execution_id=rows["execution"]["id"],
        user=user,
        order=rows["order"],
        output=output,
        content=content,
        artifact=artifact,
    )
    engine.dispose()


def _download(state):
    return delivery_api.download_workflow_delivery(
        state.user,
        execution_id=state.execution_id,
        artifact_id=state.artifact["artifact_id"],
        order_no=state.contract["goal"]["order_no"],
        goal_id=state.contract["goal"]["customer_goal_id"],
    )


def test_actual_old_completed_output_and_original_receipts_remain_historical(
    legacy_completion,
):
    state = legacy_completion
    with state.factory() as db:
        assert delivery.load_completed_delivery(db, state.execution_id) == (
            state.binding,
            state.produced,
        )
        assert delivery._event(db, f"{finalization.RETURNED_EVENT}:{state.execution_id}") is None
        execution = db.get(WorkflowExecution, state.execution_id)
        due = datetime.fromisoformat(state.binding["customer_outcome_due_at"])
        measured = feedback._measured(db, execution, state.binding, due)
        assert measured[0] is True
    assert _download(state).body == state.content
    state.output.write_bytes(b"later execution overwrote the shared output path")
    with state.factory() as db:
        assert delivery.load_completed_delivery(db, state.execution_id) == (
            state.binding,
            state.produced,
        )
        assert (
            feedback._measured(
                db, db.get(WorkflowExecution, state.execution_id), state.binding, due
            )
            == measured
        )
    with pytest.raises(HTTPException) as download:
        _download(state)
    assert download.value.status_code == 409
    with pytest.raises(HTTPException) as receipt:
        delivery_api.validate_workflow_receipt(
            order=state.order,
            goal_id=state.contract["goal"]["customer_goal_id"],
            artifact_id=state.artifact["artifact_id"],
            artifact_sha256=state.artifact["artifact_sha256"],
            occurred_at=due.astimezone(UTC),
        )
    assert receipt.value.status_code == 409


@pytest.mark.parametrize("status", ["running", "failed"])
def test_original_produced_only_never_completes_an_old_unfinished_run(legacy_completion, status):
    state = legacy_completion
    with state.factory() as db:
        execution = db.get(WorkflowExecution, state.execution_id)
        returned = finalization._legacy_completed_return(
            db, execution, state.binding, state.contract, state.produced
        )
        execution.status = status
        execution.output_data = "{}"
        execution.completed_at = None
        db.commit()
        with pytest.raises(ValueError):
            delivery.load_completed_delivery(db, execution.id)
        with pytest.raises(ValueError):
            finalization.finalize_returned_customer_workflow(
                db, returned, session_factory=state.factory
            )
        db.rollback()
    assert finalization.recover_returned_customer_workflows(session_factory=state.factory) == {
        "checked": 0,
        "completed": 0,
        "blocked": 0,
        "next_cursor": 0,
    }
    with state.factory() as db:
        execution = db.get(WorkflowExecution, state.execution_id)
        assert execution.status == status and execution.output_data == "{}"
        assert execution.completed_at is None
        assert delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution.id}") is None


@pytest.mark.parametrize(
    "changed",
    [
        "missing_output",
        "missing_end",
        "native_result",
        "produced_hash",
        "produced_after_completion",
        "claim",
        "producer",
        "foreign_user",
        "error",
        "native_digest_key",
        "unexpected_return",
    ],
)
def test_legacy_history_requires_original_output_and_bound_native_receipts(
    legacy_completion, changed
):
    state = legacy_completion
    with state.factory() as db:
        execution = db.get(WorkflowExecution, state.execution_id)
        produced = delivery._event(
            db, f"{delivery.PRODUCED_EVENT}:{execution.id}:{state.contract['node_id']}"
        )
        payload = json.loads(produced.payload_json)
        output = json.loads(execution.output_data)
        if changed == "missing_output":
            output = {}
        elif changed == "missing_end":
            del output["nodes"][str(output["nodes"]["prev"]["id"])]
        elif changed == "native_result":
            output["nodes"][str(state.contract["node_id"])]["output"]["employee_result"] = {
                "ok": False
            }
        elif changed == "produced_hash":
            payload["artifacts"][0]["artifact_sha256"] = "f" * 64
        elif changed == "produced_after_completion":
            payload["completed_at"] = (execution.completed_at + timedelta(seconds=1)).isoformat()
        elif changed == "claim":
            claim = delivery._event(
                db, f"{delivery.CLAIM_EVENT}:{execution.id}:{state.contract['node_id']}"
            )
            claim.payload_json = "{}"
        elif changed == "producer":
            produced.producer = "foreign-workflow"
        elif changed == "foreign_user":
            db.add(
                User(
                    id=execution.user_id + 1,
                    username="other-customer",
                    password_hash="test-only",
                    is_enterprise=True,
                )
            )
            db.flush()
            execution.user_id += 1
        elif changed == "error":
            execution.error_message = "original graph failed"
        elif changed == "native_digest_key":
            payload["native_result_sha256"] = None
        elif changed == "unexpected_return":
            db.add(
                OutboxEvent(
                    event_id=f"{finalization.RETURNED_EVENT}:{execution.id}",
                    event_name=finalization.RETURNED_EVENT,
                    aggregate_id=str(execution.id),
                    producer="modstore-python",
                    payload_json="{}",
                )
            )
        produced.payload_json = json.dumps(payload)
        execution.output_data = json.dumps(output)
        db.commit()
        with pytest.raises(ValueError):
            delivery.load_completed_delivery(db, state.execution_id)


@pytest.mark.parametrize(
    "changed",
    [
        "missing_return",
        "missing_return_and_digest",
        "contract_marker_removed",
        "producer_marker_removed",
        "both_markers_removed",
        "empty_marker",
        "return_without_native_digest",
    ],
)
def test_new_protocol_cannot_downgrade_when_original_evidence_is_removed(
    customer_workflow, changed
):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    with delivery.get_session_factory()() as db:
        execution_id = env["execution_id"]
        started = delivery._event(db, f"{delivery.START_EVENT}:{execution_id}")
        binding = json.loads(started.payload_json)
        contract = binding["customer_delivery"]
        produced = delivery._event(
            db, f"{delivery.PRODUCED_EVENT}:{execution_id}:{contract['node_id']}"
        )
        payload = json.loads(produced.payload_json)
        returned = delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution_id}")
        assert (
            contract["completion_protocol"]
            == payload["completion_protocol"]
            == delivery.COMPLETION_PROTOCOL
        )
        if changed != "return_without_native_digest":
            db.delete(returned)
        if changed in {
            "missing_return_and_digest",
            "return_without_native_digest",
            "producer_marker_removed",
        }:
            del payload["native_result_sha256"]
        if changed in {"contract_marker_removed", "both_markers_removed"}:
            del contract["completion_protocol"]
        if changed in {"producer_marker_removed", "both_markers_removed"}:
            del payload["completion_protocol"]
        if changed == "empty_marker":
            contract["completion_protocol"] = payload["completion_protocol"] = ""
        # Even a rehashed contract and matching node claim cannot erase the
        # independent producer marker/digest or substitute for the graph return.
        contract["contract_sha256"] = digest(
            {key: value for key, value in contract.items() if key != "contract_sha256"}
        )
        claim = delivery._event(db, f"{delivery.CLAIM_EVENT}:{execution_id}:{contract['node_id']}")
        claim_payload = json.loads(claim.payload_json)
        claim_payload["contract_sha256"] = payload["contract_sha256"] = contract["contract_sha256"]
        started.payload_json = json.dumps(binding)
        claim.payload_json = json.dumps(claim_payload)
        produced.payload_json = json.dumps(payload)
        db.commit()
        with pytest.raises(ValueError):
            delivery.load_completed_delivery(db, execution_id)
