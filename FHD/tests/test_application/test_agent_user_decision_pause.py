"""工具返回 requires_user_decision 时，编排应停下询问用户而不是记为异常。"""

from __future__ import annotations

import copy
import hashlib
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.task_background import apply_approved_step
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _approve_and_execute(orchestrator, run, actor):
    """Approve the frozen step with its actual actor-bound grant, then dispatch it."""
    from app.application.agent_orchestrator.approval_grant import (
        consume_approval_grant,
        issue_approval_grant,
    )

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


@pytest.fixture
def native_preview(tmp_path):
    """Real owned upload, rows and published preview; only dispatch is substituted."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.application.elt.preview_confirmation import publish_preview
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.models.elt import EltRun, EltRunRow, EltUpload
    from app.domain.shared_services.tools_workflow_elt import _summary
    from app.infrastructure.tenant_scope import tenant_scope

    def receipt(actor, *, executable=False, file_name="宗南.xlsx", **overrides):
        path = tmp_path / file_name
        path.write_bytes(b"name,weight\nvalid,5\ninvalid,\n")
        upload_id = hashlib.sha256(file_name.encode()).hexdigest()[:32]
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            upload = db.get(EltUpload, upload_id)
            if upload is None:
                upload = EltUpload(
                    id=upload_id,
                    tenant_id=actor.tenant_id,
                    owner_user_id=actor.user_id,
                    file_name=path.name,
                    suffix=".xlsx",
                    storage_path=str(path),
                    size_bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
                db.add(upload)
                db.flush()
            native = EltRun(
                id=uuid4().hex,
                tenant_id=actor.tenant_id,
                owner_user_id=actor.user_id,
                upload_id=upload.id,
                file_sha256=upload.sha256,
                target_type="customers",
                status="preview_ready",
                stage="preview_ready",
                total_rows=2,
                new_rows=1,
                error_rows=1,
            )
            db.add(native)
            db.flush()
            for row, action in ((2, "new"), (18, "error")):
                db.add(
                    EltRunRow(
                        run_id=native.id,
                        tenant_id=actor.tenant_id,
                        owner_user_id=actor.user_id,
                        source_row=row,
                        source_sheet="宗南",
                        final_action=action,
                        normalized_json='{"name":"owned preview row"}',
                        after_json='{"name":"owned preview row"}' if action == "new" else "{}",
                    )
                )
            publish_preview(db, native)
            data = _summary(HistoryServiceMixin().run_dict(native))
        data.update(executable=executable, mapping_pending=[])
        return {
            "success": True,
            "preview": True,
            "data": data,
            "requires_user_decision": not executable,
            "question": "预演完成：第18行（宗南）数据未通过校验，仅继续有效行？"
            if not executable
            else "",
            "resume_params": {"valid_rows_only": True} if not executable else {},
            **overrides,
        }

    return receipt


@pytest.fixture
def preview_evidence(trusted_actor, tmp_path):
    from app.application.elt.preview_confirmation import publish_preview
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.models.elt import EltRun, EltRunRow, EltUpload
    from app.domain.shared_services.tools_workflow_elt import _summary
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    actor = trusted_actor(permissions=["elt.execute"])
    source = tmp_path / "source.csv"
    source.write_bytes(b"name,quantity\nZongnan,\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.add(
            EltUpload(
                id="upload-1",
                owner_user_id=actor.user_id,
                tenant_id=actor.tenant_id,
                file_name="source.csv",
                suffix=".csv",
                size_bytes=source.stat().st_size,
                sha256=digest,
                storage_path=str(source),
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
        db.flush()
        row = EltRun(
            id="run-1",
            owner_user_id=actor.user_id,
            tenant_id=actor.tenant_id,
            upload_id="upload-1",
            target_type="customers",
            status="preview_ready",
            stage="preview_ready",
            file_sha256=digest,
            total_rows=1,
            error_rows=1,
        )
        db.add(row)
        db.flush()
        db.add(
            EltRunRow(
                run_id=row.id,
                owner_user_id=actor.user_id,
                tenant_id=actor.tenant_id,
                source_sheet="宗南",
                source_row=18,
                final_action="error",
            )
        )
        db.flush()
        publish_preview(db, row)
        data = _summary(HistoryServiceMixin().run_dict(row))
    return actor, data


def _run(actor) -> AgentRun:
    preview = AgentStep(
        node_id="elt_preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "upload-1"},
        risk="medium",
        idempotent=False,
    )
    execute = AgentStep(
        node_id="elt_execute",
        tool_id="elt_import",
        action="execute",
        params={
            "run_id": "{{elt_preview.data.run_id}}",
            "preview_revision": "{{elt_preview.data.preview_revision}}",
        },
        risk="high",
        idempotent=False,
        depends_on=["elt_preview"],
    )
    run = AgentRun(user_id=str(actor.user_id), message="导入宗南.xlsx", status="running")
    run.metadata.update(
        cost_units_total=0, ai_cost_units_total=0, runtime_context=dict(actor.context)
    )
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
    apply_approved_step(run, preview, approved_by=str(actor.user_id))
    return run


def _executor(output: dict) -> MagicMock:
    executor = MagicMock()
    executor.execute_with_deadline.return_value = dict(output)
    return executor


def test_preview_blocker_pauses_run_instead_of_failing(preview_evidence):
    actor, data = preview_evidence
    repo = InMemoryAgentRunRepository()
    executor = _executor(
        {
            "success": True,
            "preview": True,
            "message": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "requires_user_decision": True,
            "resume_params": {"valid_rows_only": True},
            "question": "预演完成：1 行源数据未通过校验（第18行（宗南）：公斤数或桶数至少填写一项）。",
            "data": {**data, "executable": False},
        }
    )
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)

    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )

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


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
def test_approved_pause_reruns_step_with_resume_params(preview_evidence, storage):
    actor, data = preview_evidence
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    repo = (
        InMemoryAgentRunRepository()
        if storage == "memory"
        else SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    )
    pause_output = {
        "success": True,
        "preview": True,
        "message": "预演有 1 行错误",
        "requires_user_decision": True,
        "question": "预演有 1 行错误",
        "resume_params": {"valid_rows_only": True},
        "data": {**data, "executable": False},
    }
    resume_output = {
        "success": True,
        "preview": True,
        "message": "预演完成",
        "requires_user_decision": False,
        "data": {**data, "executable": True},
    }
    executor = MagicMock()
    executor.execute_with_deadline.side_effect = [dict(pause_output), dict(resume_output)]
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)

    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "waiting_user"
    original = copy.deepcopy(run.tool_calls[0])

    run.status = "running"
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "waiting_user"
    assert any(event.event_type == "approval.scope_changed" for event in run.events)
    assert run.steps[0].output == run.tool_calls[0].output == pause_output
    assert executor.execute_with_deadline.call_count == 1
    # The proposed valid-rows-only parameters need their own approval scope.
    run = orchestrator.continue_run(
        run.run_id,
        approved_by=str(actor.user_id),
        runtime_context=actor.context,
        approved_step_id=run.steps[0].step_id,
    )
    assert run is not None

    second_params = executor.execute_with_deadline.call_args_list[1].args[0].params
    assert second_params["valid_rows_only"] is True
    assert run.steps[1].depends_on == ["elt_preview"]
    assert run.steps[1].params == {
        "run_id": data["run_id"],
        "preview_revision": data["preview_revision"],
    }
    assert len(run.tool_calls) == 2
    retained, resumed = repo.get(run.run_id).tool_calls
    assert retained.params == original.params and retained.output == original.output
    for key in ("verification_contract", "verification_output_sha256", "idempotency_key"):
        assert retained.metadata[key] == original.metadata[key]
        assert resumed.metadata[key] != original.metadata[key]


@pytest.mark.parametrize(
    "change", ["revision", "tenant", "executed", "source", "extra_control", "numeric_control"]
)
def test_unverified_preview_cannot_supply_a_resume_proposal(preview_evidence, tmp_path, change):
    actor, data = preview_evidence
    output = {
        "success": True,
        "preview": True,
        "requires_user_decision": True,
        "question": "confirm",
        "resume_params": {"valid_rows_only": True},
        "data": {**data, "executable": False},
        "verification": {"verified": True, "status": "verified", "scope": "preview_only"},
    }
    if change == "revision":
        output["data"]["preview_revision"] = "0" * 64
    elif change == "source":
        (tmp_path / "source.csv").write_bytes(b"changed")
    elif change in {"tenant", "executed"}:
        with actor.factory.begin() as db:
            db.connection().exec_driver_sql(
                "update elt_runs set tenant_id = 99 where id = 'run-1'"
                if change == "tenant"
                else "update elt_runs set executed_rows = 1 where id = 'run-1'"
            )
    elif change == "extra_control":
        output["resume_params"]["file_path"] = "another-upload"
    else:
        output["resume_params"]["valid_rows_only"] = 1
    executor = _executor(output)
    repo = InMemoryAgentRunRepository()
    run = _run(actor)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "blocked"
    assert run.tool_calls[0].metadata["verification"]["accepted"] is False
    assert run.tool_calls[0].output["verification"]["verified"] is True
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert executor.execute_with_deadline.call_count == 1


@pytest.mark.parametrize("extra", [{"accept_suggested": True}, {"file_path": "another-upload"}])
def test_fresh_approval_does_not_authorize_unproposed_preview_parameters(preview_evidence, extra):
    actor, data = preview_evidence
    executor = _executor(
        {
            "success": True,
            "preview": True,
            "requires_user_decision": True,
            "question": "confirm",
            "resume_params": {"valid_rows_only": True},
            "data": {**data, "executable": False},
        }
    )
    repo = InMemoryAgentRunRepository()
    run = _run(actor)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "waiting_user"
    original = copy.deepcopy(run.tool_calls[0])
    run.steps[0].params.update(extra)
    from app.application.agent_orchestrator.approval_grant import ApprovalGrantError

    with pytest.raises(ApprovalGrantError, match="续跑参数尚未绑定到当前完整计划"):
        apply_approved_step(run, run.steps[0], approved_by=str(actor.user_id))
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == "blocked"
    assert executor.execute_with_deadline.call_count == 1
    assert run.tool_calls[0].to_dict() == original.to_dict()
