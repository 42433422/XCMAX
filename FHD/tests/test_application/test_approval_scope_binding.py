"""An approval authorizes the displayed scope and tool contract until either changes."""

from dataclasses import replace

import pytest

from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    execution_scope_claims,
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def pending_approval():
    run = AgentRun(
        user_id="7",
        message="create an approved customer",
        status="waiting_user",
        steps=[
            AgentStep(
                node_id="create",
                tool_id="customers",
                action="create",
                params={"unit_name": "Approval scope test"},
                status="waiting_user",
            )
        ],
        metadata={
            "runtime_context": {
                "user_id": "7",
                "actor_id": "7",
                "tenant_id": "11",
                "mod_id": "customer-tools",
                "employee_id": "employee-a",
                "employee_tool_allowlist": ["customers.create"],
                "_actor_authorization": {
                    "session_row_id": 1,
                    "proof": "original-session-proof",
                    "user_id": "7",
                    "tenant_id": "11",
                    "execution_tenant_id": "11",
                    "role": "employee",
                    "tier": "enterprise",
                    "mod_id": "customer-tools",
                },
                "_mod_authorization": {
                    "session_row_id": 1,
                    "user_id": "7",
                    "mod_id": "customer-tools",
                    "account_tenant_id": "11",
                    "account_role": "employee",
                },
            }
        },
    )
    token = issue_approval_grant(run, principal_id="7")["grant"]
    return run, token


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "22"),
        ("user_id", "8"),
        ("actor_id", "8"),
        ("mod_id", "other-mod"),
        ("active_mod_id", "other-mod"),
        ("employee_id", "employee-b"),
        ("employee_tool_allowlist", ["customers"]),
        ("employee_tool_allowlist", []),
        ("mutation_policy", "allow_once"),
        ("_bulk_preview_scope", {"tool": "customers", "digest": "replacement"}),
        ("_bulk_preview_scopes", {"customers": "replacement"}),
    ],
)
def test_scope_change_requires_new_approval(pending_approval, field, value):
    run, token = pending_approval
    run.metadata["runtime_context"][field] = value

    with pytest.raises(ApprovalGrantError):
        validate_approval_grant(token, run=run, principal_id="7")


@pytest.mark.parametrize(
    "binding,field,value",
    [
        ("_actor_authorization", "role", "admin"),
        ("_actor_authorization", "execution_tenant_id", "22"),
        ("_actor_authorization", "tier", "admin"),
        ("_mod_authorization", "mod_id", "other-mod"),
        ("_mod_authorization", "account_role", "admin"),
    ],
)
def test_authority_change_requires_new_approval(pending_approval, binding, field, value):
    run, token = pending_approval
    run.metadata["runtime_context"][binding][field] = value

    with pytest.raises(ApprovalGrantError):
        validate_approval_grant(token, run=run, principal_id="7")


@pytest.mark.parametrize(
    "change",
    [
        {"version": "3"},
        {"permission": "customer.delete"},
        {"risk": "high"},
        {"owner_mod_id": "replacement-mod"},
        {"read_only": True},
        {"input_schema": {"type": "object", "required": ["replacement_target"]}},
        {"output_schema": {"type": "object", "required": ["verified_receipt"]}},
        {"retry": {"max_attempts": 7}},
        {"timeout_seconds": 1},
        {"availability": "owned"},
    ],
)
def test_tool_contract_change_requires_new_approval(pending_approval, monkeypatch, change):
    from app.application.agent_orchestrator import tool_spec

    run, token = pending_approval
    current = tool_spec.get_tool_action_spec("customers", "create")
    assert any(getattr(current, key) != value for key, value in change.items())
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: replace(current, **change))

    with pytest.raises(ApprovalGrantError):
        validate_approval_grant(token, run=run, principal_id="7")


def test_same_scope_session_renewal_keeps_approval(pending_approval):
    run, token = pending_approval
    context = run.metadata["runtime_context"]
    context["_actor_authorization"].update(session_row_id=2, proof="renewed-session-proof")
    context["_mod_authorization"]["session_row_id"] = 2
    context["message"] = "continue the approved operation"

    assert validate_approval_grant(token, run=run, principal_id="7")["run_id"] == run.run_id


def test_grant_id_is_stable_for_the_same_scope_and_changes_with_reapproval(
    pending_approval,
):
    run, token = pending_approval
    original = validate_approval_grant(token, run=run, principal_id="7")["jti"]
    same = issue_approval_grant(run, principal_id="7")["grant"]
    assert validate_approval_grant(same, run=run, principal_id="7")["jti"] == original
    run.metadata["runtime_context"]["employee_id"] = "employee-b"
    changed = issue_approval_grant(run, principal_id="7")["grant"]
    assert validate_approval_grant(changed, run=run, principal_id="7")["jti"] != original


def test_effective_server_workspace_is_bound_and_changes_require_reapproval(
    pending_approval, monkeypatch, tmp_path
):
    run, _token = pending_approval
    run.metadata["runtime_context"]["workspace_root"] = "stale-persisted-root"
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "first"))
    token = issue_approval_grant(run, principal_id="7")["grant"]
    run.metadata["runtime_context"]["workspace_root"] = str(tmp_path / "first")
    assert validate_approval_grant(token, run=run, principal_id="7")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "second"))
    with pytest.raises(ApprovalGrantError):
        validate_approval_grant(token, run=run, principal_id="7")


def test_executor_rechecks_approved_contract_before_each_attempt(pending_approval, monkeypatch):
    from app.application.agent_orchestrator import tool_spec
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    run, _token = pending_approval
    step = run.steps[0]
    context = dict(run.metadata["runtime_context"])
    context["_tool_approval_scope"] = {
        "tool_id": step.tool_id,
        "action": step.action,
        **execution_scope_claims(context, step.tool_id, step.action),
    }
    current = tool_spec.get_tool_action_spec(step.tool_id, step.action)
    monkeypatch.setattr(
        tool_spec, "get_tool_action_spec", lambda *_: replace(current, version="new")
    )
    denial = actor_tool_denial(step.tool_id, step.action, context, step.params)
    assert denial["error_code"] == "approval_scope_changed" and denial["retryable"] is False


@pytest.mark.parametrize(
    "drift",
    [None, "employee", "contract", "legacy_receipt", "params_after_first_attempt"],
)
def test_queued_approval_and_retry_do_not_execute_after_scope_drift(monkeypatch, tmp_path, drift):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import AgentOrchestrator, tool_spec
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    calls = []

    def execute(step, **_):
        calls.append(dict(step.params))
        return {
            "success": drift != "params_after_first_attempt",
            "data": {"id": 7},
            "retryable": drift == "params_after_first_attempt",
        }

    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(
        repository=repo, tool_executor=SimpleNamespace(execute=execute)
    )
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="write one customer",
        runtime_context={"tenant_id": "11", "employee_id": "employee-a"},
        plan=PlanGraph(
            plan_id="approved-write",
            intent="test",
            nodes=[
                WorkflowNode(
                    node_id="write",
                    tool_id="business_db",
                    action="write",
                    params={
                        "entity": "customers",
                        "operation": "create",
                        "payload": {"customer_name": "approved"},
                    },
                )
            ],
        ),
    )
    assert run.status == "waiting_user" and not calls
    grant = issue_approval_grant(run, principal_id="owner")["grant"]
    claims = validate_approval_grant(grant, run=run, principal_id="owner")
    queued = orchestrator.stage_approved_run(
        run.run_id,
        approved_by="owner",
        approved_step_id=run.steps[0].step_id,
        approval_claims=claims,
    )
    assert queued.status == "queued"
    assert (
        queued.metadata["approval_receipt"]["authorization_scope_sha256"]
        == claims["authorization_scope_sha256"]
    )
    if drift == "employee":
        queued.metadata["runtime_context"]["employee_id"] = "employee-b"
        repo.save(queued)
    elif drift == "contract":
        original = tool_spec.get_tool_action_spec
        monkeypatch.setattr(
            tool_spec,
            "get_tool_action_spec",
            lambda tool, action: replace(original(tool, action), version="new"),
        )
    elif drift == "legacy_receipt":
        queued.metadata["approval_receipt"].pop("authorization_scope_sha256")
        repo.save(queued)
    elif drift == "params_after_first_attempt":

        def repair(_run, step, **_):
            step.params["payload"]["customer_name"] = "unapproved replacement"
            return True

        monkeypatch.setattr(orchestrator, "_prepare_repair_or_retry", repair)
    finished = orchestrator.execute_dispatched_run(run.run_id)
    if drift is None:
        assert finished.status == "blocked" and len(calls) == 1, (
            finished.error,
            [step.output for step in finished.steps],
        )
        assert finished.steps[0].output["success"] is True
        assert (
            finished.tool_calls[0].metadata["verification"]["code"] == "result_verifier_unavailable"
        )
    else:
        assert finished.status == "waiting_user", (
            finished.error,
            [step.output for step in finished.steps],
        )
        assert finished.steps[0].output["error_code"] == "approval_scope_changed"
        assert len(calls) == (1 if drift == "params_after_first_attempt" else 0)


@pytest.mark.parametrize(
    "drift", [None, "mod", "employee_allowlist", "legacy_scope", "permission_revoked"]
)
@pytest.mark.parametrize("entry", ["plan", "task"])
def test_existing_plan_result_is_bound_to_scope_and_live_permission(
    trusted_actor, monkeypatch, tmp_path, drift, entry
):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
    )
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        create_unified_task,
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models.permission import Role

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(
        role="scoped-reader",
        mod_id="mod-a",
        permissions=["business_db.read", "customer.view"],
    )
    context = {**actor.context, "employee_tool_allowlist": ["business_db.read"]}
    calls = []

    def execute(step, **_):
        calls.append(step.step_id)
        return {"success": True, "data": [{"private": "owned-result"}]}

    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(
        repository=repo, tool_executor=SimpleNamespace(execute=execute)
    )
    plan = PlanGraph(
        "same-plan",
        "read",
        nodes=[WorkflowNode("read", "business_db", "read", {"entity": "customers"})],
    )

    def start():
        if entry == "task":
            return create_unified_task(
                orchestrator=orchestrator,
                user_id=str(actor.user_id),
                task_id="same-task",
                title="read",
                message="read",
                tool_id="business_db",
                action="read",
                params={"entity": "customers"},
                runtime_context=context,
            ).run
        return orchestrator.start_run_from_plan(
            user_id=str(actor.user_id), message="read", plan=plan, runtime_context=context
        )

    first = start()
    if entry == "task":
        first = orchestrator.continue_run(first.run_id, approved_by=str(actor.user_id))
    assert first.status == "completed" and len(calls) == 1
    if drift == "mod":
        other = trusted_actor(user_id=actor.user_id, role="scoped-reader", mod_id="mod-b")
        context = {**other.context, "employee_tool_allowlist": ["business_db.read"]}
    elif drift == "employee_allowlist":
        context["employee_tool_allowlist"] = ["business_db"]
    elif drift == "legacy_scope":
        first.metadata.pop("execution_authorization_scope")
        repo.save(first)
    elif drift == "permission_revoked":
        with actor.factory.begin() as db:
            role = db.query(Role).filter_by(name="scoped-reader").one()
            role.permissions.clear()
    if entry == "task" and drift is not None:
        with pytest.raises(UnifiedTaskConflictError):
            start()
        assert len(calls) == 1 and repo.get(first.run_id).status == "completed"
        return
    replay = start()
    assert len(calls) == 1
    if drift is None:
        assert replay.run_id == first.run_id and replay.status == "completed"
    else:
        assert replay.status == "blocked" and replay.error == "execution_idempotency_conflict"
        assert "owned-result" not in str(replay.to_dict())
        assert repo.get(first.run_id).status == "completed"


@pytest.mark.parametrize("policy", ["block", "model_only", "allow_once"])
def test_trusted_mutation_policy_and_preview_reach_the_real_executor(
    trusted_actor, local_tools, monkeypatch, tmp_path, policy
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.tool_permission import merge_turn_context
    from app.application.chat_turn_guard import scope_snapshot
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models import Product
    from app.fastapi_routes.domains.agent.route_support import without_runtime_identity
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(role="admin")
    with actor.factory.begin() as db:
        db.add(Product(id=1, name="approved preview", tenant_id=actor.tenant_id))
    context = {**actor.context, "mutation_policy": policy}
    with tenant_scope(actor.tenant_id):
        context["_bulk_preview_scopes"] = {"products": scope_snapshot(context)[3]}
    forged = {"mutation_policy": "allow", "_bulk_preview_scopes": {"products": "forged"}}
    assert without_runtime_identity(forged) == {}
    assert merge_turn_context(context, forged)["mutation_policy"] == policy
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    orchestrator = AgentOrchestrator(repository=repo)
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="delete approved product",
        runtime_context=context,
        plan=PlanGraph(
            "approved-delete",
            "delete",
            nodes=[
                WorkflowNode(
                    "delete",
                    "products",
                    "batch_delete",
                    {"ids": [1]},
                )
            ],
        ),
    )
    assert run.status == "waiting_user"
    finished = orchestrator.continue_run(run.run_id, approved_by=str(actor.user_id))
    with actor.factory() as db:
        exists = (
            db.connection()
            .exec_driver_sql(
                "select id from products where id = 1 and tenant_id = ?", (actor.tenant_id,)
            )
            .first()
            is not None
        )
    if policy == "allow_once":
        assert finished.status == "blocked", finished.steps[0].output
        assert finished.steps[0].output["success"] is True
        assert (
            finished.tool_calls[0].metadata["verification"]["code"] == "result_verifier_unavailable"
        )
        assert exists is False
    else:
        assert finished.steps[0].output["error_code"] == "mutation_blocked"
        assert exists is True
