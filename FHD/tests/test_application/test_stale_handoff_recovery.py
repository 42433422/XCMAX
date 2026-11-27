"""Restart recovery preserves the registered parent-child handoff and ancestor fencing."""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
import threading
import types
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentRun, SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.run_repository import (
    set_agent_run_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.db_base import Base
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry
from tests.test_application.test_agent_task_admission import (
    admission_sessions as admission_sessions,
)
from tests.test_application.test_stale_run_reconciler import (
    _backdate_run,
    _iso,
    _make_repo,
    reconciler,
    task_dispatcher,
)
from tests.test_application.test_stale_run_reconciler import (
    _offline_recovery as _offline_recovery,
)
from tests.test_routes.test_xiaox_receipt_projection import receipt_task as receipt_task


def _registered_handoff(repo, *, attempt, depth=1):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_audit_scope import attach_child_result
    from app.application.agent_orchestrator.task_context import apply_task_context
    from app.application.agent_orchestrator.tool_permission import handoff_runtime_context
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    parent = AgentRun(user_id="1", message="original handoff", status="waiting_user")
    context = {
        "tenant_id": "7",
        "user_id": "1",
        "task_id": "registered-handoff",
        "task_attempt": attempt,
        "workspace_id": "original-workspace",
    }
    parent.metadata["runtime_context"] = context
    apply_task_context(parent, context)
    repo.save(parent)
    ancestors = [parent]
    for index in range(depth):
        context = handoff_runtime_context(
            context,
            employee_id=f"employee-{index}",
            allowlist=["business_db.read"],
            parent_task_id="registered-handoff",
            parent_run_id=parent.run_id,
        )
        plan = PlanGraph(
            plan_id=f"registered-plan-{index}",
            intent="query",
            nodes=[
                WorkflowNode(
                    node_id="read-customers",
                    tool_id="business_db",
                    action="read",
                    params={"entity": "customers"},
                    risk="low",
                    idempotent=True,
                )
            ],
        )
        child = AgentRun(
            user_id=parent.user_id,
            message="registered child read",
            status="running" if index == depth - 1 else "waiting_user",
            plan_id=plan.plan_id,
        )
        child.steps = [AgentOrchestrator._step_from_node(node) for node in plan.nodes]
        child.metadata.update(runtime_context=context, plan=plan_to_dict(plan))
        apply_task_context(child, context)
        repo.save(child)
        assert attach_child_result(parent, child)
        repo.save(parent)
        if index < depth - 1:
            ancestors.append(child)
        parent = child
    return ancestors, child


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("depth", [1, 2])
def test_registered_handoff_keeps_original_child_after_restart(tmp_path, attempt, depth):
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    engine, factory, repo = _make_repo(tmp_path, "registered-handoff.db")
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    try:
        set_agent_run_repository_for_tests(repo)
        ancestors, child = _registered_handoff(repo, attempt=attempt, depth=depth)
        assert child.metadata["task_context"]["attempt"] == 1
        assert safe_continuation_error(child) == ""
        task_before = repo.get_task(
            user_id="1", tenant_id="7", task_id="registered-handoff"
        ).to_dict()
        assert task_before["active_run_id"] == ancestors[0].run_id
        assert task_before["attempt"] == attempt
        parent_snapshots = {run.run_id: repo.get(run.run_id).to_dict() for run in ancestors}
        _backdate_run(factory, child.run_id, status="running", updated_at=_iso(-300))

        assert reconciler.reconcile_stale_running_runs() == 1
        recovered = repo.get(child.run_id)
        assert recovered.status == "queued"
        assert [step.to_dict() for step in recovered.steps] == [
            step.to_dict() for step in child.steps
        ]
        assert queue.claim("replacement-worker", run_id=child.run_id, lease_seconds=60)
        assert (
            repo.get_task(user_id="1", tenant_id="7", task_id="registered-handoff").to_dict()
            == task_before
        )
        for run_id, before in parent_snapshots.items():
            assert repo.get(run_id).to_dict() == before
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


@pytest.mark.parametrize(
    "invalid",
    [
        "unregistered",
        "forged_parent",
        "cross_tenant",
        "cross_mod",
        "changed_employee",
        "changed_actor",
        "changed_root",
        "paused_ancestor",
        "cancelled_ancestor",
        "pause_requested",
        "cancel_requested",
        "xiaox_paused",
        "xiaox_cancelled",
        "task_paused",
        "task_cancelled",
        "cycle",
        "superseded",
    ],
)
def test_handoff_recovery_refuses_unbound_or_stopped_ancestors(tmp_path, invalid):
    from app.db.models.agent import AgentRunRecord, AgentTaskRecord

    engine, factory, repo = _make_repo(tmp_path, "refused-handoff.db")
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    try:
        set_agent_run_repository_for_tests(repo)
        ancestors, child = _registered_handoff(repo, attempt=2, depth=2)
        root, parent = ancestors
        if invalid in {"pause_requested", "cancel_requested"}:
            repo.request_task_control(root.run_id, invalid.split("_")[0], requested_by="1")
        elif invalid == "superseded":
            from app.application.agent_orchestrator.task_context import apply_task_context

            replacement = AgentRun(user_id="1", message="new attempt", status="waiting_user")
            replacement.metadata["runtime_context"] = {
                **root.metadata["runtime_context"],
                "task_attempt": 3,
            }
            apply_task_context(replacement, replacement.metadata["runtime_context"])
            repo.save(replacement)
        else:
            # Simulate a stored legacy/inconsistent relation or a control write
            # surviving before its final Run projection. No mocked repository.
            with factory.begin() as db:
                if invalid.startswith("task_"):
                    task = (
                        db.query(AgentTaskRecord)
                        .filter_by(tenant_id="7", user_id="1", task_id="registered-handoff")
                        .one()
                    )
                    task.status = invalid.removeprefix("task_")
                else:
                    target = (
                        child
                        if invalid in {"forged_parent", "changed_employee", "changed_root"}
                        else root
                        if invalid.startswith("xiaox_")
                        else parent
                    )
                    record = db.get(AgentRunRecord, target.run_id)
                    payload = json.loads(record.payload_json)
                    metadata = payload["metadata"]
                    context = metadata["runtime_context"]
                    if invalid == "unregistered":
                        metadata["child_results"].pop(child.run_id)
                    elif invalid == "forged_parent":
                        context["parent_run_id"] = root.run_id
                        metadata["task_context"]["parent_run_id"] = root.run_id
                    elif invalid == "cross_tenant":
                        context["tenant_id"] = "8"
                    elif invalid == "cross_mod":
                        context["_mod_authorization"] = {"mod_id": "another-mod"}
                    elif invalid == "changed_employee":
                        context["employee_id"] = "another-employee"
                    elif invalid == "changed_actor":
                        context["_actor_authorization"] = {"user_id": "another-owner"}
                    elif invalid == "changed_root":
                        context["root_run_id"] = "another-root"
                    elif invalid.endswith("_ancestor"):
                        payload["status"] = invalid.removesuffix("_ancestor")
                    elif invalid.startswith("xiaox_"):
                        payload["status"] = "running"
                        metadata["runtime_type"] = "xiaox"
                        metadata["xiaox_runtime"] = {
                            "revoked": True,
                            "close_reason": invalid.removeprefix("xiaox_"),
                        }
                    elif invalid == "cycle":
                        context["parent_run_id"] = child.run_id
                        metadata["task_context"]["parent_run_id"] = child.run_id
                        reciprocal = db.get(AgentRunRecord, child.run_id)
                        reciprocal_payload = json.loads(reciprocal.payload_json)
                        reciprocal_payload["metadata"]["child_results"] = {
                            parent.run_id: {
                                "parent_run_id": child.run_id,
                                "parent_task_id": "registered-handoff",
                                "tenant_id": "7",
                                "user_id": "1",
                                "mod_id": "",
                                "employee_id": context["employee_id"],
                            }
                        }
                        reciprocal.payload_json = json.dumps(reciprocal_payload)
                    record.payload_json = json.dumps(payload)
                    record.status = payload["status"]
        parent_snapshots = {run.run_id: repo.get(run.run_id).to_dict() for run in ancestors}
        task_before = repo.get_task(
            user_id="1", tenant_id="7", task_id="registered-handoff"
        ).to_dict()
        _backdate_run(factory, child.run_id, status="running", updated_at=_iso(-300))

        assert reconciler.reconcile_stale_running_runs() == 1
        assert repo.get(child.run_id).status == "failed"
        assert queue.claim("replacement-worker", run_id=child.run_id, lease_seconds=60) is None
        assert (
            repo.get_task(user_id="1", tenant_id="7", task_id="registered-handoff").to_dict()
            == task_before
        )
        for run_id, before in parent_snapshots.items():
            assert repo.get(run_id).to_dict() == before
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


@pytest.mark.parametrize("depth", [15, 16])
def test_registered_handoff_recovery_has_a_bounded_ancestor_walk(tmp_path, depth):
    engine, factory, repo = _make_repo(tmp_path, "handoff-depth.db")
    try:
        set_agent_run_repository_for_tests(repo)
        _, child = _registered_handoff(repo, attempt=2, depth=depth)
        _backdate_run(factory, child.run_id, status="running", updated_at=_iso(-300))
        assert reconciler.reconcile_stale_running_runs() == 1
        assert repo.get(child.run_id).status == ("queued" if depth < 16 else "failed")
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


def test_handoff_recovery_fences_a_parent_cancelled_after_its_read(admission_sessions, monkeypatch):
    from sqlalchemy.orm import Query

    from app.db.models.agent import AgentRunRecord

    repo = SQLAlchemyAgentRunRepository(session_factory=admission_sessions)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    ancestors, child = _registered_handoff(repo, attempt=2, depth=2)
    parent = ancestors[-1]
    _backdate_run(admission_sessions, child.run_id, status="running", updated_at=_iso(-300))
    with admission_sessions() as db:
        postgres = db.get_bind().dialect.name == "postgresql"
    original_one, original_all = Query.one_or_none, Query.all
    cancelled = None

    def cancel_parent():
        nonlocal cancelled
        cancelled = {}
        # Commit through another real Session. On PostgreSQL the child fence
        # does not lock its parent; SQLite serializes at the first child write.
        repo.request_task_control(parent.run_id, "cancel", requested_by="1")
        current = repo.get(parent.run_id)
        current.status = "cancelled"
        current.metadata["control"] = {"state": "cancelled", "requested_by": "1"}
        repo.save(current)
        cancelled = repo.get(parent.run_id).to_dict()

    def after_parent_read(query):
        record = original_one(query)
        if postgres and cancelled is None and isinstance(record, AgentRunRecord):
            if record.run_id == parent.run_id:
                cancel_parent()
        return record

    def after_candidates_read(query):
        records = original_all(query)
        if (
            not postgres
            and cancelled is None
            and any(
                isinstance(record, AgentRunRecord) and record.run_id == child.run_id
                for record in records
            )
        ):
            cancel_parent()
        return records

    try:
        set_agent_run_repository_for_tests(repo)
        monkeypatch.setattr(Query, "one_or_none", after_parent_read)
        monkeypatch.setattr(Query, "all", after_candidates_read)
        assert reconciler.reconcile_stale_running_runs() == 1
        assert cancelled
        assert repo.get(child.run_id).status == "failed"
        assert queue.claim("replacement-worker", run_id=child.run_id, lease_seconds=60) is None
        assert repo.get(parent.run_id).to_dict() == cancelled
    finally:
        set_agent_run_repository_for_tests(None)
