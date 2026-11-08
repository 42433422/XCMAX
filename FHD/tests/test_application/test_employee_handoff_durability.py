"""Handoff storage/replay contracts; E25 owns the hard tool-worker acceptance."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import drop_process_idempotency_memory
from app.application.employee_runtime.handoff_commit import commit_registered_handoff

from .test_employee_handoff_e25 import _card, _start
from .test_employee_handoff_e25 import customers_db as customers_db


@pytest.fixture
def handoff_env(customers_db, tmp_path, monkeypatch):
    # Keep the real registered read and SQL repositories; isolate the tool deadline
    # boundary so these tests cannot stand in for the separate E25 process checks.
    monkeypatch.setattr(
        AgentToolExecutor,
        "execute_with_deadline",
        lambda self, step, *, runtime_context, deadline_monotonic: self.execute(
            step, runtime_context=runtime_context
        ),
    )
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
            "permissions": ["customers.query"],
            "delegated_tool": "customers",
            "delegated_action": "query",
            "delegated_params": {"keyword": "交接客户甲"},
            "idempotency_key": "handoff-1",
        },
        context={
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
        {"delegated_params": {"keyword": "other"}},
        {"target": "employee-c"},
        {"permissions": ["customers.query", "sales.query"]},
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

    from .test_employee_handoff_e25 import _handoff

    first = _handoff(
        handoff_env.workspace, handoff_env.context["task_id"], permissions=["customers.query"]
    )
    first_receipt = first["handoff"]["result_payload"]
    assert first_receipt["success"], first
    second = execute_employee_task_local(
        "employee-b",
        "继续交接",
        {
            "continuity_action": "handoff",
            "tenant_id": "11",
            "user_id": "11",
            "task_id": handoff_env.context["task_id"],
            "target_employee": "employee-c",
            "permissions": ["customers.query"],
            "delegated_tool": "customers",
            "delegated_action": "query",
            "delegated_params": {"keyword": "交接客户甲"},
        },
        workspace_root=str(handoff_env.workspace),
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

    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope, bind_agent_mod_scope
    from app.utils.time import utc_now_naive

    User.__table__.create(customers_db, checkfirst=True)
    UserSession.__table__.create(customers_db, checkfirst=True)
    monkeypatch.setattr("app.db.HostSessionLocal", handoff_env.factory)
    with handoff_env.factory.begin() as db:
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
    assert cross_key["error_code"] == "idempotency_conflict"
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

    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
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
    assert child.status == "completed"

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
