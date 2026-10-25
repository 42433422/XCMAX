"""Real SQL, original HTTP grant and independent write readback for workflow turns."""

import json

from tests.test_application import test_workflow_model_turn as workflow_fixtures

json_model = workflow_fixtures.json_model
reviewed_agent_http = workflow_fixtures.reviewed_agent_http
run_workflow = workflow_fixtures.run_workflow
trusted_actor = workflow_fixtures.trusted_actor
workflow_model = workflow_fixtures.workflow_model


def test_original_write_waits_then_continues_same_call_and_model(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(
        monkeypatch,
        [
            {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}},
            {
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "workflow approved customer"},
                },
            },
            {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}},
            {"action": "done"},
        ],
    )
    registry = {
        "business_db": {
            "actions": {
                "read": {"risk": "low", "idempotent": True},
                "write": {"risk": "medium", "idempotent": False},
            }
        }
    }
    first = run_workflow(actor, registry)
    assert first.success is False
    assert first.final_context["workflow_status"]["state"] == "waiting_user"
    run = http.repository.get(first.final_context["run_id"])
    assert len(requests) == 2 and len(run.tool_calls) == 2
    assert run.metadata[STATE_KEY]["next_call_index"] == 0
    original = [(call.call_id, call.step_id, call.params) for call in run.tool_calls]
    active_seconds = run.metadata[STATE_KEY]["active_seconds"]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="workflow approved customer").count() == 0
    review = http.client.get(f"/api/agent/runs/{run.run_id}")
    assert review.status_code == 200, review.text
    grant = review.json()["approval"]["grant"]
    assert STATE_KEY not in json.dumps(review.json())
    queued = http.client.post(
        f"/api/agent/runs/{run.run_id}/continue", json={"approval_grant": grant}
    )
    assert queued.status_code == 202, queued.text
    execution = http.queue.claim_run(run.run_id, "workflow-test", lease_seconds=60)
    assert execution is not None
    fenced = ClaimedRunRepository(http.repository, execution, "workflow-test")
    final = AgentOrchestrator(repository=fenced).execute_dispatched_run(run.run_id)
    assert final.status == "completed", {"state": final.metadata[STATE_KEY], "error": final.error}
    assert [(call.call_id, call.step_id, call.params) for call in final.tool_calls[:2]] == original
    assert final.metadata[STATE_KEY]["round"] == 4 and len(requests) == 4
    projected = final.final_output["workflow_result"]["workflow_result"]
    assert len(projected["final_context"]["workflow_trace"]) == len(final.tool_calls)
    assert all(row["success"] for row in projected["final_context"]["workflow_trace"])
    assert final.metadata[STATE_KEY]["active_seconds"] >= active_seconds
    assert len(final.metadata[STATE_KEY]["delivered"]) == 3
    assert final.tool_calls[1].metadata["independent_verification"]["verified"] is True
    assert all(not call.metadata.get("observed") for call in final.tool_calls)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="workflow approved customer").count() == 1
    replay = run_workflow(actor, registry)
    assert replay.success is True and len(requests) == 4
    assert replay.final_context["run_id"] == final.run_id
    assert (
        http.client.post(
            f"/api/agent/runs/{run.run_id}/continue", json={"approval_grant": grant}
        ).status_code
        != 202
    )


def _waiting_write(actor, monkeypatch):
    workflow_fixtures.json_model(
        monkeypatch,
        [
            {
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"unit_name": "workflow boundary customer"},
                },
            }
        ],
    )
    first = run_workflow(actor, {"business_db": {"actions": {"write": {}}}})
    return first.final_context["run_id"]


import pytest


@pytest.mark.parametrize("damage", ["projection", "receipt", "budget", "model_reference"])
def test_saved_boundary_damage_blocks_original_write(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    damage,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.worker_repository import ClaimedRunRepository
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    run_id = _waiting_write(actor, monkeypatch)
    review = http.client.get(f"/api/agent/runs/{run_id}")
    queued = http.client.post(
        f"/api/agent/runs/{run_id}/continue",
        json={"approval_grant": review.json()["approval"]["grant"]},
    )
    assert queued.status_code == 202
    run = http.repository.get(run_id)
    original_id = run.tool_calls[0].call_id
    if damage == "projection":
        run.tool_calls[0].metadata["workflow_projection"]["node_result"]["success"] = True
    elif damage == "receipt":
        run.tool_calls[0].output["changed"] = True
    elif damage == "budget":
        run.metadata[STATE_KEY]["active_seconds"] = run.metadata[STATE_KEY]["limits"]["seconds"] + 1
    else:
        run.metadata[STATE_KEY]["model_reference"]["endpoint"] = "https://different.example/v1"
    http.repository.save(run)
    execution = http.queue.claim_run(run_id, "workflow-boundary", lease_seconds=60)
    final = AgentOrchestrator(
        repository=ClaimedRunRepository(http.repository, execution, "workflow-boundary")
    ).execute_dispatched_run(run_id)
    assert final.status in {"blocked", "failed"}
    assert [call.call_id for call in final.tool_calls] == [original_id]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(PurchaseUnit).filter_by(unit_name="workflow boundary customer").count() == 0


@pytest.mark.parametrize("outcome", ["unknown", "pending", "waiting_approval"])
def test_unresolved_real_receipt_holds_cursor_and_never_requests_next_model(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    outcome,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    workflow_fixtures.inline_business_adapter(
        monkeypatch, lambda *args: {"success": False, "outcome": outcome}
    )
    requests = json_model(
        monkeypatch,
        [{"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}}],
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    run = http.repository.get(result.final_context["run_id"])
    assert not result.success and len(requests) == 1
    assert len(run.tool_calls) == 1
    assert run.metadata[STATE_KEY]["next_call_index"] == 0
    assert run.metadata[STATE_KEY]["delivered"] == []
    assert (
        run.metadata[STATE_KEY]["phase"]
        == {
            "unknown": "reconciliation",
            "pending": "pending",
            "waiting_approval": "waiting_approval",
        }[outcome]
    )


@pytest.mark.parametrize("damage", ["shape", "json", "type_error"])
def test_damaged_memory_projection_preserves_actual_receipt_and_blocks(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    damage,
):
    from app.application.agent_orchestrator.trace_runs import (
        TraceRunService,
        WorkflowReceiptProjection,
    )

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    original = TraceRunService.dispatch_tool

    def dispatch(self, *args, **kwargs):
        def broken():
            raise TypeError("broken trusted projection")

        kwargs["projection"] = (
            {"read": "JSON cannot construct a callback"}
            if damage == "json"
            else WorkflowReceiptProjection(
                broken if damage == "type_error" else lambda: {"output": {"success": True}}
            )
        )
        return original(self, *args, **kwargs)

    monkeypatch.setattr(TraceRunService, "dispatch_tool", dispatch)
    requests = json_model(
        monkeypatch,
        [{"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}}],
    )
    result = run_workflow(actor, {"business_db": {"actions": {"read": {}}}})
    run = http.repository.get(result.final_context["run_id"])
    assert run.status == "blocked" and not result.success and len(requests) == 1
    assert run.tool_calls[0].output["success"] is True
    assert run.tool_calls[0].metadata["workflow_projection_error"] == "workflow_projection_invalid"
    assert run.tool_calls[0].metadata["independent_verification"]["verified"] is True


@pytest.mark.parametrize("finished", [False, True])
def test_historical_observed_run_is_readable_but_never_promoted_to_model_execution(
    trusted_actor,
    reviewed_agent_http,
    workflow_model,
    monkeypatch,
    finished,
):
    from app.application.agent_orchestrator.model_turn_runtime import STATE_KEY
    from app.application.ai_chat.agent_workflow_bridge import AgentWorkflowBridge
    from app.application.workflow.workflow_types import PlanGraph, WorkflowRunResult

    actor = trusted_actor()
    http = reviewed_agent_http(actor)
    requests = json_model(monkeypatch, [])
    bridge = AgentWorkflowBridge(http.repository, lambda output: "", lambda output: [])
    plan = PlanGraph("old-observed", "old-history")
    run = bridge.start_run(
        user_id=str(actor.user_id),
        message="historical",
        plan=plan,
        runtime_context=dict(actor.context),
    )
    if finished:
        run = bridge.record_result(
            user_id=str(actor.user_id),
            message="historical",
            plan=plan,
            runtime_context=dict(actor.context),
            agent_run=run,
            run_result=WorkflowRunResult(plan.plan_id, True, [], {}, "historical snapshot"),
        )
    before = run.to_dict()
    review = http.client.get(f"/api/agent/runs/{run.run_id}")
    assert review.status_code == 200, review.text
    assert not review.json().get("approval")
    continued = http.client.post(f"/api/agent/runs/{run.run_id}/continue", json={})
    assert continued.status_code != 202, continued.text
    after = http.repository.get(run.run_id)
    assert after.to_dict() == before
    assert STATE_KEY not in after.metadata
    assert requests == [] and http.queue.get(run.run_id) is None
