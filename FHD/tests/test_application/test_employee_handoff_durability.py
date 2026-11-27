"""Handoff storage/replay contracts; E25 owns the hard tool-worker acceptance."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import drop_process_idempotency_memory
from app.application.employee_runtime.handoff_commit import commit_registered_handoff
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

from .test_employee_handoff_e25 import _card, _start
from .test_employee_handoff_e25 import customers_db as customers_db


@pytest.mark.parametrize("drift", [None, "owner", "tenant", "mod", "parent", "unbound", "self"])
def test_child_attachment_requires_same_owner_tenant_and_mod(drift):
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.run_audit_scope import attach_child_result

    context = {"tenant_id": "1", "mod_id": "mod-a", "_mod_authorization": {"mod_id": "mod-a"}}
    parent = AgentRun(
        user_id="owner", message="parent", metadata={"runtime_context": copy.deepcopy(context)}
    )
    child = AgentRun(
        user_id="owner",
        message="child",
        metadata={"runtime_context": {**copy.deepcopy(context), "parent_run_id": parent.run_id}},
    )
    if drift == "owner":
        child.user_id = "other"
    elif drift == "tenant":
        child.metadata["runtime_context"]["tenant_id"] = "2"
    elif drift == "mod":
        child.metadata["runtime_context"].update(
            mod_id="mod-b", _mod_authorization={"mod_id": "mod-b"}
        )
    elif drift == "parent":
        child.metadata["runtime_context"]["parent_run_id"] = "different-parent"
    elif drift == "unbound":
        child.metadata["runtime_context"].pop("parent_run_id")
    elif drift == "self":
        child.run_id = parent.run_id
    assert attach_child_result(parent, child) is (drift is None)
    if drift:
        assert not parent.metadata.get("child_results")


def test_child_attachment_snapshot_cannot_change_with_a_live_child_result():
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.run_audit_scope import attach_child_result

    parent = AgentRun(
        user_id="owner", message="parent", metadata={"runtime_context": {"tenant_id": "1"}}
    )
    child = AgentRun(
        user_id="owner",
        message="child",
        metadata={"runtime_context": {"tenant_id": "1", "parent_run_id": parent.run_id}},
        final_output={"nested": {"value": "original"}},
    )
    assert attach_child_result(parent, child)
    child.final_output["nested"]["value"] = "later-mutation"
    assert parent.metadata["child_results"][child.run_id]["final_output"] == {
        "nested": {"value": "original"}
    }


@pytest.mark.parametrize("control", ["cancelled", "rejected", "paused"])
def test_child_projection_keeps_latest_control_over_a_pending_response(control):
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.run_audit_scope import child_result_state

    child = AgentRun(
        user_id="owner",
        message="child",
        status=control,
        final_output={"execution_state": "running", "success": False},
    )
    assert child_result_state(child) == control
    child.final_output["reconciliation_required"] = True
    assert child_result_state(child) == "unknown"


@pytest.mark.parametrize(
    "drift", [None, "owner", "tenant", "mod", "parent", "missing", "read_error"]
)
def test_parent_public_view_refreshes_bound_child_without_writing_or_replaying(drift):
    from unittest.mock import Mock

    from app.application.agent_orchestrator import AgentRun
    from app.fastapi_routes.domains.agent.route_support import public_run_dict

    context = {"tenant_id": "1", "mod_id": "mod-a", "_mod_authorization": {"mod_id": "mod-a"}}
    parent = AgentRun(
        user_id="owner",
        message="parent",
        status="completed",
        metadata={"runtime_context": copy.deepcopy(context)},
    )
    child = AgentRun(
        user_id="owner",
        message="child",
        status="running",
        metadata={"runtime_context": {**copy.deepcopy(context), "parent_run_id": parent.run_id}},
    )
    parent.metadata["child_results"] = {
        child.run_id: {"status": "completed", "final_output": {"secret": "stale-result"}}
    }
    original = copy.deepcopy(parent.to_dict())
    if drift == "owner":
        child.user_id = "other"
    elif drift == "tenant":
        child.metadata["runtime_context"]["tenant_id"] = "2"
    elif drift == "mod":
        child.metadata["runtime_context"].update(
            mod_id="mod-b", _mod_authorization={"mod_id": "mod-b"}
        )
    elif drift == "parent":
        child.metadata["runtime_context"]["parent_run_id"] = "other-parent"
    read = Mock(return_value=None if drift == "missing" else child)
    if drift == "read_error":
        read.side_effect = OSError("storage unavailable")
    view = public_run_dict(parent, read_run=read)
    result = view["metadata"]["child_results"][child.run_id]
    assert result["execution_state"] == ("unknown" if drift else "running")
    assert result["success"] is False
    assert "stale-result" not in str(result)
    assert view["status"] == "completed"
    assert parent.to_dict() == original
    read.assert_called_once_with(child.run_id)
    if drift:
        assert result["requires_reconciliation"] is True
        return
    child.status = "completed"
    child.final_output = {"message": "current-result"}
    fresh = public_run_dict(parent, read_run=read)["metadata"]["child_results"][child.run_id]
    assert fresh["success"] is True
    assert fresh["final_output"] == {"message": "current-result"}
    assert parent.to_dict() == original


@pytest.fixture
def handoff_env(customers_db, tmp_path, monkeypatch, trusted_actor):
    # Keep the real registered read and SQL repositories; isolate the tool deadline
    # boundary so these tests cannot stand in for the separate E25 process checks.
    monkeypatch.setattr(
        AgentToolExecutor,
        "execute_with_deadline",
        lambda self, step, *, runtime_context, deadline_monotonic: self.execute(
            step, runtime_context=runtime_context
        ),
    )
    actor = trusted_actor(user_id=11, tenant_id=11, role="admin")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    workspace = tmp_path / "durable-handoff"
    workspace.mkdir()
    for employee in ("employee-a", "employee-b", "employee-c"):
        _card(workspace, employee)
    task_id = _start(workspace)["task_id"]
    factory = sessionmaker(bind=customers_db, expire_on_commit=False)
    return SimpleNamespace(
        workspace=workspace,
        factory=factory,
        repository=lambda: SQLAlchemyAgentRunRepository(session_factory=factory),
        body={
            "target": "employee-b",
            "permissions": ["business_db.read"],
            "delegated_tool": "business_db",
            "delegated_action": "read",
            "delegated_params": {"entity": "customers", "keyword": "交接客户甲"},
            "idempotency_key": "handoff-1",
        },
        context={
            **actor.context,
            "tenant_id": "11",
            "user_id": "11",
            "employee_id": "employee-a",
            "task_id": task_id,
        },
    )


def _commit(env, *, body=None, context=None):
    return commit_registered_handoff(body or env.body, str(env.workspace), context or env.context)


def test_parent_child_and_receipt_survive_repository_and_claim_memory_reentry(handoff_env):
    first = _commit(handoff_env)
    assert first["success"], first
    fresh = handoff_env.repository()
    parent = fresh.get(first["parent_run_id"])
    child = fresh.get(first["child_run_id"])
    task = fresh.get_task(user_id="11", tenant_id="11", task_id=handoff_env.context["task_id"])
    assert task.root_run_id == parent.run_id
    assert parent.metadata["child_results"][child.run_id]["final_output"] == child.final_output
    assert child.metadata["runtime_context"]["parent_run_id"] == parent.run_id
    assert child.metadata["runtime_context"]["workspace_path"] == str(handoff_env.workspace)
    drop_process_idempotency_memory()
    second = _commit(handoff_env)
    assert second == first
    assert len(fresh.list_task_runs(user_id="11", task_id=task.task_id)) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"delegated_params": {"entity": "customers", "keyword": "other"}},
        {"target": "employee-c"},
        {"permissions": ["business_db.read", "sales.query"]},
    ],
)
def test_same_operation_cannot_change_arguments_target_or_delegated_scope(handoff_env, change):
    first = _commit(handoff_env)
    assert first["success"], first
    conflict = _commit(handoff_env, body={**handoff_env.body, **change})
    assert conflict["error_code"] == "idempotency_conflict"
    assert (
        len(
            handoff_env.repository().list_task_runs(
                user_id="11", task_id=handoff_env.context["task_id"]
            )
        )
        == 2
    )


def test_distinct_operations_with_equal_arguments_have_independent_receipts(handoff_env):
    first = _commit(handoff_env)
    second_body = {**handoff_env.body, "idempotency_key": "handoff-2"}
    second = _commit(handoff_env, body=second_body)
    assert first["success"] and second["success"], (first, second)
    assert first["parent_run_id"] == second["parent_run_id"]
    assert first["child_run_id"] != second["child_run_id"]
    drop_process_idempotency_memory()
    assert _commit(handoff_env) == first
    assert _commit(handoff_env, body=second_body) == second
    parent = handoff_env.repository().get(first["parent_run_id"])
    assert set(parent.metadata["child_results"]) == {first["child_run_id"], second["child_run_id"]}


@pytest.mark.parametrize("failed_employee", [None, "employee-c"])
def test_parallel_employees_retain_each_original_result_and_isolate_failure(
    handoff_env, monkeypatch, failed_employee
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine

    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    first = _commit(handoff_env)
    assert first["success"], first
    engine = create_engine(str(handoff_env.factory.kw["bind"].url))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(
        "app.application.employee_runtime.handoff_commit.get_agent_run_repository",
        lambda: SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
    )
    original_handoff = AgentOrchestrator.start_employee_handoff
    original_execute = AgentToolExecutor.execute
    barrier = threading.Barrier(2)
    calls = []

    def start_together(self, *args, **kwargs):
        barrier.wait(timeout=10)
        return original_handoff(self, *args, **kwargs)

    def execute(self, step, *, runtime_context):
        employee = runtime_context["employee_id"]
        calls.append(employee)
        if employee == failed_employee:
            return {
                "success": False,
                "message": "independent child read failed",
                "retryable": False,
            }
        return original_execute(self, step, runtime_context=runtime_context)

    monkeypatch.setattr(AgentOrchestrator, "start_employee_handoff", start_together)
    monkeypatch.setattr(AgentToolExecutor, "execute", execute)
    bodies = [
        {**handoff_env.body, "idempotency_key": target, "target": target}
        for target in ("employee-b", "employee-c")
    ]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda body: _commit(handoff_env, body=body), bodies))
        assert sorted(calls) == ["employee-b", "employee-c"]
        assert results[0]["success"] is True, results
        assert results[1]["success"] is (failed_employee is None), results
        if failed_employee:
            assert results[1]["error_code"] == "handoff_child_failed", results
        repository = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        parent = repository.get(first["parent_run_id"])
        assert set(parent.metadata["child_results"]) == {
            first["child_run_id"],
            *(item["child_run_id"] for item in results),
        }
        assert parent.metadata["child_results"][first["child_run_id"]]["status"] == "completed"
        assert parent.status == "running"
        for body, receipt in zip(bodies, results, strict=True):
            assert _commit(handoff_env, body=body) == receipt
        assert sorted(calls) == ["employee-b", "employee-c"]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "foreign"),
        ("user_id", "other"),
        ("employee_id", "employee-c"),
        ("task_id", "other-task"),
        ("workspace_path", "/other/workspace"),
    ],
)
def test_explicit_parent_run_must_match_every_trusted_identity(handoff_env, field, value):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.task_context import apply_task_context

    context = {**handoff_env.context, "workspace_path": str(handoff_env.workspace), field: value}
    parent = AgentRun(user_id=str(context["user_id"]), message="existing parent", status="running")
    parent.metadata["runtime_context"] = context
    apply_task_context(parent, context)
    handoff_env.repository().save(parent)
    denied = _commit(handoff_env, context={**handoff_env.context, "run_id": parent.run_id})
    assert denied["error_code"] == "handoff_unauthorized"
    assert len(handoff_env.repository().list_recent(user_id=parent.user_id)) == 1


def test_explicit_parent_run_is_reused_and_credentials_are_not_persisted(handoff_env):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.task_context import apply_task_context

    parent = AgentRun(user_id="11", message="original execution", status="running")
    parent.metadata["runtime_context"] = {
        **handoff_env.context,
        "workspace_path": str(handoff_env.workspace),
    }
    apply_task_context(parent, parent.metadata["runtime_context"])
    handoff_env.repository().save(parent)
    result = _commit(
        handoff_env,
        context={
            **handoff_env.context,
            "run_id": parent.run_id,
            "token": "credential-must-not-copy",
            "password": "not-a-handoff-field",
        },
    )
    assert result["success"], result
    assert result["parent_run_id"] == parent.run_id
    stored = str([run.to_dict() for run in handoff_env.repository().list_recent(user_id="11")])
    assert "credential-must-not-copy" not in stored and "not-a-handoff-field" not in stored


def test_completed_handoff_becomes_the_next_employees_real_parent(handoff_env):
    from app.application.employee_runtime.executor import execute_employee_task_local

    first = execute_employee_task_local(
        "employee-a",
        "交给员工乙",
        {
            "continuity_action": "handoff",
            "tenant_id": "999",
            "user_id": "999",
            "_actor_authorization": {"proof": "forged"},
            "task_id": handoff_env.context["task_id"],
            "target_employee": "employee-b",
            "permissions": ["business_db.read"],
            "delegated_tool": "business_db",
            "delegated_action": "read",
            "delegated_params": {"entity": "customers", "keyword": "交接客户甲"},
        },
        user_id=11,
        workspace_root=str(handoff_env.workspace),
        runtime_context=handoff_env.context,
    )
    assert "handoff" in first, first
    first_receipt = first["handoff"]["result_payload"]
    assert first_receipt.get("success"), json.dumps(first["handoff"], ensure_ascii=False)
    second = execute_employee_task_local(
        "employee-b",
        "继续交接",
        {
            "continuity_action": "handoff",
            "tenant_id": "11",
            "user_id": "11",
            "task_id": handoff_env.context["task_id"],
            "target_employee": "employee-c",
            "permissions": ["business_db.read"],
            "delegated_tool": "business_db",
            "delegated_action": "read",
            "delegated_params": {"entity": "customers", "keyword": "交接客户甲"},
        },
        user_id=11,
        workspace_root=str(handoff_env.workspace),
        runtime_context={**handoff_env.context, "employee_id": "employee-b"},
    )
    receipt = second["handoff"]["result_payload"]
    assert receipt["success"], second
    assert receipt["parent_run_id"] == first_receipt["child_run_id"]
    child = handoff_env.repository().get(receipt["child_run_id"])
    assert child.metadata["runtime_context"]["root_run_id"] == first_receipt["parent_run_id"]


def test_known_failed_child_remains_failed_without_another_dispatch(handoff_env, monkeypatch):
    from app.application.agent_orchestrator.tool_permission import _LIVE_OWNERS

    live_before = set(_LIVE_OWNERS)
    calls = []

    def fail(self, step, *, runtime_context):
        calls.append(step.step_id)
        return {
            "success": False,
            "error_code": "test_failure",
            "message": "read failed",
            "retryable": False,
        }

    monkeypatch.setattr(AgentToolExecutor, "execute", fail)
    first = _commit(handoff_env)
    assert first["error_code"] == "handoff_child_failed", first
    assert first["execution_status"] == "blocked"
    assert not first.get("reconciliation_required")
    assert live_before == _LIVE_OWNERS
    drop_process_idempotency_memory()
    assert _commit(handoff_env) == first
    assert len(calls) == 1


def test_inflight_handoff_reads_original_child_then_accepts_its_late_receipt(
    handoff_env, monkeypatch
):
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    original = AgentOrchestrator.start_run_from_plan

    def defer(self, **kwargs):
        return original(self, **{**kwargs, "auto_execute": False})

    monkeypatch.setattr(AgentOrchestrator, "start_run_from_plan", defer)
    first = _commit(handoff_env)
    assert first["success"] is False
    assert first["execution_state"] == "running"
    assert not first.get("reconciliation_required")
    assert first["retryable"] is False
    drop_process_idempotency_memory()
    assert _commit(handoff_env) == first
    repository = handoff_env.repository()
    original_parent = repository.get(first["parent_run_id"])
    child = repository.get(first["child_run_id"])
    assert not child.tool_calls
    AgentOrchestrator(repository=repository).execute_dispatched_run(child.run_id)
    completed = repository.get(child.run_id)
    assert completed.status == "completed", completed.error

    monkeypatch.setattr(
        AgentOrchestrator,
        "start_employee_handoff",
        lambda *_args, **_kwargs: pytest.fail("readback dispatched a new child"),
    )
    monkeypatch.setattr(
        AgentToolExecutor,
        "execute",
        lambda *_args, **_kwargs: pytest.fail("readback repeated the original tool"),
    )
    result = _commit(handoff_env)
    assert result["success"] is True, result
    assert result["child_run_id"] == child.run_id
    assert repository.get(first["parent_run_id"]).to_dict() == original_parent.to_dict()
    assert len(repository.list_task_runs(user_id="11", task_id=handoff_env.context["task_id"])) == 2


@pytest.mark.parametrize(
    "snapshot",
    [
        {"status": "unknown", "final_output": {}},
        {"status": "blocked", "final_output": {"reconciliation_required": True}},
    ],
)
def test_handoff_readback_cannot_clear_an_unknown_parent_snapshot(handoff_env, snapshot):
    from app.application.employee_runtime.handoff_commit import _child_receipt

    first = _commit(handoff_env)
    assert first["success"], first
    repository = handoff_env.repository()
    parent = repository.get(first["parent_run_id"])
    child = repository.get(first["child_run_id"])
    parent.metadata["child_results"][child.run_id].update(snapshot)
    result = _child_receipt(
        parent,
        child,
        task_id=handoff_env.context["task_id"],
        tenant_id="11",
        user_id="11",
        target=handoff_env.body["target"],
        delegated=handoff_env.body["permissions"],
        tool_id=handoff_env.body["delegated_tool"],
        action=handoff_env.body["delegated_action"],
        params=handoff_env.body["delegated_params"],
    )
    assert result["success"] is False
    assert result["reconciliation_required"] is True


@pytest.mark.parametrize("outcome", ["running", "waiting_approval", "unknown"])
def test_continuity_preserves_original_handoff_receipt_and_waiting_state(
    handoff_env, monkeypatch, outcome
):
    from app.application.employee_runtime.executor import execute_employee_task_local
    from app.application.employee_runtime.task_continuity import load_employee_task_ledger

    receipt = {
        "success": False,
        "parent_run_id": "original-parent",
        "child_run_id": "original-child",
        "execution_state": outcome,
        "retryable": False,
        "reconciliation_required": outcome == "unknown",
        "pending_approval": outcome == "waiting_approval",
        "error_code": "handoff_pending"
        if outcome != "unknown"
        else "handoff_reconciliation_required",
        "error_message": "原子任务待回执",
    }
    monkeypatch.setattr(
        "app.application.employee_runtime.handoff_commit.commit_registered_handoff",
        lambda *_args, **_kwargs: copy.deepcopy(receipt),
    )
    result = execute_employee_task_local(
        "employee-a",
        "交给员工乙",
        {
            "continuity_action": "handoff",
            "task_id": handoff_env.context["task_id"],
            "target_employee": "employee-b",
            "permissions": handoff_env.body["permissions"],
            "delegated_tool": handoff_env.body["delegated_tool"],
            "delegated_action": handoff_env.body["delegated_action"],
            "delegated_params": handoff_env.body["delegated_params"],
        },
        user_id=11,
        workspace_root=str(handoff_env.workspace),
        runtime_context=handoff_env.context,
    )
    ledger = load_employee_task_ledger(handoff_env.workspace)
    handoff = ledger["handoffs"][result["handoff"]["handoff_id"]]
    assert handoff["result_payload"] == {
        **receipt,
        "ok": False,
        **({"outcome_unknown": True} if outcome == "unknown" else {}),
    }
    assert handoff["status"] == outcome
    assert result["task"]["status"] == ("recovering" if outcome == "unknown" else outcome)
    assert result["business_success"] is False
    assert not ledger["side_effects"]


@pytest.mark.parametrize("unknown", [{"outcome": "unknown"}, {"reconciliation_required": True}])
def test_generic_handoff_step_preserves_unknown_and_cannot_retry(handoff_env, monkeypatch, unknown):
    from app.application.employee_runtime.executor import execute_employee_task_local
    from app.application.employee_runtime.task_continuity import load_employee_task_ledger

    calls = []

    def unknown_handoff(*_args, **_kwargs):
        calls.append(True)
        return {
            "success": False,
            "parent_run_id": "original-parent",
            "child_run_id": "original-child",
            **unknown,
        }

    monkeypatch.setattr(
        "app.application.employee_runtime.handoff_commit.commit_registered_handoff", unknown_handoff
    )

    def dispatch(action, **payload):
        return execute_employee_task_local(
            "employee-a",
            "原交接",
            {"continuity_action": action, **payload},
            user_id=11,
            workspace_root=str(handoff_env.workspace),
            runtime_context=handoff_env.context,
        )

    first = dispatch("start", steps=[{"tool": "handoff_commit", "params": {}}], execute_limit=1)
    task_id = first["task_id"]
    assert first["task"]["status"] == "recovering"
    ledger = load_employee_task_ledger(handoff_env.workspace)
    step = ledger["tasks"][task_id]["steps"][0]
    assert step["status"] == "recovering"
    assert step["result_payload"]["child_run_id"] == "original-child"
    assert step["result_payload"]["outcome_unknown"] is True
    retried = dispatch("retry_step", task_id=task_id, step_id=step["step_id"])
    assert retried["error_code"] == "retry_not_failed"
    dispatch("run_tools", task_id=task_id)
    assert calls == [True]


def test_inflight_duplicate_never_dispatches_a_second_child(handoff_env, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    entered, release = threading.Event(), threading.Event()
    original = AgentOrchestrator.start_employee_handoff

    def blocked(self, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentOrchestrator, "start_employee_handoff", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        execution = pool.submit(_commit, handoff_env)
        assert entered.wait(10)
        try:
            duplicate = _commit(handoff_env)
            assert duplicate["outcome"] == "unknown"
            assert duplicate["reconciliation_required"] is True
        finally:
            release.set()
        first = execution.result(timeout=20)
    assert first["success"], first
    assert _commit(handoff_env) == first
    assert (
        len(
            handoff_env.repository().list_task_runs(
                user_id="11", task_id=handoff_env.context["task_id"]
            )
        )
        == 2
    )


def test_sealed_actor_mod_scope_is_preserved_and_revocation_rechecked(
    handoff_env, customers_db, monkeypatch
):
    from datetime import timedelta

    from app.db.db_base import Base
    from app.db.models.permission import Permission, Role
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope, bind_agent_mod_scope
    from app.utils.time import utc_now_naive

    Base.metadata.create_all(customers_db)
    monkeypatch.setattr("app.db.HostSessionLocal", handoff_env.factory)
    with handoff_env.factory.begin() as db:
        role = Role(name="admin")
        role.permissions.append(Permission(code="customer.view", name="查看客户"))
        db.add(role)
        db.add(
            User(
                id=11,
                username="handoff-owner",
                password="unused",
                tenant_id=11,
                role="admin",
                is_active=True,
            )
        )
        db.flush()
        db.add(
            UserSession(
                session_id="test-private-session",
                user_id=11,
                expires_at=utc_now_naive() + timedelta(hours=1),
                entitled_mod_ids_json='["mod-a", "mod-b"]',
            )
        )

    def context(mod):
        return {
            **handoff_env.context,
            "_actor_authorization": bind_agent_actor_scope(
                session_id="test-private-session", user_id="11", mod_id=mod
            ),
            "_mod_authorization": bind_agent_mod_scope(
                session_id="test-private-session", user_id="11", mod_id=mod
            ),
        }

    original_context = context("mod-a")
    first = _commit(handoff_env, context=original_context)
    assert first["success"], first
    fresh = handoff_env.repository()
    for run_id in (first["parent_run_id"], first["child_run_id"]):
        runtime = fresh.get(run_id).metadata["runtime_context"]
        assert runtime["_actor_authorization"] == original_context["_actor_authorization"]
        assert runtime["_mod_authorization"] == original_context["_mod_authorization"]
        assert "test-private-session" not in str(runtime)
    assert _commit(handoff_env, context=context("mod-a")) == first
    cross_mod = _commit(handoff_env, context={**context("mod-b"), "run_id": first["parent_run_id"]})
    assert cross_mod["error_code"] == "handoff_unauthorized"
    cross_key = _commit(handoff_env, context=context("mod-b"))
    assert cross_key["error_code"] == "handoff_unauthorized"
    new_key = _commit(
        handoff_env,
        body={**handoff_env.body, "idempotency_key": "different-mod-operation"},
        context=context("mod-b"),
    )
    assert new_key["error_code"] == "handoff_unauthorized"
    with handoff_env.factory.begin() as db:
        db.query(UserSession).filter_by(
            session_id="test-private-session"
        ).one().entitled_mod_ids_json = "[]"
    denied = _commit(handoff_env, context=original_context)
    assert denied["error_code"] == "tool_identity_required"
    assert len(fresh.list_task_runs(user_id="11", task_id=handoff_env.context["task_id"])) == 2


_CRASH_HANDOFF = r"""
import json, os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator import tool_permission
from app.application import customer_app_service
from app.application.employee_runtime import handoff_commit

factory = sessionmaker(bind=create_engine(sys.argv[1]), expire_on_commit=False)
customer_app_service.get_customers_session = factory
handoff_commit.get_agent_run_repository = lambda: SQLAlchemyAgentRunRepository(session_factory=factory)
AgentToolExecutor.execute_with_deadline = lambda self, step, *, runtime_context, deadline_monotonic: self.execute(step, runtime_context=runtime_context)
def crash(*args, **kwargs):
    os._exit(91)
if sys.argv[5] == "before_parent_receipt":
    tool_permission.attach_child_result = crash
else:
    handoff_commit.finish_idempotent_replay = crash
handoff_commit.commit_registered_handoff(json.loads(sys.argv[3]), sys.argv[2], json.loads(sys.argv[4]))
raise AssertionError("handoff did not reach crash boundary")
"""


@pytest.mark.parametrize(
    "phase,verified", [("before_parent_receipt", False), ("before_claim_receipt", True)]
)
def test_process_exit_recovers_only_persisted_receipts_without_reexecution(
    handoff_env, monkeypatch, phase, verified
):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH")))
        ),
    }
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH_HANDOFF,
            str(handoff_env.factory.kw["bind"].url),
            str(handoff_env.workspace),
            json.dumps(handoff_env.body),
            json.dumps(handoff_env.context),
            phase,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert crashed.returncode == 91, crashed.stderr
    fresh = handoff_env.repository()
    before = fresh.list_task_runs(user_id="11", task_id=handoff_env.context["task_id"])
    assert len(before) == 2
    child = next(run for run in before if run.metadata.get("plan"))
    assert child.status == "completed", (child.error, crashed.stderr[-2500:])

    def forbidden(*args, **kwargs):
        raise AssertionError("replayed an interrupted handoff")

    monkeypatch.setattr(AgentOrchestrator, "start_employee_handoff", forbidden)
    drop_process_idempotency_memory()
    result = _commit(handoff_env)
    assert result["success"] is verified, result
    assert result["child_run_id"] == child.run_id
    if not verified:
        assert result["outcome"] == "unknown" and result["reconciliation_required"] is True
    assert _commit(handoff_env) == result
    assert {
        run.run_id
        for run in fresh.list_task_runs(user_id="11", task_id=handoff_env.context["task_id"])
    } == {run.run_id for run in before}


def test_new_operation_cannot_move_the_same_task_to_another_workspace(handoff_env):
    import shutil

    first = _commit(handoff_env)
    assert first["success"], first
    another = handoff_env.workspace.parent / "another-workspace"
    shutil.copytree(handoff_env.workspace, another)
    denied = commit_registered_handoff(
        {**handoff_env.body, "idempotency_key": "new-workspace-operation"},
        str(another),
        handoff_env.context,
    )
    assert denied["error_code"] == "handoff_unauthorized"
    assert (
        len(
            handoff_env.repository().list_task_runs(
                user_id="11", task_id=handoff_env.context["task_id"]
            )
        )
        == 2
    )


def test_missing_task_root_requires_reconciliation_without_a_replacement(handoff_env, monkeypatch):
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.db.models.agent import AgentRunRecord

    first = _commit(handoff_env)
    assert first["success"], first
    with handoff_env.factory.begin() as db:
        db.query(AgentRunRecord).filter_by(run_id=first["parent_run_id"]).delete()

    def forbidden(*args, **kwargs):
        raise AssertionError("recreated missing task root")

    monkeypatch.setattr(AgentOrchestrator, "start_employee_handoff", forbidden)
    result = _commit(
        handoff_env, body={**handoff_env.body, "idempotency_key": "new-after-root-loss"}
    )
    assert result["reconciliation_required"] is True
    assert result["parent_run_id"] == first["parent_run_id"]
    runs = handoff_env.repository().list_task_runs(
        user_id="11", task_id=handoff_env.context["task_id"]
    )
    assert [run.run_id for run in runs] == [first["child_run_id"]]


@pytest.mark.parametrize(
    ("flags", "code"),
    [
        ({"available": False}, "handoff_unknown_employee"),
        ({"available": "false"}, "handoff_identity_unverified"),
        ({"available": 1}, "handoff_identity_unverified"),
        ({"timeout": "false"}, "handoff_identity_unverified"),
        ({"crash": True}, "employee_unavailable"),
        ({"timeout": True}, "employee_unavailable"),
        ({"unrecoverable": True}, "employee_unavailable"),
    ],
)
def test_unavailable_handoff_target_cannot_start_a_child(handoff_env, flags, code):
    path = handoff_env.workspace / "employees" / "employee-b.json"
    card = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**card, **flags}), encoding="utf-8")

    result = _commit(handoff_env)

    assert result["success"] is False
    assert result["error_code"] == code
    assert (
        handoff_env.repository().list_task_runs(
            user_id="11", task_id=handoff_env.context["task_id"]
        )
        == []
    )


@pytest.mark.parametrize("interruption", ["role_revoke", "disable_account"])
def test_inflight_handoff_rechecks_original_session_after_role_revocation(
    handoff_env, customers_db, monkeypatch, interruption
):
    """A revoked role cannot use a tool after an already admitted handoff."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    import app.db
    from app.application.rbac_app_service import RbacAppService
    from app.db.db_base import Base
    from app.db.models.permission import Permission, Role
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.infrastructure.auth.agent_mod_scope import (
        AgentModAuthorizationError,
        bind_agent_actor_scope,
    )
    from app.utils.time import utc_now_naive

    Base.metadata.create_all(customers_db)
    monkeypatch.setattr(app.db, "HostSessionLocal", handoff_env.factory)
    with handoff_env.factory.begin() as db:
        role = Role(
            name="tenant:11:handoff-reviewer",
            is_system=False,
            permissions=[Permission(code="customer.view", name="Read customer")],
        )
        db.add(role)
        db.flush()
        role_id = role.id
        db.add(
            User(
                id=11,
                username="handoff-revoke-owner",
                password="unused",
                tenant_id=11,
                role=role.name,
                tier="enterprise",
                is_active=True,
            )
        )
        db.flush()
        db.add(
            UserSession(
                user_id=11,
                session_id="handoff-revoke-original",
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    ctx = {
        **handoff_env.context,
        "_actor_authorization": bind_agent_actor_scope(
            session_id="handoff-revoke-original", user_id="11"
        ),
        "_mod_authorization": None,
    }
    entered, released = threading.Event(), threading.Event()
    original_execute = AgentToolExecutor.execute
    attempts: list[str] = []

    def after_admission(self, step, *, runtime_context):
        attempts.append(step.step_id)
        entered.set()
        assert released.wait(20)
        return original_execute(self, step, runtime_context=runtime_context)

    monkeypatch.setattr(AgentToolExecutor, "execute", after_admission)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_commit, handoff_env, context=ctx)
        assert entered.wait(20), "handoff never reached the original tool gate"
        try:
            if interruption == "role_revoke":
                changed = RbacAppService().update_role(role_id, tenant_id=11, permissions=[])
                assert changed["sessions_revoked"] == 1
            else:
                with handoff_env.factory.begin() as db:
                    db.get(User, 11).is_active = False
        finally:
            released.set()
        outcome = future.result(timeout=30)
    assert outcome.get("success") is not True, outcome
    with handoff_env.factory() as db:
        remaining = db.query(UserSession).filter_by(session_id="handoff-revoke-original").count()
        assert remaining == (0 if interruption == "role_revoke" else 1)
        role = db.query(Role).filter_by(id=role_id).one()
        expected = [] if interruption == "role_revoke" else ["customer.view"]
        assert sorted(permission.code for permission in role.permissions) == expected
        assert db.get(User, 11).is_active is (interruption != "disable_account")
    with pytest.raises(AgentModAuthorizationError):
        bind_agent_actor_scope(session_id="handoff-revoke-original", user_id="11")
    before = len(
        handoff_env.repository().list_task_runs(
            user_id="11", task_id=handoff_env.context["task_id"]
        )
    )
    repeated = _commit(handoff_env, context=ctx)
    assert repeated.get("success") is not True, repeated
    assert len(attempts) == 1
    assert (
        len(
            handoff_env.repository().list_task_runs(
                user_id="11", task_id=handoff_env.context["task_id"]
            )
        )
        == before
    )
