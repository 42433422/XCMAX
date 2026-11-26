"""Reusable receipt, approval and independent SQLite readback test fixtures."""

from __future__ import annotations

import copy
import sqlite3
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult


def _receipt(
    *, read_only=False, output=None, tool_id="custom_business", action="create", params=None
):
    context = {"tenant_id": "7", "actor_id": "9", "user_id": "9", "task_id": "task-original"}
    step = AgentStep(
        node_id="write",
        tool_id=tool_id,
        action=action,
        params=copy.deepcopy({"name": "A"} if params is None else params),
    )
    step.attempt_count, step.status = 1, "completed"
    step.output = copy.deepcopy(output if output is not None else {"success": True, "id": 1})
    run = AgentRun(user_id="9", message="Create A", status="running", steps=[step])
    run.metadata["runtime_context"] = copy.deepcopy(context)
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        status="completed",
        output=copy.deepcopy(step.output),
        metadata={"attempt_count": 1},
    )
    run.tool_calls.append(call)
    spec = ToolActionSpecV2(
        tool_id=step.tool_id,
        action=step.action,
        read_only=read_only,
        output_schema={
            "type": "object",
            "required": ["success"],
            "properties": {"success": {"type": "boolean"}},
        },
    )
    freeze_verification_contract(run, step, call, spec, context)
    bind_execution_receipt(call)
    return run, step, call, context


def _passed():
    return {
        "status": "verified",
        "code": "source_matches",
        "checks": [
            {
                "check_id": "row",
                "status": "passed",
                "source": "separate_database_connection",
                "evidence": {"row_id": 1},
            }
        ],
    }


def _adapter(monkeypatch, function):
    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        function,
    )


def _paused_preview(actor, native_preview, *, resume=None):
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    output = native_preview(actor)
    if resume is not None:
        output["resume_params"] = copy.deepcopy(resume)
    step = AgentStep(
        node_id="preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "@uploads/宗南.xlsx"},
        risk="medium",
        idempotent=False,
        attempt_count=1,
        status="waiting_user",
        output=copy.deepcopy(output),
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        status="completed",
        output=copy.deepcopy(output),
        metadata={"attempt_count": 1},
    )
    plan = PlanGraph(
        plan_id="bound-preview",
        intent="elt_import",
        nodes=[
            WorkflowNode(
                step.node_id,
                step.tool_id,
                step.action,
                params=copy.deepcopy(step.params),
                risk=step.risk,
                idempotent=step.idempotent,
            )
        ],
    )
    run = AgentRun(
        user_id=str(actor.user_id),
        message="Confirm the original preview",
        status="waiting_user",
        plan_id=plan.plan_id,
        steps=[step],
        tool_calls=[call],
    )
    context = {
        **actor.context,
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
    }
    run.metadata.update(runtime_context=copy.deepcopy(context), plan=plan_to_dict(plan))
    freeze_verification_contract(
        run, step, call, get_tool_action_spec(step.tool_id, step.action), context
    )
    bind_execution_receipt(call)
    verify_step_result(run=run, step=step, call=call, context=context)
    return run, step, call, context


def _approval_for(run, step):
    from app.application.agent_orchestrator.approval_grant import (
        approval_receipt_claims,
        consume_approval_grant,
        issue_approval_grant,
    )

    grant = issue_approval_grant(run, principal_id=run.user_id)
    assert grant is not None
    claims = consume_approval_grant(grant["grant"], run=run, principal_id=run.user_id)
    return {
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        **approval_receipt_claims(run, step, claims=claims),
    }


def _runtime(tmp_path, monkeypatch):
    database = tmp_path / "actual-effect.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE effects (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    dispatches, charges = [], []

    def dispatch(_step, *, runtime_context):
        dispatches.append(runtime_context["idempotency_key"])
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO effects(id,name) VALUES(1,'A')")
        return {"success": True, "id": 1}

    def readback(**_):
        with sqlite3.connect(database) as db:
            row = db.execute("SELECT id,name FROM effects WHERE id=1").fetchone()
        assert row == (1, "A")
        return _passed()

    _adapter(monkeypatch, readback)
    spec = ToolActionSpecV2(tool_id="custom_business", action="create", risk="high")
    dependencies = SimpleNamespace(
        action_spec=lambda *_: spec,
        validate=lambda *_: ToolValidationResult(
            ok=True, tool_id=spec.tool_id, action=spec.action, spec=spec
        ),
    )
    usage = SimpleNamespace(
        refresh_run_cost_metadata=lambda run: run.metadata.update(
            cost_units_total=0, ai_cost_units_total=0
        ),
        record_tool_usage_entry=lambda *_: charges.append(1) or True,
        record_tool_usage_refund=lambda *_args, **_kwargs: pytest.fail(
            "Executed effect cannot be refunded by verification"
        ),
    )
    repo = InMemoryAgentRunRepository()
    runner = StepExecution(
        repo,
        SimpleNamespace(execute=dispatch),
        usage,
        dependencies,
        attach_artifacts=lambda *_args, **_kwargs: None,
        observe=lambda *_args, **_kwargs: {},
    )
    step = AgentStep(
        node_id="write", tool_id=spec.tool_id, action=spec.action, params={"name": "A"}
    )
    run = AgentRun(user_id="9", message="Create A", steps=[step], status="running")
    context = {"tenant_id": "7", "user_id": "9", "actor_id": "9"}
    run.metadata["runtime_context"] = context
    return repo, runner, run, step, context, readback, dispatches, charges
