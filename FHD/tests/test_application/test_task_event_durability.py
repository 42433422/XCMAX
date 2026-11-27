"""Ownership and control events share durable transaction fences across restarts."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_models import TaskControlCommand
from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord
from app.domain.task_lifecycle.control import SessionBook
from tests.test_application.test_agent_task_admission import (
    admission_sessions as admission_sessions,
)


def test_claim_takeover_and_completion_keep_ordered_durable_history(admission_sessions):
    queue = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    run = AgentRun(user_id="owner", message="original request", status="queued")
    queue.enqueue(run, requested_by="owner")
    first = queue.claim("first-worker", lease_seconds=30)
    future = (datetime.fromisoformat(first.lease_expires_at) + timedelta(seconds=1)).isoformat()
    second = queue.claim("next-worker", lease_seconds=30, now=future)
    assert second.execution_count == 2
    assert (
        queue.finish(
            run.run_id, second.lease_owner, "completed", execution_count=second.execution_count
        ).state
        == "succeeded"
    )

    reopened = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    history = reopened.lifecycle(run.run_id)["history"]
    assert [(event["from"], event["to"], event["code"]) for event in history] == [
        ("created", "queued", "task_enqueued"),
        ("queued", "running", "worker_claimed"),
        ("running", "running", "worker_reclaimed"),
        ("running", "succeeded", ""),
    ]
    assert [(event["actor"], event["execution_count"]) for event in history[1:3]] == [
        ("first-worker", 1),
        ("next-worker", 2),
    ]
    assert reopened.get(run.run_id).execution_count == 2


def test_claim_and_event_rollback_together_before_reopen(admission_sessions, monkeypatch):
    queue = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    run = AgentRun(user_id="owner", message="claim interrupted before commit", status="queued")
    queue.enqueue(run)
    before = queue.get(run.run_id).to_dict()
    history = queue.lifecycle(run.run_id)["history"]
    original_put = SessionBook.put

    def interrupt(db_book, module, tenant, task_id, body):
        original_put(db_book, module, tenant, task_id, body)
        if body["history"][-1]["code"] == "worker_claimed":
            raise OperationalError("injected claim commit failure", {}, RuntimeError("lost"))

    with monkeypatch.context() as context:
        context.setattr(SessionBook, "put", interrupt)
        with pytest.raises(OperationalError, match="injected claim commit failure"):
            queue.claim("lost-worker", lease_seconds=30)
    reopened = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    assert reopened.get(run.run_id).to_dict() == before
    assert reopened.lifecycle(run.run_id)["history"] == history
    recovered = reopened.claim("current-worker", lease_seconds=30)
    assert recovered.execution_count == 1
    events = reopened.lifecycle(run.run_id)["history"]
    assert len(events) == 2 and events[-1]["actor"] == "current-worker"


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_control_publication_waits_for_run_fence_and_orders_intents(admission_sessions, action):
    repo = SQLAlchemyAgentRunRepository(session_factory=admission_sessions)
    run = repo.save(AgentRun(user_id="owner", message="ancestor under recovery", status="running"))
    before = run.to_dict()
    attempted = threading.Event()
    publisher: dict[str, int] = {}
    engine = admission_sessions.kw["bind"]

    def observe_write(connection, cursor, statement, parameters, context, executemany):
        if (
            threading.get_ident() == publisher.get("ident")
            and statement.lstrip().upper().startswith(("UPDATE", "INSERT"))
            and any(table in statement for table in ("agent_runs", "agent_task_commands"))
        ):
            attempted.set()

    def publish():
        publisher["ident"] = threading.get_ident()
        return repo.request_task_control(run.run_id, action, requested_by=run.user_id)

    event.listen(engine, "before_cursor_execute", observe_write)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with admission_sessions.begin() as inspection:
                # The real Run fence held by startup/ancestor inspection. The
                # second Session must not publish a command inside this window.
                inspection.query(AgentRunRecord).filter_by(run_id=run.run_id).update(
                    {AgentRunRecord.status: AgentRunRecord.status}, synchronize_session=False
                )
                future = pool.submit(publish)
                assert attempted.wait(timeout=5)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.1)

                # Another command commits while the publisher is waiting. Its
                # timestamp and supersession must precede the newly admitted one.
                preceding = TaskControlCommand(
                    task_id=run.run_id,
                    run_id=run.run_id,
                    action="cancel" if action == "pause" else "pause",
                    requested_by=run.user_id,
                )
                inspection.add(
                    AgentTaskCommandRecord(
                        command_id=preceding.command_id,
                        task_id=preceding.task_id,
                        run_id=preceding.run_id,
                        action=preceding.action,
                        status=preceding.status,
                        requested_by=preceding.requested_by,
                        metadata_json=json.dumps(preceding.metadata),
                        created_at=preceding.created_at,
                    )
                )
                released_after = utc_now_iso()
            command = future.result(timeout=5)
    finally:
        event.remove(engine, "before_cursor_execute", observe_write)

    assert command.created_at >= released_after > preceding.created_at
    reopened = SQLAlchemyAgentRunRepository(session_factory=admission_sessions)
    assert reopened.latest_task_control(run.run_id).command_id == command.command_id
    with admission_sessions() as db:
        rows = (
            db.query(AgentTaskCommandRecord)
            .filter_by(run_id=run.run_id)
            .order_by(AgentTaskCommandRecord.created_at, AgentTaskCommandRecord.command_id)
            .all()
        )
        assert [(row.command_id, row.status) for row in rows] == [
            (preceding.command_id, "superseded"),
            (command.command_id, "requested"),
        ]
        assert rows[0].applied_at >= command.created_at
    assert reopened.get(run.run_id).to_dict() == before
