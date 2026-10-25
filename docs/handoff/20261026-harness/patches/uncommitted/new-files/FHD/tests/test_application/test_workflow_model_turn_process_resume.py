"""Two spawned workers compete for the same formally approved workflow cursor."""

import multiprocessing

from tests.test_application import test_workflow_model_turn as workflow_fixtures

trusted_actor = workflow_fixtures.trusted_actor
reviewed_agent_http = workflow_fixtures.reviewed_agent_http
workflow_model = workflow_fixtures.workflow_model


def _resume_workflow(url, run_id, owner, ready, start, outcomes):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as host_db
    from app.application.agent_orchestrator import run_repository, task_execution_repository
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository
    from tests.test_application.test_workflow_model_turn import json_model

    class Patches:
        @staticmethod
        def setattr(owner, name, value):
            setattr(owner, name, value)

    requests = json_model(Patches(), [{"action": "done"}])
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    host_db.HostSessionLocal = factory
    runs = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory, auto_create=False)
    run_repository._agent_run_repository = runs
    task_execution_repository._task_execution_repository = queue
    ready.put(owner)
    try:
        assert start.wait(25)
        execution = queue.claim_run(run_id, owner, lease_seconds=60)
        if execution is None:
            outcomes.put({"claimed": False, "requests": 0})
            return
        final = AgentOrchestrator(
            repository=ClaimedRunRepository(runs, execution, owner)
        ).execute_dispatched_run(run_id)
        queue.finish(run_id, owner, final.status, execution_count=execution.execution_count)
        outcomes.put(
            {
                "claimed": True,
                "status": final.status,
                "requests": len(requests),
                "calls": [call.call_id for call in final.tool_calls],
                "output": final.final_output,
            }
        )
    finally:
        engine.dispose()


def test_two_processes_continue_original_workflow_once(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    workflow_fixtures.json_model(
        monkeypatch,
        [
            {
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "workflow process customer"},
                },
            }
        ],
    )
    first = workflow_fixtures.run_workflow(actor, {"business_db": {"actions": {"write": {}}}})
    run = http.repository.get(first.final_context["run_id"])
    original_id = run.tool_calls[0].call_id
    review = http.client.get(f"/api/agent/runs/{run.run_id}")
    assert review.status_code == 200
    approved = http.client.post(
        f"/api/agent/runs/{run.run_id}/continue",
        json={"approval_grant": review.json()["approval"]["grant"]},
    )
    assert approved.status_code == 202, approved.text
    ctx = multiprocessing.get_context("spawn")
    ready, outcomes, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    workers = [
        ctx.Process(
            target=_resume_workflow,
            args=(str(actor.factory.kw["bind"].url), run.run_id, owner, ready, start, outcomes),
        )
        for owner in ("workflow-one", "workflow-two")
    ]
    try:
        for worker in workers:
            worker.start()
        assert {ready.get(timeout=25), ready.get(timeout=25)} == {"workflow-one", "workflow-two"}
        start.set()
        results = [outcomes.get(timeout=45), outcomes.get(timeout=45)]
        assert sorted(value["claimed"] for value in results) == [False, True]
        winner = next(value for value in results if value["claimed"])
        assert winner["status"] == "completed" and winner["requests"] == 1
        assert winner["calls"] == [original_id]
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        final = http.repository.get(run.run_id)
        assert final.metadata[STATE_KEY]["round"] == 2
        assert final.steps[0].attempt_count == 1
        assert final.tool_calls[0].metadata["independent_verification"]["verified"] is True
        with tenant_scope(actor.tenant_id), actor.factory() as db:
            assert (
                db.query(PurchaseUnit).filter_by(unit_name="workflow process customer").count() == 1
            )
    finally:
        start.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        ready.close()
        outcomes.close()


def _approved_workflow_crash(url, run_id, after_intent):
    import json
    import os

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app import db as host_db
    from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY, ModelTurnDriver
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.trace_runs import WorkflowExecutionLease
    from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository
    from app.application.workflow.agentic_model_policy import WorkflowAgenticModelPolicy
    from app.infrastructure.llm.client import resolve_durable_model_client

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    host_db.HostSessionLocal = factory
    if after_intent:
        committing = {"intent": False}

        def detect(_connection, _cursor, statement, parameters, _context, _many):
            if statement.startswith("UPDATE agent_runs"):
                for value in parameters:
                    if isinstance(value, str) and value.startswith("{"):
                        payload = json.loads(value)
                        steps, calls = payload.get("steps", []), payload.get("tool_calls", [])
                        if len(steps) == len(calls) == 1 and steps[0]["status"] == "running":
                            committing["intent"] = (
                                calls[0]["output"].get("outcome") == "waiting_approval"
                            )

        def committed(_session):
            if committing["intent"]:
                os._exit(74)

        event.listen(engine, "after_cursor_execute", detect)
        event.listen(factory.class_, "after_commit", committed)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory, auto_create=False)
    execution = queue.get(run_id)
    run = runs.get(run_id)
    state = run.metadata[STATE_KEY]
    context = {
        **run.metadata["runtime_context"],
        "_workflow_execution_lease": WorkflowExecutionLease(run_id),
    }
    client, model = resolve_durable_model_client(context, state["model_reference"])
    policy = WorkflowAgenticModelPolicy.restore(state["policy"], context, client, model)
    fenced = ClaimedRunRepository(runs, execution, execution.lease_owner)
    driver = ModelTurnDriver(policy, repository=fenced, run_id=run_id, context=context, state=state)
    driver.initialize([], limits={})
    with worker_claim_scope(runs, execution, execution.lease_owner):
        driver.execute_approved(
            AgentOrchestrator(repository=fenced), run.metadata["dispatch"]["approved_step_id"]
        )
    saved = runs.get(run_id)
    assert saved.metadata[STATE_KEY]["phase"] == "waiting_approval"
    assert saved.metadata[STATE_KEY]["next_call_index"] == 0
    assert saved.steps[0].attempt_count == 1
    assert saved.tool_calls[0].output["business_verification"]["verified"] is True
    os._exit(73)


import pytest


@pytest.mark.parametrize("after_intent", [False, True])
def test_real_os_crash_at_approved_intent_and_receipt_boundaries(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    after_intent,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope
    from tests.test_application.test_workflow_model_turn_durable import _waiting_write

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    run_id = _waiting_write(actor, monkeypatch)
    review = http.client.get(f"/api/agent/runs/{run_id}")
    queued = http.client.post(
        f"/api/agent/runs/{run_id}/continue",
        json={"approval_grant": review.json()["approval"]["grant"]},
    )
    assert queued.status_code == 202
    execution = http.queue.claim_run(run_id, "workflow-crash", lease_seconds=60)
    process = multiprocessing.get_context("spawn").Process(
        target=_approved_workflow_crash,
        args=(str(actor.factory.kw["bind"].url), run_id, after_intent),
    )
    try:
        process.start()
        process.join(timeout=35)
        assert process.exitcode == (74 if after_intent else 73)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    crashed = http.repository.get(run_id)
    original = crashed.tool_calls[0]
    original_usage = dict(original.metadata.get("usage_ledger") or {})
    with actor.factory.begin() as db:
        db.query(AgentTaskExecutionRecord).filter_by(run_id=run_id).update(
            {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
        )
    replacement = http.queue.claim_run(run_id, "workflow-recovered", lease_seconds=60)
    assert replacement.execution_count == execution.execution_count + 1
    requests = workflow_fixtures.json_model(monkeypatch, [{"action": "done"}])
    final = AgentOrchestrator(
        repository=ClaimedRunRepository(http.repository, replacement, "workflow-recovered")
    ).execute_dispatched_run(run_id, recovered=True)
    assert final.status == ("blocked" if after_intent else "completed")
    assert [call.call_id for call in final.tool_calls] == [original.call_id]
    assert final.steps[0].attempt_count == 1
    assert final.tool_calls[0].metadata.get("usage_ledger", {}) == original_usage
    assert len(requests) == (0 if after_intent else 1)
    assert final.metadata[STATE_KEY]["round"] == (1 if after_intent else 2)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="workflow boundary customer").count() == (
            0 if after_intent else 1
        )
