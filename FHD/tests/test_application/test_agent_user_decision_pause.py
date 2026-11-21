"""工具返回 requires_user_decision 时，编排应停下询问用户而不是记为异常。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    consume_approval_grant,
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def preview_actor(trusted_actor, tmp_path, monkeypatch):
    from app.application.elt.preview_confirmation import publish_preview
    from app.db.models.elt import EltRun, EltRunRow, EltUpload
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(role="admin")
    path = tmp_path / "source.csv"
    path.write_text("product,quantity\nvalid,2\ninvalid,\n", encoding="utf-8")
    upload_id = "d6024ab0-cce5-44b5-9b6f-1221ad76dabb"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.add(
            EltUpload(
                id=upload_id,
                tenant_id=actor.tenant_id,
                owner_user_id=actor.user_id,
                file_name=path.name,
                suffix=".csv",
                size_bytes=path.stat().st_size,
                sha256=digest,
                storage_path=str(path),
                expires_at=utc_now_naive() + timedelta(days=1),
            )
        )
        db.flush()
        row = EltRun(
            id="run-1",
            tenant_id=actor.tenant_id,
            owner_user_id=actor.user_id,
            upload_id=upload_id,
            target_type="products",
            status="preview_ready",
            stage="preview_ready",
            progress=100,
            file_sha256=digest,
            total_rows=2,
            processed_rows=2,
            new_rows=1,
            error_rows=1,
            update_rows=0,
            skip_rows=0,
            executed_rows=0,
            draft_json="{}",
            summary_json="{}",
            source_features_json="{}",
            receipt_json="{}",
            reversible=False,
        )
        db.add(row)
        db.flush()
        for number, action in ((2, "new"), (3, "error")):
            db.add(
                EltRunRow(
                    run_id=row.id,
                    tenant_id=actor.tenant_id,
                    owner_user_id=actor.user_id,
                    source_sheet="source",
                    source_row=number,
                    final_action=action,
                    source_json=json.dumps({"product": action}),
                )
            )
        db.flush()
        publish_preview(db, row)
    actor.preview_upload_id = upload_id
    actor.preview_path = path
    return actor


def _preview_output(output, actor):
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.models.elt import EltRun
    from app.domain.shared_services.tools_workflow_elt import _summary
    from app.infrastructure.tenant_scope import tenant_scope

    result = deepcopy(output)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        actual = HistoryServiceMixin().run_dict(db.get(EltRun, "run-1"))
    result["data"] = {**_summary(actual), **result.get("data", {})}
    return result


def _run(actor) -> AgentRun:
    preview = AgentStep(
        node_id="elt_preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": actor.preview_upload_id},
        risk="medium",
        idempotent=False,
        status="waiting_user",
    )
    execute = AgentStep(
        node_id="elt_execute",
        tool_id="elt_import",
        action="execute",
        params={"run_id": "{{elt_preview.data.run_id}}"},
        risk="high",
        idempotent=False,
        depends_on=["elt_preview"],
    )
    run = AgentRun(user_id=str(actor.user_id), message="导入宗南.xlsx", status="waiting_user")
    run.metadata.update(cost_units_total=0, ai_cost_units_total=0)
    run.metadata["runtime_context"] = dict(actor.context)
    run.steps = [preview, execute]
    plan = PlanGraph(
        plan_id="elt-decision-pause",
        intent="elt_import",
        nodes=[
            WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params),
                risk=step.risk,
                idempotent=step.idempotent,
                depends_on=list(step.depends_on),
            )
            for step in run.steps
        ],
    )
    run.plan_id = plan.plan_id
    run.intent = plan.intent
    run.metadata["plan"] = plan_to_dict(plan)
    return run


def _executor(output: dict, actor) -> MagicMock:
    executor = MagicMock()
    executor.execute_with_deadline.return_value = _preview_output(output, actor)
    return executor


def _approve_and_execute(orchestrator, run, actor):
    grant = issue_approval_grant(run, principal_id=str(actor.user_id))
    assert grant is not None
    claims = consume_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
    staged = orchestrator.stage_approved_run(
        run.run_id,
        approved_by=str(actor.user_id),
        approved_step_id=claims["step_id"],
        runtime_context=actor.context,
        authenticated_actor_binding=actor.principal.actor_authorization,
        approval_claims=claims,
    )
    assert staged is not None and staged.status == "queued"
    return orchestrator.execute_dispatched_run(run.run_id)


def test_preview_blocker_pauses_run_instead_of_failing(preview_actor):
    actor = preview_actor
    repo = InMemoryAgentRunRepository()
    executor = _executor(
        {
            "success": True,
            "preview": True,
            "message": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "requires_user_decision": True,
            "question": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "resume_params": {"valid_rows_only": True},
            "data": {"run_id": "run-1", "executable": False, "error_rows": 1},
        },
        actor,
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)

    preview, execute = run.steps
    assert preview.status == "waiting_user"
    assert run.status == "waiting_user"
    assert execute.status == "pending", "阻断后不应继续调度执行节点"
    assert executor.execute_with_deadline.call_count == 1
    assert not any(event.event_type == "tool.failed" for event in run.events)
    waiting = [event for event in run.events if event.event_type == "step.waiting_user"]
    assert waiting and waiting[-1].data["reason"] == "requires_user_decision"
    assert "第18行" in waiting[-1].message
    assert run.final_output["clarification"]["requires_confirmation"] is True


@pytest.mark.parametrize("tamper_params", [False, True])
def test_approved_pause_reruns_step_with_resume_params(preview_actor, tamper_params):
    actor = preview_actor
    repo = InMemoryAgentRunRepository()
    pause_output = {
        "success": True,
        "preview": True,
        "message": "预演有 1 行错误",
        "requires_user_decision": True,
        "question": "预演有 1 行错误",
        "resume_params": {"valid_rows_only": True},
        "data": {"run_id": "run-1", "executable": False, "error_rows": 1},
    }
    resume_output = {
        "success": True,
        "preview": True,
        "message": "预演完成",
        "requires_user_decision": False,
        "data": {"run_id": "run-1", "executable": True, "error_rows": 1},
    }
    executor = MagicMock()
    executor.execute_with_deadline.side_effect = [
        _preview_output(pause_output, actor),
        _preview_output(resume_output, actor),
    ]
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)
    assert run.status == "waiting_user"
    assert executor.execute_with_deadline.call_count == 1
    assert run.steps[0].params["valid_rows_only"] is True
    assert run.metadata["plan"]["nodes"][0]["params"]["valid_rows_only"] is True
    assert "valid_rows_only" not in run.tool_calls[0].params

    if tamper_params:
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        run.steps[0].params["valid_rows_only"] = False
        with pytest.raises(ApprovalGrantError):
            validate_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        assert executor.execute_with_deadline.call_count == 1
        return

    run = _approve_and_execute(orchestrator, run, actor)
    assert executor.execute_with_deadline.call_count == 2, (
        run.status,
        run.error,
        [(event.event_type, event.message, event.data) for event in run.events[-4:]],
    )
    second_params = executor.execute_with_deadline.call_args_list[1].args[0].params
    assert second_params["valid_rows_only"] is True
    assert run.steps[0].status == "completed"
    assert run.steps[1].status == run.status == "waiting_user"
    assert all(call.action == "preview" for call in run.tool_calls)


def test_step_id_alone_cannot_authorize_a_paused_step(preview_actor):
    actor = preview_actor
    repo = InMemoryAgentRunRepository()
    executor = _executor({"success": True}, actor)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == run.steps[0].status == "waiting_user"
    assert run.steps[0].output["error_code"] == "approval_scope_changed"
    executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("storage", ["memory", "sql"])
def test_each_preview_decision_requires_its_own_grant_and_preserves_receipts(
    preview_actor, storage
):
    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.elt.preview_confirmation import publish_preview
    from app.db.models.elt import EltRun
    from app.infrastructure.tenant_scope import tenant_scope

    actor = preview_actor
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        row = db.get(EltRun, "run-1")
        row.draft_json = json.dumps(
            {"field_mappings": [{"source": "quantity", "target": "quantity", "confidence": 0.7}]}
        )
        publish_preview(db, row)
    outputs = []
    for decision, resume in (
        (True, {"valid_rows_only": True}),
        (True, {"accept_suggested": True}),
        (False, {}),
    ):
        outputs.append(
            _preview_output(
                {
                    "success": True,
                    "preview": True,
                    "requires_user_decision": decision,
                    "question": "核对下一项预演条件" if decision else "",
                    "resume_params": resume,
                    "data": {"executable": not decision},
                },
                actor,
            )
        )
    executor = MagicMock()
    executor.execute_with_deadline.side_effect = outputs
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=actor.factory)
        if storage == "sql"
        else InMemoryAgentRunRepository()
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    preserved = []
    for expected in range(1, 4):
        run = _approve_and_execute(orchestrator, run, actor)
        assert executor.execute_with_deadline.call_count == expected, (run.status, run.error)
        assert [call.to_dict() for call in run.tool_calls[:-1]] == preserved
        preserved = deepcopy([call.to_dict() for call in run.tool_calls])
        assert run.status == "waiting_user"
        assert run.steps[1].status in {"pending", "waiting_user"}
        assert all(call.action == "preview" for call in run.tool_calls)
        assert all(call.metadata["verification"]["accepted"] is True for call in run.tool_calls)
    assert run.steps[0].status == "completed"
    assert len({call.call_id for call in run.tool_calls}) == 3
    assert [call.metadata["attempt_count"] for call in run.tool_calls] == [1, 2, 3]
    with actor.factory() as db:
        assert (
            db.connection()
            .exec_driver_sql("SELECT executed_rows FROM elt_runs WHERE id='run-1'")
            .scalar_one()
            == 0
        )


def test_old_step_id_does_not_approve_verified_preview_continuation(preview_actor):
    actor = preview_actor
    repo = InMemoryAgentRunRepository()
    executor = _executor(
        {
            "success": True,
            "preview": True,
            "requires_user_decision": True,
            "question": "请确认只写入正确行",
            "resume_params": {"valid_rows_only": True},
            "data": {"executable": False},
        },
        actor,
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)
    original = deepcopy(run.tool_calls[0].to_dict())
    orchestrator._execute_ready_steps(
        run,
        runtime_context=actor.context,
        approved_step_id=run.steps[0].step_id,
    )
    assert executor.execute_with_deadline.call_count == 1
    assert repo.get(run.run_id).tool_calls[0].to_dict() == original
    assert run.status == "waiting_user"


def test_unknown_preview_cannot_resume_via_an_old_step_id(preview_actor):
    actor = preview_actor
    repo = InMemoryAgentRunRepository()
    executor = _executor(
        {
            "success": False,
            "preview": True,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "error_code": "original_preview_unsettled",
            "requires_user_decision": True,
            "question": "请核对原预演",
            "resume_params": {"valid_rows_only": True},
            "data": {"executable": False},
        },
        actor,
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)
    original = deepcopy(run.tool_calls[0].to_dict())
    reopened = orchestrator.execute_dispatched_run(run.run_id, recovered=True)
    assert executor.execute_with_deadline.call_count == 1
    assert reopened.tool_calls[0].to_dict() == original
    assert reopened.metadata["non_retryable"] is True
    assert reopened.tool_calls[0].metadata["verification"]["accepted"] is False


def _read_preview(actor, *, params=None, output=None):
    from app.application.agent_orchestrator.result_verification import (
        bind_execution_receipt,
        freeze_verification_contract,
        verify_step_result,
    )
    from app.application.agent_orchestrator.run_models import ToolCall
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    run = _run(actor)
    step = run.steps[0]
    if params is not None:
        step.params = params
    step.attempt_count = 1
    step.output = output or _preview_output(
        {
            "success": True,
            "preview": True,
            "requires_user_decision": True,
            "question": "确认只处理正确行？",
            "resume_params": {"valid_rows_only": True},
            "data": {"executable": False},
        },
        actor,
    )
    call = ToolCall(
        step.step_id,
        step.node_id,
        step.tool_id,
        step.action,
        params=deepcopy(step.params),
        output=deepcopy(step.output),
        status="completed",
        metadata={"attempt_count": 1},
    )
    run.tool_calls = [call]
    context = {
        **actor.context,
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
    }
    freeze_verification_contract(
        run, step, call, get_tool_action_spec("elt_import", "preview"), context
    )
    bind_execution_receipt(call)
    before = deepcopy(call.output)
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert call.output == before
    return report


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "rows",
        "count",
        "owner",
        "tenant",
        "revision",
        "resume",
        "executable",
        "batch",
        "linked_parent",
        "linked_child",
        "linked_child_details",
        "session_revoked",
    ],
)
def test_preview_readback_refuses_changed_or_unbound_evidence(preview_actor, change):
    from app.db.models.elt import EltRun, EltRunRow
    from app.db.models.user import Session as UserSession
    from app.infrastructure.tenant_scope import tenant_scope

    actor = preview_actor
    output = _preview_output(
        {
            "success": True,
            "preview": True,
            "requires_user_decision": True,
            "question": "确认只处理正确行？",
            "resume_params": {"valid_rows_only": True},
            "data": {"executable": False},
        },
        actor,
    )
    params = {"file_path": actor.preview_upload_id}
    if change == "source":
        actor.preview_path.write_text("changed source", encoding="utf-8")
    elif change == "revision":
        output["data"]["preview_revision"] = "0" * 64
    elif change == "resume":
        output["resume_params"]["file_path"] = "another-upload"
    elif change == "executable":
        output["data"]["executable"] = True
    elif change == "batch":
        params = {"file_paths": [actor.preview_upload_id]}
    else:
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            row = db.get(EltRun, "run-1")
            if change == "rows":
                db.query(EltRunRow).filter_by(
                    run_id=row.id, final_action="new"
                ).one().source_json = '{"changed":true}'
            elif change == "count":
                row.new_rows += 1
            elif change == "owner":
                row.owner_user_id += 100
            elif change == "tenant":
                row.tenant_id += 100
            elif change == "linked_parent":
                details = json.loads(row.summary_json)
                details["linked_customer_products_preview"] = {"run_id": "another-run"}
                row.summary_json = json.dumps(details)
            elif change == "linked_child":
                row.draft_json = '{"linked_preview":{"parent_run_id":"another-run"}}'
            elif change == "linked_child_details":
                details = json.loads(row.summary_json)
                details["linked_from_shipment_preview"] = "another-run"
                row.summary_json = json.dumps(details)
            else:
                db.delete(db.get(UserSession, actor.session_row_id))
    report = _read_preview(actor, params=params, output=output)
    assert report["accepted"] is False
    assert report["status"] in {"inconclusive", "failed"}
    with actor.factory() as db:
        row = (
            db.connection()
            .exec_driver_sql(
                "SELECT confirmed_at, executed_at, executed_rows FROM elt_runs WHERE id='run-1'"
            )
            .one()
        )
        assert tuple(row) == (None, None, 0)


@pytest.mark.parametrize("forged", [False, True])
def test_existing_preview_is_a_read_without_continuation_authority(preview_actor, forged):
    actor = preview_actor
    output = _preview_output(
        {
            "success": True,
            "preview": True,
            "data": {"preview_only": True, "requires_user_confirmation": True},
        },
        actor,
    )
    if forged:
        output.update(
            requires_user_decision=True,
            question="Change the input",
            resume_params={"file_path": "another-upload"},
        )
    report = _read_preview(actor, params={"run_id": "run-1"}, output=output)
    assert report["accepted"] is (not forged)
    if not forged:
        evidence = report["checks"][0]["evidence"]
        assert evidence["verification_scope"] == "preview_snapshot"
        assert evidence["business_effect_verified"] is False


def test_preview_readback_restores_original_mod_scope(preview_actor, monkeypatch):
    from contextlib import contextmanager

    from app.infrastructure.auth import agent_mod_scope
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    original_scope = agent_mod_scope.agent_mod_execution_scope
    observed = []

    @contextmanager
    def checked_scope(binding):
        observed.append((get_request_active_mod_id(), binding))
        with original_scope(binding):
            yield

    monkeypatch.setattr(agent_mod_scope, "agent_mod_execution_scope", checked_scope)
    token = set_request_active_mod_id("unrelated-current-mod")
    try:
        report = _read_preview(preview_actor)
        assert report["accepted"] is True
        assert observed == [("", preview_actor.context.get("_mod_authorization"))]
        assert get_request_active_mod_id() == "unrelated-current-mod"
    finally:
        reset_request_active_mod_id(token)
