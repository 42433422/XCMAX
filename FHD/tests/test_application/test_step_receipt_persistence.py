"""Committed synthetic effects and independent SQLite reads across optional sink failures."""

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_permission import _fingerprint, idempotency_scope_key
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.customer_creation_receipt import (
    customer_creation_claim,
    record_customer_creation,
)
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("failed_sink", [None, "artifacts", "observation"])
@pytest.mark.parametrize("result_state", ["completed", "unknown", "waiting_user"])
def test_receipt_is_durable_before_optional_sinks(
    monkeypatch, failed_sink, result_state, trusted_actor
):
    def no_network(*args, **kwargs):
        raise AssertionError("synthetic receipt tests prohibit network/model access")

    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("socket.create_connection", no_network)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.view", "customer.edit"])
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    engine = actor.factory.kw["bind"]
    path = engine.url.database
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE synthetic_effects(id INTEGER PRIMARY KEY, receipt TEXT)")
    step = AgentStep(
        "write",
        "customers",
        "create",
        params={"customer_name": "Receipt customer", "contact_phone": "123"},
    )
    run = AgentRun(
        user_id=str(actor.user_id),
        message="persist original receipt",
        steps=[step],
        metadata={"runtime_context": copy.deepcopy(actor.context)},
    )
    unknown = result_state == "unknown"
    receipt = {
        "success": not unknown,
        "receipt_id": "original-committed-effect",
        "artifacts": [{"artifact_id": "receipt-view", "artifact_type": "tool_result"}],
    }
    if unknown:
        receipt.update(outcome="unknown", retryable=False, reconciliation_required=True)
    elif result_state == "waiting_user":
        receipt.update(requires_user_decision=True, question="Continue with the proposed rows?")
    observed, dispatched = [], []

    def readback():
        with sqlite3.connect(path) as reopened:
            payload = json.loads(
                reopened.execute(
                    "SELECT payload_json FROM agent_runs WHERE run_id=?", (run.run_id,)
                ).fetchone()[0]
            )
            effects = reopened.execute("SELECT receipt FROM synthetic_effects").fetchall()
        assert effects == [(receipt["receipt_id"],)]
        stored_step, stored_call = payload["steps"][0], payload["tool_calls"][0]
        assert stored_call["status"] == ("failed" if unknown else "completed")
        assert stored_step["status"] == ("failed" if unknown else result_state)
        if result_state == "waiting_user":
            assert payload["status"] == "waiting_user"
        assert stored_step["output"] == stored_call["output"]
        assert stored_step["finished_at"] == stored_call["finished_at"] != ""
        assert stored_step["attempt_count"] == stored_call["metadata"]["attempt_count"] == 1
        if unknown:
            assert stored_step["output"]["reconciliation_evidence"] == receipt
            assert {key: stored_step["output"][key] for key in receipt} == receipt
            assert stored_step["output"].get("error_code") != "tool_timeout_unknown"
            assert payload["metadata"]["non_retryable"] is True
            assert payload["metadata"]["recovery"]["state"] == "manual_reconciliation_required"
        else:
            assert stored_step["output"] == receipt
        return payload

    def execute(*args, runtime_context, **kwargs):
        dispatched.append(1)
        key = idempotency_scope_key(runtime_context, step.tool_id, step.action, step.params)
        with tenant_scope(actor.tenant_id), actor.factory.begin() as business:
            business.connection().exec_driver_sql(
                "INSERT INTO synthetic_effects(receipt) VALUES(?)",
                (receipt["receipt_id"],),
            )
            customer = PurchaseUnit(
                tenant_id=actor.tenant_id, unit_name="Receipt customer", contact_phone="123"
            )
            business.add(customer)
            business.flush()
            with customer_creation_claim(key, _fingerprint(step.params), str(actor.tenant_id)):
                record_customer_creation(business, customer)
            receipt["id"] = customer.id
        return copy.deepcopy(receipt)

    def sink(name):
        def apply(*args, **kwargs):
            readback()  # The receipt must already be visible to another connection.
            observed.append(name)
            if failed_sink == name:
                raise RuntimeError(f"synthetic {name} failure after commit")
            return {"observation_id": "synthetic-observation"}

        return apply

    dependencies = SimpleNamespace(
        action_spec=lambda *_: ToolActionSpecV2("customers", "create", timeout_seconds=2),
        validate=lambda *_: SimpleNamespace(ok=True),
        refresh_budget=lambda _: None,
    )
    execution = StepExecution(
        repo,
        SimpleNamespace(execute_with_deadline=execute),
        RunUsageLedger(dependencies),
        dependencies,
        attach_artifacts=sink("artifacts"),
        observe=sink("observation"),
    )
    try:
        if failed_sink == "observation" or (failed_sink == "artifacts" and not unknown):
            with pytest.raises(RuntimeError, match=f"synthetic {failed_sink} failure"):
                execution.execute_step(run, step, runtime_context=actor.context, node_outputs={})
        else:
            execution.execute_step(run, step, runtime_context=actor.context, node_outputs={})
        persisted = readback()
        assert observed == (
            ["observation"]
            if unknown
            else ["artifacts"]
            if failed_sink == "artifacts"
            else ["artifacts", "observation"]
        )
        events = [event["event_type"] for event in persisted["events"]]
        if failed_sink is None or (failed_sink == "artifacts" and unknown):
            assert ("tool.failed" if unknown else "tool.completed") in events
        elif failed_sink == "observation":
            assert events == [
                "tool.started",
                "verification.failed" if unknown else "verification.verified",
            ]
        else:
            assert events == ["tool.started"]
        reopened_repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
        assert reopened_repo.get(run.run_id).to_dict() == persisted
        if not unknown:
            # A recovered projection sink may read the original transaction;
            # it must not create another business effect after its earlier failure.
            execution.attach_artifacts = sink("recovered-artifacts")
            restored = reopened_repo.get(run.run_id)
            execution.execute_step(
                restored, restored.steps[0], runtime_context=actor.context, node_outputs={}
            )
            assert restored.tool_calls[0].metadata["verification"]["status"] == "verified"
            assert restored.steps[0].attempt_count == 1
            assert len(restored.tool_calls) == 1
            readback()
        assert dispatched == [1]
    finally:
        engine.dispose()
