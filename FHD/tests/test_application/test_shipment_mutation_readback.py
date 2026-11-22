"""Real shipment updates/deletes retain exact claims and read current tenant state."""

import copy
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.result_verification import verify_step_result
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import _idempotency_path
from app.application.shipment_app_service import ShipmentApplicationService
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models.permission import Role
from app.db.models.shipment import ShipmentRecord
from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_onboarding_seed_app_service import (
    verified_shipment as verified_shipment,
)


@pytest.fixture(params=["update", "delete"])
def mutation(verified_shipment, monkeypatch, request):
    actor, created = verified_shipment
    record_id = created.tool_calls[0].output["shipment"]["id"]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        row = db.get(ShipmentRecord, record_id)
        original = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    params = {"id": record_id}
    if request.param == "update":
        params.update(status="printed", quantity_kg=9.5, amount=27.5, date="2026-11-21")
    service = AgentOrchestrator(
        repository=InMemoryAgentRunRepository(),
        tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    run = service.start_run_from_plan(
        user_id=str(actor.user_id),
        message="Mutate the original tenant shipment",
        runtime_context=actor.context,
        plan=PlanGraph(
            plan_id="shipment-mutation",
            intent="shipment_mutation",
            nodes=[
                WorkflowNode(
                    node_id="mutation",
                    tool_id="shipment_records",
                    action=request.param,
                    params=params,
                )
            ],
        ),
    )
    assert run.status == "waiting_user" and not run.tool_calls
    run = service.continue_run(run.run_id, approved_by=str(actor.user_id))
    assert run.status == "completed", run.to_dict()
    assert run.tool_calls[0].metadata["verification"]["accepted"] is True
    for method in ("update_shipment_record", "delete_shipment_record"):
        monkeypatch.setattr(
            ShipmentApplicationService,
            method,
            lambda *_a, **_k: pytest.fail("Verification must never repeat a shipment mutation"),
        )
    return actor, run, original


@pytest.mark.parametrize("change", [None, "receipt", "state", "permission"])
def test_mutation_readback_requires_original_claim_and_current_state(mutation, change):
    actor, run, original = mutation
    step, call = run.steps[0], run.tool_calls[0]
    raw_output = copy.deepcopy(call.output)
    if change == "receipt":
        with sqlite3.connect(_idempotency_path(create_parent=False)) as db:
            db.execute("DELETE FROM tool_idempotency")
    elif change:
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            if change == "permission":
                role = db.query(Role).filter_by(name="admin").one()
                role.permissions = [p for p in role.permissions if p.code != "shipment.view"]
            elif step.action == "delete":
                db.add(ShipmentRecord(**original))
            else:
                db.get(ShipmentRecord, original["id"]).amount = 999
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            report = verify_step_result(
                run=run,
                step=step,
                call=call,
                context={
                    **run.metadata["runtime_context"],
                    **task_execution_context(run, step),
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                },
            )
            assert report["accepted"] is (change is None), report
            assert report["code"] != "verification_binding_invalid"
        assert writes == [] and call.output == raw_output and len(run.tool_calls) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("mutation", ["delete"], indirect=True)
def test_deleted_shipment_requires_its_own_tenant_fingerprints_to_be_absent(mutation):
    actor, run, original = mutation
    with actor.factory.begin() as db:
        db.add(
            ShipmentEltImportFingerprint(
                tenant_key=f"tenant:{actor.tenant_id}",
                fingerprint="retained-original-import",
                shipment_id=original["id"],
            )
        )
    step, call = run.steps[0], run.tool_calls[0]
    report = verify_step_result(
        run=run,
        step=step,
        call=call,
        context={
            **run.metadata["runtime_context"],
            **task_execution_context(run, step),
            "run_id": run.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
        },
    )
    assert report["accepted"] is False
    assert report["code"] == "result_shipment_fingerprint_retained"
