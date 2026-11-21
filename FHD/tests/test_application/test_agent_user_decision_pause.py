"""工具返回 requires_user_decision 时，编排应停下询问用户而不是记为异常。"""

from __future__ import annotations

import copy
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.application.agent_orchestrator import (
    InMemoryAgentRunRepository,
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    consume_approval_grant,
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import (
    ApprovalRequest,
    ApprovalStatus,
    PlanGraph,
    WorkflowNode,
    plan_fingerprint,
    plan_from_dict,
    plan_to_dict,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def native_preview(tmp_path):
    """Real owned upload, rows and published preview; only dispatch is substituted."""
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


def _run(actor) -> AgentRun:
    preview = AgentStep(
        node_id="elt_preview",
        tool_id="elt_import",
        action="preview",
        params={"file_path": "@uploads/宗南.xlsx"},
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


def _executor(output: dict) -> MagicMock:
    executor = MagicMock()
    executor.execute_with_deadline.return_value = dict(output)
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


def test_preview_blocker_pauses_run_instead_of_failing(trusted_actor, native_preview):
    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    executor = _executor(native_preview(actor))
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
    verification = run.tool_calls[0].metadata["verification"]
    assert verification["code"] == "verified_elt_preview_admission"
    assert verification["checks"][0]["evidence"]["business_effect_verified"] is False


@pytest.mark.parametrize("tamper_params", [False, "step", "plan", "proposal", "both", "remove"])
@pytest.mark.parametrize("backend", ["memory", "sql"])
def test_approved_pause_reruns_step_with_resume_params(
    trusted_actor, native_preview, tamper_params, backend
):
    actor = trusted_actor(role="admin")
    repo = (
        InMemoryAgentRunRepository()
        if backend == "memory"
        else SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    )
    pause_output = native_preview(actor)
    resume_output = native_preview(actor, executable=True)
    executor = MagicMock()
    executor.execute_with_deadline.side_effect = [dict(pause_output), dict(resume_output)]
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)
    assert run.status == "waiting_user"
    assert executor.execute_with_deadline.call_count == 1
    assert run.steps[0].params["valid_rows_only"] is True
    assert run.metadata["plan"]["nodes"][0]["params"]["valid_rows_only"] is True
    assert "valid_rows_only" not in run.tool_calls[0].params
    original = copy.deepcopy(run.tool_calls[0].to_dict())
    original["metadata"].pop("verification")

    if tamper_params:
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        validate_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        if tamper_params in {"step", "both"}:
            run.steps[0].params["valid_rows_only"] = False
        if tamper_params == "plan":
            run.metadata["plan"]["nodes"][0]["params"]["valid_rows_only"] = False
        if tamper_params in {"proposal", "both"}:
            run.steps[0].output["resume_params"]["valid_rows_only"] = False
        if tamper_params == "remove":
            run.steps[0].output.pop("resume_params")
        with pytest.raises(ApprovalGrantError):
            validate_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        assert executor.execute_with_deadline.call_count == 1
        return

    run = _approve_and_execute(orchestrator, run, actor)
    assert executor.execute_with_deadline.call_count == 2
    second_params = executor.execute_with_deadline.call_args_list[1].args[0].params
    assert second_params["valid_rows_only"] is True
    assert run.steps[0].status == "completed"
    assert run.steps[1].status == run.status == "waiting_user"
    assert all(call.action == "preview" for call in run.tool_calls)
    retained = copy.deepcopy(run.tool_calls[0].to_dict())
    retained["metadata"].pop("verification")
    assert retained == original
    assert run.steps[1].output == {}, "预演核验不能变成业务写入成功"


def _corrupt_native_preview(actor, receipt, change):
    from pathlib import Path

    from app.application.elt.preview_confirmation import publish_preview
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.models.elt import EltRun, EltRunRow, EltUpload
    from app.domain.shared_services.tools_workflow_elt import _summary
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        native = db.get(EltRun, receipt["data"]["run_id"])
        if change == "missing":
            receipt["data"]["run_id"] = "forged-preview"
        elif change in {"owner", "tenant"}:
            setattr(native, "owner_user_id" if change == "owner" else "tenant_id", 999999)
        elif change == "source":
            Path(db.get(EltUpload, native.upload_id).storage_path).write_bytes(b"changed source")
        elif change == "manifest":
            db.query(EltRunRow).filter_by(
                run_id=native.id, final_action="new"
            ).one().normalized_json = '{"name":"unreviewed change"}'
        elif change == "operation":
            native.operation_kind, native.operation_token = "execute", "live-owner"
        elif change == "unknown":
            native.receipt_json = '{"outcome":"unknown","reconciliation_required":true}'
        elif change == "decision":
            native.error_rows, native.skip_rows = 0, 1
            db.query(EltRunRow).filter_by(
                run_id=native.id, final_action="error"
            ).one().final_action = "skip"
            publish_preview(db, native)
            receipt["data"].update(_summary(HistoryServiceMixin().run_dict(native)))


@pytest.mark.parametrize(
    "change",
    ["missing", "owner", "tenant", "source", "manifest", "operation", "unknown", "decision"],
)
def test_unproven_user_decision_never_authorizes_wait_or_replay(
    trusted_actor, native_preview, change
):
    actor = trusted_actor(role="admin")
    receipt = native_preview(actor)
    _corrupt_native_preview(actor, receipt, change)
    repo = InMemoryAgentRunRepository()
    executor = _executor(receipt)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    result = _approve_and_execute(orchestrator, run, actor)
    assert result.status == "blocked"
    assert result.steps[1].status == "pending"
    assert result.tool_calls[0].params == {"file_path": "@uploads/宗南.xlsx"}
    assert result.steps[0].output == result.tool_calls[0].output == receipt
    assert result.tool_calls[0].metadata["verification"]["accepted"] is False
    with pytest.raises(ApprovalGrantError):
        issue_approval_grant(result, principal_id=str(actor.user_id))
    for _ in range(2):
        assert (
            orchestrator.continue_run(
                result.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
            ).status
            == "blocked"
        )
    assert executor.execute_with_deadline.call_count == 1


@pytest.mark.parametrize("change", ["source", "manifest", "operation", "unknown"])
def test_approved_continuation_rechecks_native_preview_without_replaying(
    trusted_actor, native_preview, change
):
    actor = trusted_actor(role="admin")
    receipt = native_preview(actor)
    repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    executor = _executor(receipt)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    paused = _approve_and_execute(orchestrator, run, actor)
    assert paused.status == "waiting_user"
    _corrupt_native_preview(actor, receipt, change)
    result = _approve_and_execute(orchestrator, paused, actor)
    assert result.status == "blocked"
    assert result.tool_calls[0].output == receipt
    assert len(result.tool_calls) == executor.execute_with_deadline.call_count == 1
    assert result.steps[1].status == "pending"


def test_step_id_alone_cannot_authorize_a_paused_step(trusted_actor):
    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    executor = _executor({"success": True})
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    repo.save(run)
    orchestrator._execute_ready_steps(
        run, runtime_context=actor.context, approved_step_id=run.steps[0].step_id
    )
    assert run.status == run.steps[0].status == "waiting_user"
    assert run.steps[0].output["error_code"] == "approval_scope_changed"
    executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("backend", ["memory", "sql"])
def test_invalid_resume_params_preserve_executed_receipt_and_never_rerun(
    trusted_actor, native_preview, backend
):
    actor = trusted_actor(role="admin")
    repo = (
        InMemoryAgentRunRepository()
        if backend == "memory"
        else SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    )
    receipt = native_preview(actor, resume_params={"valid_rows_only": "not-a-boolean"})
    executor = _executor(receipt)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    run = _run(actor)
    original = copy.deepcopy(run.steps[0].params)
    repo.save(run)
    run = _approve_and_execute(orchestrator, run, actor)

    assert run.status == "blocked"
    assert run.steps[0].params == run.metadata["plan"]["nodes"][0]["params"] == original
    assert run.steps[0].output == run.tool_calls[0].output == receipt
    assert run.tool_calls[0].status == "completed"
    assert run.tool_calls[0].params == original
    assert run.steps[1].status == "pending"
    with pytest.raises(ApprovalGrantError):
        issue_approval_grant(run, principal_id=str(actor.user_id))
    for _ in range(2):
        continued = orchestrator.continue_run(
            run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
        )
        assert continued.status == "blocked"
        assert continued.tool_calls[0].to_dict() == run.tool_calls[0].to_dict()
    assert executor.execute_with_deadline.call_count == 1


def test_frozen_approval_cannot_authorize_proposed_resume_params(
    trusted_actor, native_preview, monkeypatch
):
    from app.application.workflow.approval_persistence import (
        claim_agent_approval,
        load_workflow_snapshot_for_execution,
        mark_durable_request_approved_and_load,
        persist_agent_run_link,
        persist_workflow_approval,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    executor = _executor(native_preview(actor))
    run = _run(actor)
    run.steps[0].risk = run.metadata["plan"]["nodes"][0]["risk"] = "high"
    run.metadata["plan"]["metadata"]["approval_required_node_ids"] = ["elt_preview"]
    plan = plan_from_dict(run.metadata["plan"])
    request = ApprovalRequest(
        "original-preview",
        plan.plan_id,
        "elt_preview",
        "elt_import",
        "preview",
        copy.deepcopy(run.steps[0].params),
        ApprovalStatus.PENDING,
        datetime.now(UTC),
        tenant_id=actor.tenant_id,
    )
    repo.save(run)
    checkpoints = []
    save = repo.save

    def capture_receipt(value):
        stored = save(value)
        if value.tool_calls and value.steps[0].status == "waiting_user":
            checkpoints.append(copy.deepcopy(stored))
        return stored

    monkeypatch.setattr(repo, "save", capture_receipt)
    with tenant_scope(actor.tenant_id):
        assert persist_workflow_approval(request, actor.context, flow_key="resume-test", plan=plan)
        assert persist_agent_run_link(
            request.request_id, agent_run_id=run.run_id, approved_step_id=run.steps[0].step_id
        )
        assert mark_durable_request_approved_and_load(request.request_id)
        assert claim_agent_approval(
            request.request_id, agent_run_id=run.run_id, approved_step_id=run.steps[0].step_id
        )
        assert load_workflow_snapshot_for_execution(request.request_id)
        _approve_and_execute(AgentOrchestrator(repository=repo, tool_executor=executor), run, actor)

        # A restart can observe the receipt committed before continuation preparation.
        checkpoint = checkpoints[0]
        assert "valid_rows_only" not in checkpoint.steps[0].params
        original_receipt = checkpoint.tool_calls[0].to_dict()
        recovered = InMemoryAgentRunRepository()
        recovered.save(checkpoint)
        orchestrator = AgentOrchestrator(repository=recovered, tool_executor=executor)
        result = orchestrator.continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            approved_step_id=run.steps[0].step_id,
            approval_request_id=request.request_id,
            runtime_context=actor.context,
        )

    assert result.status == "blocked"
    assert result.events[-1].event_type == "approval.resume_proof_missing"
    assert result.steps[0].params["valid_rows_only"] is True
    assert result.metadata["plan_sha256"] == plan_fingerprint(
        plan_from_dict(result.metadata["plan"])
    )
    assert result.tool_calls[0].to_dict() == original_receipt
    assert result.steps[1].status == "pending"
    assert executor.execute_with_deadline.call_count == 1


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


def parallel_run(actor) -> AgentRun:
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


def parallel_executor(output: dict, actor) -> MagicMock:
    executor = MagicMock()
    executor.execute_with_deadline.return_value = _preview_output(output, actor)
    return executor


def parallel_approve_and_execute(orchestrator, run, actor):
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
    run = parallel_run(actor)
    repo.save(run)
    preserved = []
    for expected in range(1, 4):
        run = parallel_approve_and_execute(orchestrator, run, actor)
        assert executor.execute_with_deadline.call_count == expected, (run.status, run.error)
        observed_receipts = deepcopy([call.to_dict() for call in run.tool_calls[:-1]])
        prior_receipts = deepcopy(preserved)
        for previous, observed in zip(prior_receipts, observed_receipts, strict=True):
            old_report = previous["metadata"]["verification"]
            report = observed["metadata"]["verification"]
            assert report["verification_attempt"] >= old_report["verification_attempt"]
            # Fresh readback has its own observation identity; original execution,
            # frozen scope and evidence remain byte-for-byte equivalent.
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash

            assert report["report_sha256"] == canonical_hash(
                {key: value for key, value in report.items() if key != "report_sha256"}
            )
            for key in ("verification_attempt", "observed_at", "report_sha256"):
                old_report.pop(key)
                report.pop(key)
        assert observed_receipts == prior_receipts
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
    executor = parallel_executor(
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
    run = parallel_run(actor)
    repo.save(run)
    run = parallel_approve_and_execute(orchestrator, run, actor)
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
    executor = parallel_executor(
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
    run = parallel_run(actor)
    repo.save(run)
    run = parallel_approve_and_execute(orchestrator, run, actor)
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

    run = parallel_run(actor)
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
        params = {"file_paths": [actor.preview_upload_id, "unbound-upload"]}
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
        assert evidence["preview_only"] is True
        assert evidence["previews"][0]["run_id"] == "run-1"
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
        assert observed == [("", preview_actor.context.get("_mod_authorization"))] * 2
        assert get_request_active_mod_id() == "unrelated-current-mod"
    finally:
        reset_request_active_mod_id(token)
