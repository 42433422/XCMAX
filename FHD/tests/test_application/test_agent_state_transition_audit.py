"""Committed ledger evidence survives retries, rollback and concurrent control."""

from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield InMemoryAgentRunRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'state-audit.db'}")
    yield SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    engine.dispose()


def audits(run):
    return [event for event in run.events if event.event_type == "run.state_changed"]


def test_committed_transitions_have_causal_ids_and_do_not_repeat(repository):
    run = AgentRun(user_id="u", message="private task")
    run.add_event("run.created")
    first = repository.save(run)
    run.status = "running"
    started = run.add_event("run.started", "private input", {"secret": "do-not-copy"})
    second = repository.save(run)
    again = repository.save(run)
    assert [event.data["to_status"] for event in audits(again)] == ["queued", "running"]
    assert audits(first)[0].data["from_status"] is None
    transition = audits(second)[-1]
    assert transition.data["from_status"] == "queued"
    assert transition.data["reason_event_id"] == started.event_id
    assert transition.data["reason_code"] == "run.started"
    assert transition.data["sequence"] == 2
    assert transition.data["trace_id"] == second.to_dict()["trace_id"]
    assert "private" not in json.dumps(transition.to_dict())
    assert "do-not-copy" not in json.dumps(transition.to_dict())
    assert [event.to_dict() for event in audits(again)] == [
        event.to_dict() for event in audits(second)
    ]


def test_cancelled_state_fences_late_writer_and_failed_cas_adds_no_audit(repository):
    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin

    initial = repository.save(AgentRun(user_id="u", message="task", status="running"))
    cancelled = copy.deepcopy(initial)
    RunLifecycleMixin._mark_controlled(cancelled, "cancel", requested_by="u")
    cancelled.add_event("run.cancelled")
    assert repository.save_control_if_unchanged(cancelled, initial)
    late = copy.deepcopy(initial)
    late.status = "completed"
    late.add_event("run.completed")
    assert not repository.save_if_unchanged(late, initial)
    latest = repository.save(late)
    assert latest.status == "cancelled"
    assert [event.data["to_status"] for event in audits(latest)] == ["running", "cancelled"]


def test_missing_reason_is_explicit_and_never_inferred_from_private_error(repository):
    run = repository.save(AgentRun(user_id="u", message="task"))
    run.status = "failed"
    run.error = "password=secret"
    result = repository.save(run)
    transition = audits(result)[-1]
    assert transition.data["reason_code"] == "reason_not_recorded"
    assert transition.data["reason_recorded"] is False
    assert transition.data["reason_event_id"] is None
    assert "password" not in json.dumps(transition.to_dict())


def test_identifier_shaped_private_values_are_not_copied_to_audit_summary(repository):
    run = repository.save(AgentRun(user_id="u", message="task"))
    run.status = "failed"
    event = run.add_event("private-customer-name", data={"error_code": "sk-private-token-example"})
    result = repository.save(run)
    transition = audits(result)[-1]
    assert transition.data["reason_code"] == "event_reference"
    assert transition.data["reason_event_type"] == "other"
    assert transition.data["reason_event_id"] == event.event_id
    assert transition.data["reported_code_sha256"]
    assert "sk-private" not in json.dumps(transition.to_dict())
    assert "private-customer" not in json.dumps(transition.to_dict())


def test_rollback_retry_does_not_persist_a_phantom_state_or_duplicate(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        original = repository.save(AgentRun(user_id="u", message="task"))
        candidate = copy.deepcopy(original)
        candidate.status = "running"
        candidate.add_event("run.started")
        with factory() as session:
            repository.save_in_session(session, candidate)
            rolled_back_id = audits(candidate)[-1].event_id
            session.flush()
            session.rollback()
        assert repository.get(original.run_id).status == "queued"
        assert len(audits(repository.get(original.run_id))) == 1
        committed = repository.save(candidate)
        assert [event.data["to_status"] for event in audits(committed)] == ["queued", "running"]
        assert audits(committed)[-1].event_id != rolled_back_id
        reopened = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        assert [event.to_dict() for event in audits(reopened.get(original.run_id))] == [
            event.to_dict() for event in audits(committed)
        ]
    finally:
        engine.dispose()


def test_cancel_after_rollback_accepts_same_candidate(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cancel.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        previous = repo.save(AgentRun(user_id="u", message="cancel test", status="running"))
        candidate = copy.deepcopy(previous)
        RunLifecycleMixin._mark_controlled(candidate, "cancel", requested_by="u")
        candidate.add_event("run.cancelled")
        with factory() as db:
            assert repo.save_if_unchanged_in_session(db, candidate, previous)
            db.flush()
            db.rollback()
        assert repo.get(previous.run_id).status == "running"
        assert repo.save_control_if_unchanged(candidate, previous)
        assert repo.get(previous.run_id).status == "cancelled"
    finally:
        engine.dispose()


def test_planning_after_rollback_accepts_same_candidate(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'planning.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        waiting = AgentRun(user_id="owner", message="task")
        waiting.metadata["task_context"] = {"task_id": "planning-task"}
        waiting.metadata["runtime_context"] = {
            "tenant_id": "tenant-1",
            "_mod_authorization": {"mod_id": "mod"},
        }
        question = {"question": "Which scope?", "clarification": {"reason": "planning_scope"}}
        plan = PlanGraph(
            plan_id="planning-original",
            intent="query",
            metadata={"planning_clarification": True},
            nodes=[WorkflowNode("scope", "clarify", "ask", params=question)],
        )
        waiting.status, waiting.plan_id = "waiting_user", plan.plan_id
        waiting.steps = [
            AgentStep("scope", "clarify", "ask", params=question, status="waiting_user")
        ]
        waiting.metadata["plan"] = plan_to_dict(plan)
        previous = repo.save(waiting)
        replacement = copy.deepcopy(previous)
        replacement.status = "running"
        replacement.steps = [AgentStep("read", "print", "list", idempotent=True)]
        replacement.metadata["plan"] = plan_to_dict(
            PlanGraph(
                plan_id=plan.plan_id, intent="query", nodes=[WorkflowNode("read", "print", "list")]
            )
        )
        replacement.metadata["runtime_context"]["_planning_clarification_snapshot"] = (
            canonical_hash(previous.to_dict())
        )
        replacement.add_event(
            "run.clarification_resumed",
            "scope answered",
            {"kind": "planning_scope", "step_id": previous.steps[0].step_id},
        )
        with factory() as db:
            assert repo.save_if_unchanged_in_session(db, replacement, previous)
            db.flush()
            db.rollback()
        assert repo.get(previous.run_id).status == "waiting_user"
        assert repo.save_if_unchanged(replacement, previous)
        assert repo.get(previous.run_id).status == "running"
    finally:
        engine.dispose()
