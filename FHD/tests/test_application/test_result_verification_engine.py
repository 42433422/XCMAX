"""Independent evidence, immutable identities and effect-free verification recovery."""

from __future__ import annotations

import copy
import sqlite3
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    step_verification_blocked,
    summarize_verification,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_agent_user_decision_pause import native_preview as native_preview


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


def test_pending_preview_binding_does_not_itself_authorize_continuation(
    trusted_actor, native_preview
):
    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        approval_scope_matches,
    )
    from app.application.agent_orchestrator.result_verification import preview_continuation_params

    actor = trusted_actor(role="admin")
    run, step, call, context = _paused_preview(actor, native_preview)
    assert call.metadata["verification"]["code"] == "result_preview_verified"
    original = copy.deepcopy(call.to_dict())
    proposal = preview_continuation_params(run, step, call)
    assert proposal == {**call.params, "valid_rows_only": True}
    with pytest.raises(ApprovalGrantError, match="续跑参数尚未绑定"):
        _approval_for(run, step)
    assert not approval_scope_matches(run, step)
    step.params = proposal
    run.metadata["plan"]["nodes"][0]["params"] = copy.deepcopy(proposal)
    assert not step_verification_blocked(run, step)
    assert not approval_scope_matches(run, step)
    run.metadata["approval_receipt"] = _approval_for(run, step)
    assert approval_scope_matches(run, step)
    assert call.to_dict() == original


@pytest.mark.parametrize(
    "resume",
    [
        {},
        {"valid_rows_only": False},
        {"valid_rows_only": 1},
        {"valid_rows_only": "true"},
        {"file_path": "another-upload"},
        {"valid_rows_only": True, "execute": True},
    ],
)
def test_preview_resume_report_cannot_expand_the_parameter_allowlist(
    trusted_actor, native_preview, resume
):
    from app.application.agent_orchestrator.result_verification import preview_continuation_params

    actor = trusted_actor(role="admin")
    run, step, call, context = _paused_preview(actor, native_preview, resume=resume)
    original = copy.deepcopy(call.to_dict())
    plan = copy.deepcopy(run.metadata["plan"])
    assert call.metadata["verification"]["accepted"] is False
    assert preview_continuation_params(run, step, call) is None
    assert step_verification_blocked(run, step)
    assert step.params == call.params
    assert run.metadata["plan"] == plan
    assert call.to_dict() == original


@pytest.mark.parametrize("change", ["source", "extra_param", "changed_upload", "unknown"])
def test_verified_preview_continuation_still_requires_exact_original_authority(
    monkeypatch, trusted_actor, native_preview, change
):
    from app.application.agent_orchestrator.approval_grant import approval_scope_matches
    from app.application.agent_orchestrator.result_verification import preview_continuation_params
    from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation

    actor = trusted_actor(role="admin")
    run, step, call, context = _paused_preview(actor, native_preview)
    proposal = preview_continuation_params(run, step, call)
    assert proposal is not None
    step.params = proposal
    run.metadata["plan"]["nodes"][0]["params"] = copy.deepcopy(proposal)
    run.metadata["approval_receipt"] = _approval_for(run, step)
    assert approval_scope_matches(run, step)
    if change == "source":
        unrelated = _passed()
        unrelated["checks"][0]["source"] = "other_authority"
        _adapter(monkeypatch, lambda **_: unrelated)
        original = copy.deepcopy(step)
        original.params = copy.deepcopy(call.params)
        assert verify_step_result(run=run, step=original, call=call, context=context)["accepted"]
        assert preview_continuation_params(run, step, call) is None
        assert step_verification_blocked(run, step)
    elif change == "unknown":
        run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
        assert requires_retry_reconciliation(run)
    else:
        step.params["target_type" if change == "extra_param" else "file_path"] = "other"
        assert step_verification_blocked(run, step)
        assert not approval_scope_matches(run, step)


def test_tool_and_model_claims_cannot_supply_independent_evidence():
    run, step, call, context = _receipt(
        output={
            "success": True,
            "id": 1,
            "verification": {"status": "verified", "verified": True},
            "judge_score": 1.0,
            "summary": "All checks passed",
        }
    )
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["status"] == "inconclusive"
    assert report["code"] == "result_verifier_unavailable"
    assert report["accepted"] is False
    assert step_verification_blocked(run, step)


def test_read_only_contract_is_explicitly_not_independent_verification():
    run, step, call, context = _receipt(read_only=True)
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["status"] == "not_required"
    assert report["accepted"] is True
    summary = summarize_verification(run)
    assert summary["independently_verified_steps"] == 0
    assert summary["contract_only_steps"] == 1


@pytest.mark.parametrize("confirmation", [False, True], ids=["parameters", "plan"])
def test_answered_host_clarification_does_not_block_a_verified_business_read(
    trusted_actor, confirmation
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.clarification_node import build_clarify_node
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor = trusted_actor(permissions=["customer.view", "business_db.read", "tool.clarify.ask"])
    read = WorkflowNode(
        node_id="read",
        tool_id="business_db",
        action="read",
        params={"entity": "customers"} if confirmation else {},
        risk="low",
        idempotent=True,
    )
    question = (
        WorkflowNode(
            node_id="confirm",
            tool_id="clarify",
            action="ask",
            params={"question": "请确认查询"},
            risk="low",
            idempotent=True,
        )
        if confirmation
        else build_clarify_node(
            "请选择业务实体",
            ambient={
                "target_node_id": read.node_id,
                "clarification": {"reason": "missing_required", "missing_fields": ["entity"]},
            },
        )
    )
    read.depends_on = [question.node_id]
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="查询当前企业客户",
        plan=PlanGraph(plan_id="confirmed-read", intent="read", nodes=[question, read]),
        runtime_context=actor.context,
    )
    assert run.status == "waiting_user" and not run.tool_calls, (run.error, run.final_output)
    if confirmation:
        completed = orchestrator.continue_plan_confirmation(
            run.run_id,
            answered_by=str(actor.user_id),
            clarification_step_id=run.steps[0].step_id,
            confirmed=True,
        )
    else:
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=run.steps[0].step_id,
            parameters={"entity": "customers"},
            requested_by=str(actor.user_id),
        )
        completed = orchestrator.execute_dispatched_run(run.run_id)
    assert completed.status == "completed"
    assert completed.metadata["verification"]["accepted"] is True
    control = completed.metadata["verification"]["steps"][0]
    assert control["status"] == "not_required"
    assert control["code"] == "host_control_answer_confirmed"
    assert len(completed.tool_calls) == 1
    assert completed.tool_calls[0].tool_id == "business_db"


@pytest.mark.parametrize("mismatch", ["no_event", "other_run", "other_step", "business_write"])
def test_answer_flag_or_unrelated_host_event_cannot_clear_historical_effect(mismatch):
    run, read, call, context = _receipt(read_only=True)
    verify_step_result(run=run, step=read, call=call, context=context)
    historical = AgentStep(
        node_id="old",
        tool_id="sales" if mismatch == "business_write" else "clarify",
        action="quote" if mismatch == "business_write" else "ask",
        status="completed",
        output={"success": True, "answer_confirmed": True},
    )
    run.steps.insert(0, historical)
    if mismatch != "no_event":
        event = run.add_event(
            "step.clarification_answered",
            data={"step_id": "other" if mismatch == "other_step" else historical.step_id},
        )
        if mismatch == "other_run":
            event.run_id = "another-run"
    assert step_verification_blocked(run, historical)
    assert summarize_verification(run)["accepted"] is False


@pytest.mark.parametrize("pending", [False, True])
def test_unverified_effect_receipt_preserves_known_pending_or_unknown_without_rewriting(pending):
    from app.application.agent_orchestrator.result_verification import project_verification
    from app.application.agent_orchestrator.trace_payloads import agent_node_output
    from app.domain.task_lifecycle.results import execution_result_pending_state
    from app.fastapi_routes.tools_execute import _capability_http_receipt

    original = (
        {"success": False, "execution_state": "pending"} if pending else {"success": True, "id": 1}
    )
    run, step, call, context = _receipt(output=original)
    verify_step_result(run=run, step=step, call=call, context=context)
    project_verification(run)
    run.status = "blocked"
    # A stale final projection must not override the immutable call and its
    # current host readback; neither variant permits a new dispatch.
    run.final_output["node_outputs"] = {step.node_id: {"success": True}}
    projected = agent_node_output(run, step.node_id)
    state = execution_result_pending_state(projected)
    assert state == ("pending" if pending else "unknown")
    payload, status = _capability_http_receipt({**projected, "execution_state": state})
    assert status == 202 and payload["success"] is False
    assert payload["retryable"] is False
    assert bool(payload.get("reconciliation_required")) is (not pending)
    assert step.output == call.output == original


def test_read_only_tool_cannot_bypass_file_verification():
    run, step, call, context = _receipt(
        read_only=True,
        output={"success": True, "artifacts": [{"artifact_type": "file", "uri": "/missing.xlsx"}]},
    )
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["code"] == "artifact_verifier_unavailable"
    assert not report["accepted"]


@pytest.mark.parametrize("location", ["artifacts", "artifact", "nested"])
def test_business_receipt_does_not_verify_an_unchecked_attached_file(monkeypatch, location):
    _adapter(monkeypatch, lambda **_: _passed())
    artifact = {"artifact_type": "file", "artifact_id": "csv_fake", "metadata": {"sha256": "fake"}}
    payload = {"success": True, "artifacts": []}
    if location == "nested":
        payload["result"] = {"artifacts": [artifact]}
    else:
        payload[location] = [artifact] if location == "artifacts" else artifact
    run, step, call, context = _receipt(output=payload)
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["code"] == "artifact_verification_incomplete"
    assert not report["accepted"]
    assert step_verification_blocked(run, step)


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [{"check_id": "empty", "status": "passed", "source": "db", "evidence": {}}],
        [{"check_id": "failed", "status": "failed", "source": "db", "evidence": {"id": 1}}],
    ],
)
def test_empty_or_contradictory_checks_cannot_pass(monkeypatch, checks):
    _adapter(
        monkeypatch, lambda **_: {"status": "verified", "code": "claimed_pass", "checks": checks}
    )
    run, step, call, context = _receipt()
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["status"] == "inconclusive"
    assert not report["accepted"]


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "mod_id", "task_id"])
def test_verification_cannot_move_to_another_scope(monkeypatch, field):
    calls = []
    _adapter(monkeypatch, lambda **_: calls.append(1) or _passed())
    run, step, call, context = _receipt()
    if field == "task_id":
        run.metadata["runtime_context"][field] = "other"
    else:
        context[field] = "other"
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["code"] == "verification_binding_invalid"
    assert calls == []


@pytest.mark.parametrize(
    "mutation", ["params", "output", "step_output", "contract", "report", "call_id"]
)
def test_completed_step_cannot_skip_static_proof_binding(monkeypatch, mutation):
    _adapter(monkeypatch, lambda **_: _passed())
    run, step, call, context = _receipt()
    assert verify_step_result(run=run, step=step, call=call, context=context)["accepted"]
    assert not step_verification_blocked(run, step)
    if mutation == "params":
        step.params["name"] = "B"
    elif mutation == "output":
        call.output["id"] = 2
    elif mutation == "step_output":
        step.output["id"] = 2
    elif mutation == "contract":
        call.metadata["verification_contract"]["read_only"] = True
    elif mutation == "report":
        call.metadata["verification"]["checks"][0]["evidence"]["row_id"] = 2
    else:
        call.call_id = "other-call"
    assert step_verification_blocked(run, step)
    assert not summarize_verification(run)["accepted"]


@pytest.mark.parametrize("has_call", [False, True])
def test_historical_completed_step_does_not_disappear_from_coverage(monkeypatch, has_call):
    from app.application.agent_orchestrator.result_verification import (
        project_verification,
        verified_step_output,
    )
    from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
    from app.application.agent_orchestrator.task_execution_models import dispatched_run_state

    _adapter(monkeypatch, lambda **_: _passed())
    run, step, call, context = _receipt()
    verify_step_result(run=run, step=step, call=call, context=context)
    legacy = AgentStep(
        node_id="legacy",
        tool_id="legacy",
        action="create",
        status="completed",
        output={"success": True},
    )
    run.steps.append(legacy)
    if has_call:
        run.tool_calls.append(
            ToolCall(
                step_id=legacy.step_id,
                node_id=legacy.node_id,
                tool_id=legacy.tool_id,
                action=legacy.action,
                status="completed",
                output=copy.deepcopy(legacy.output),
            )
        )
    original_step = copy.deepcopy(legacy.to_dict())
    original_calls = [copy.deepcopy(item.to_dict()) for item in run.tool_calls]
    summary = project_verification(run)
    assert summary["status"] == "not_verified"
    assert not summary["accepted"]
    assert len(summary["steps"]) == 2
    run.status = "blocked"
    projected = verified_step_output(run, legacy)
    assert projected["success"] is False and projected["execution_state"] == "unknown"
    assert projected["reconciliation_required"] is True and projected["retryable"] is False
    assert dispatched_run_state(run) == ("unknown", "needs_verification")
    assert requires_retry_reconciliation(run)
    assert legacy.to_dict() == original_step
    assert [item.to_dict() for item in run.tool_calls] == original_calls


@pytest.mark.parametrize(
    "body",
    [
        {"success": True, "business_result": {"status": "partial", "success": False}},
        {"success": True, "verification": {"status": "failed"}},
        {"success": "true"},
    ],
)
def test_output_contract_and_explicit_failures_precede_readback(monkeypatch, body):
    calls = []
    _adapter(monkeypatch, lambda **_: calls.append(1) or _passed())
    run, step, call, context = _receipt(output=body)
    assert not verify_step_result(run=run, step=step, call=call, context=context)["accepted"]
    assert calls == []


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


def test_verifier_timeout_only_rechecks_original_committed_effect(tmp_path, monkeypatch):
    repo, runner, run, step, context, readback, dispatches, charges = _runtime(
        tmp_path, monkeypatch
    )

    def offline(**_):
        raise TimeoutError("source not available")

    _adapter(monkeypatch, offline)
    runner.execute_step(run, step, runtime_context=context, node_outputs={})
    assert run.status == "blocked"
    assert run.tool_calls[0].output == {"success": True, "id": 1}
    assert summarize_verification(run)["status"] == "inconclusive"
    _adapter(monkeypatch, readback)
    recovered = repo.get(run.run_id)
    runner.execute_step(recovered, recovered.steps[0], runtime_context=context, node_outputs={})
    assert summarize_verification(recovered)["accepted"]
    assert len(dispatches) == len(charges) == 1
    assert recovered.steps[0].attempt_count == 1
    assert len(recovered.tool_calls) == 1


def test_business_write_cannot_replay_by_claiming_preview_control(tmp_path, monkeypatch):
    repo, runner, run, step, context, _readback, dispatches, charges = _runtime(
        tmp_path, monkeypatch
    )
    dispatch = runner.executor.execute
    runner.executor.execute = lambda *args, **kwargs: {
        **dispatch(*args, **kwargs),
        "preview": True,
        "requires_user_decision": True,
        "resume_params": {"valid_rows_only": True},
        "verification": {"scope": "preview_only", "business_effect_verified": False},
    }
    runner.execute_step(run, step, runtime_context=context, node_outputs={})
    original = copy.deepcopy(run.tool_calls[0])
    assert original.metadata["verification"]["accepted"] is True
    step.params["valid_rows_only"] = True
    step.status = "pending"
    runner.execute_step(run, step, runtime_context=context, node_outputs={})
    assert run.status == "blocked"
    assert len(dispatches) == len(charges) == len(run.tool_calls) == 1
    retained = repo.get(run.run_id).tool_calls[0]
    assert retained.params == original.params and retained.output == original.output
    assert retained.metadata["verification_contract"] == original.metadata["verification_contract"]


def test_crash_between_receipt_and_verification_retains_recheckable_result(tmp_path, monkeypatch):
    repo, runner, run, step, context, readback, dispatches, charges = _runtime(
        tmp_path, monkeypatch
    )

    class SimulatedProcessExit(BaseException):
        pass

    def crash(**_):
        raise SimulatedProcessExit()

    _adapter(monkeypatch, crash)
    with pytest.raises(SimulatedProcessExit):
        runner.execute_step(run, step, runtime_context=context, node_outputs={})
    restored = repo.get(run.run_id)
    assert restored.tool_calls[0].output == {"success": True, "id": 1}
    assert restored.tool_calls[0].metadata["verification"]["status"] == "pending"
    assert restored.final_output["verification"]["status"] == "pending"
    assert restored.final_output["verification"]["accepted"] is False
    assert restored.steps[0].status == "completed"
    _adapter(monkeypatch, readback)
    runner.execute_step(restored, restored.steps[0], runtime_context=context, node_outputs={})
    assert summarize_verification(restored)["accepted"]
    assert len(dispatches) == len(charges) == 1


def test_rechecking_saved_file_receipt_restores_download_projection_once(
    tmp_path, monkeypatch, trusted_actor
):
    from app.application.agent_orchestrator.artifact_files import (
        read_verified_run_file,
        store_run_file,
    )
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.agent_orchestrator.verification_recovery import reverify_run

    actor = trusted_actor(role="admin")
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir", lambda: str(tmp_path)
    )
    step = AgentStep(
        node_id="export",
        tool_id="reports",
        action="export",
        params={"data": [{"product": "A", "quantity": 2}]},
        status="completed",
        attempt_count=1,
    )
    run = AgentRun(
        user_id=str(actor.user_id),
        message="Export approved rows",
        status="blocked",
        steps=[step],
        metadata={"runtime_context": copy.deepcopy(actor.context)},
    )
    content = b"product,quantity\nA,2\n"
    artifact = store_run_file(run.run_id, content, name="approved.csv")
    step.output = {"success": True, "artifacts": [artifact]}
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        output=copy.deepcopy(step.output),
        status="completed",
        metadata={"attempt_count": 1},
    )
    run.tool_calls.append(call)
    freeze_verification_contract(
        run, step, call, get_tool_action_spec("reports", "export"), actor.context
    )
    bind_execution_receipt(call)
    repo = InMemoryAgentRunRepository()
    repo.save(run)
    assert not run.artifacts
    # This is the durable snapshot after the raw receipt was saved but before
    # verification/artifact projection completed. Reading it must not export again.
    for _ in range(2):
        restored = reverify_run(repo, run.run_id, runtime_context=actor.context)
        assert restored.metadata["verification"]["accepted"]
        assert len(restored.artifacts) == 1
        assert restored.artifacts[0].artifact_id == artifact["artifact_id"]
        assert read_verified_run_file(run.run_id, restored.artifacts[0].to_dict()) == content
        assert restored.tool_calls[0].output == step.output
        assert restored.steps[0].attempt_count == 1


def test_failed_verification_stops_dependent_graph_and_final_success(monkeypatch, tmp_path):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    dispatched = []

    def execute(step, *, runtime_context):
        dispatched.append(step.node_id)
        return {
            "success": True,
            "data": [],
            "verification": {"status": "failed", "verified": False},
        }

    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    orchestrator._step_execution.executor = SimpleNamespace(execute=execute)
    plan = PlanGraph(
        plan_id="verify-before-next",
        intent="query",
        nodes=[
            WorkflowNode(
                node_id="first",
                tool_id="business_db",
                action="read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="later",
                tool_id="business_db",
                action="read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
                depends_on=["first"],
            ),
        ],
    )
    run = orchestrator.start_run_from_plan(
        user_id="9", message="Read products twice", plan=plan, runtime_context={"tenant_id": "7"}
    )
    assert dispatched == ["first"]
    # The shared result normalizer preserves an explicit negative tool result
    # before independent readback, so this is a failed receipt, not a passed call.
    assert run.status == "failed"
    assert run.steps[0].output["success"] is False
    assert not any(event.event_type == "run.completed" for event in run.events)
    assert run.steps[1].status == "pending"


def test_owner_confirmation_resumes_original_verified_graph_without_tool_receipt(
    monkeypatch, tmp_path
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    dispatched = []

    def execute(step, *, runtime_context):
        dispatched.append(step.node_id)
        return {"success": True, "data": []}

    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    orchestrator._step_execution.executor = SimpleNamespace(execute=execute)
    plan = PlanGraph(
        plan_id="original-control-gate",
        intent="query",
        nodes=[
            WorkflowNode("before", "business_db", "read", {"entity": "products"}),
            WorkflowNode(
                "answer",
                "clarify",
                "ask",
                {"question": "Continue?"},
                idempotent=True,
                depends_on=["before"],
            ),
            WorkflowNode(
                "after", "business_db", "read", {"entity": "products"}, depends_on=["answer"]
            ),
        ],
    )
    for node in plan.nodes:
        spec = get_tool_action_spec(node.tool_id, node.action)
        if spec is not None:
            node.risk, node.idempotent = spec.risk, spec.idempotent
    run = orchestrator.start_run_from_plan(
        user_id="9",
        message="Read after confirmation",
        plan=plan,
        runtime_context={"tenant_id": "7"},
    )
    assert run.status == "waiting_user" and dispatched == ["before"], (
        run.error,
        [(step.node_id, step.status, step.output) for step in run.steps],
        [call.metadata.get("verification") for call in run.tool_calls],
        [
            {
                key: event.data.get(key)
                for key in (
                    "node_id",
                    "expected_risk",
                    "step_risk",
                    "plan_idempotent",
                    "step_idempotent",
                )
            }
            for event in run.events
            if event.event_type == "workflow.plan_audit_rejected"
        ],
    )
    confirmation = run.steps[1]
    assert (
        orchestrator.continue_plan_confirmation(
            run.run_id,
            answered_by="other-owner",
            clarification_step_id=confirmation.step_id,
            confirmed=True,
        )
        is None
    )
    assert dispatched == ["before"]
    resumed = orchestrator.continue_plan_confirmation(
        run.run_id, answered_by="9", clarification_step_id=confirmation.step_id, confirmed=True
    )
    assert resumed.status == "completed" and dispatched == ["before", "after"]
    assert len(resumed.tool_calls) == 2
    report = summarize_verification(resumed)
    assert report["accepted"] is True
    control = next(row for row in report["steps"] if row["step_id"] == confirmation.step_id)
    assert control["code"] == "host_control_answer_confirmed"
    assert control["checks"][0]["evidence"]["business_effect_verified"] is False


@pytest.mark.parametrize("drift", ["params", "output", "tenant", "event", "business_action"])
def test_control_answer_cannot_attest_changed_scope_or_business_action(drift):
    from app.application.agent_orchestrator.clarification import apply_plan_confirmation

    run, _step, _call, _context = _receipt()
    control = AgentStep(
        "answer", "clarify", "ask", {"question": "Continue?"}, status="waiting_user"
    )
    run.steps.append(control)
    run.status = "waiting_user"
    apply_plan_confirmation(run, step_id=control.step_id, confirmed=True)
    assert not step_verification_blocked(run, control)
    if drift == "params":
        control.params["question"] = "A different operation?"
    elif drift == "output":
        control.output["confirmed"] = False
    elif drift == "tenant":
        run.metadata["runtime_context"]["tenant_id"] = "other-tenant"
    elif drift == "event":
        run.events.clear()
    else:
        control.tool_id, control.action = "sales", "deliver"
    assert step_verification_blocked(run, control)


@pytest.mark.parametrize("read_only", [False, True])
def test_pending_receipt_requires_real_readback_even_when_read_only(read_only):
    run, step, call, context = _receipt(
        read_only=read_only, output={"success": False, "execution_state": "pending"}
    )
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert not report["accepted"]
    assert report["code"] == "result_verifier_unavailable"
    assert step_verification_blocked(run, step)


@pytest.mark.parametrize(
    "state", ["failed", "cancelled", "rejected", "unknown", "waiting_approval"]
)
def test_failed_unknown_or_unapproved_receipt_cannot_gain_business_success(monkeypatch, state):
    _adapter(monkeypatch, lambda **_: pytest.fail("failed receipt must not be upgraded"))
    run, step, call, context = _receipt(output={"success": False, "execution_state": state})
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["code"] == "execution_receipt_not_successful" and not report["accepted"]


def test_pending_step_keeps_acknowledgement_and_never_dispatches_twice(tmp_path, monkeypatch):
    repo, runner, run, step, context, readback, dispatches, charges = _runtime(
        tmp_path, monkeypatch
    )
    dispatch = runner.executor.execute

    def accepted(*args, **kwargs):
        dispatch(*args, **kwargs)
        return {"success": False, "execution_state": "pending", "request_id": "accepted-original"}

    runner.executor.execute = accepted
    _adapter(
        monkeypatch,
        lambda **_: {"status": "inconclusive", "code": "provider_pending", "checks": []},
    )
    runner.execute_step(run, step, runtime_context=context, node_outputs={})
    original = copy.deepcopy(step.output)
    assert run.status == "blocked" and step.status == "completed", repr(
        (step.output, [call.metadata.get("verification") for call in run.tool_calls])
    )
    assert step.output["execution_state"] == "pending"
    assert "outcome" not in step.output and "reconciliation_required" not in step.output
    assert run.metadata["recovery"]["state"] == "result_pending"
    _adapter(monkeypatch, readback)
    recovered = repo.get(run.run_id)
    runner.execute_step(recovered, recovered.steps[0], runtime_context=context, node_outputs={})
    assert summarize_verification(recovered)["accepted"]
    assert recovered.tool_calls[0].output == original
    assert len(dispatches) == len(charges) == 1
    assert recovered.steps[0].attempt_count == 1
