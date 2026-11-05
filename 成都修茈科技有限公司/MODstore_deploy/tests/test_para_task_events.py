"""Live hints wake authoritative saved-task readback without changing ownership."""

from __future__ import annotations

import json

import pytest

from modstore_server import incident_team_completion as completion
from modstore_server import incident_team_orchestrator as team
from modstore_server import para_task_events as events
from tests.test_incident_team_continuation import _accepted, _claim, _terminal
from tests.test_incident_team_continuation import incident as incident
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db


def test_notification_is_only_a_validated_id_hint():
    assert (
        events.task_id_from_notification(
            json.dumps(
                {
                    "type": "task_status",
                    "schema_version": 1,
                    "task_id": "original-task_1",
                    "status": "completed",
                    "event_id": 999,
                    "user_id": "other",
                    "task_url": "https://untrusted.test/task",
                }
            )
        )
        == "original-task_1"
    )
    for raw in (
        "not json",
        "[]",
        "{}",
        json.dumps(
            {
                "type": "task_status",
                "schema_version": 1,
                "task_id": "../other",
            }
        ),
        json.dumps(
            {
                "type": "task_status",
                "schema_version": 2,
                "task_id": "original",
            }
        ),
        json.dumps(
            {
                "type": "execute_task",
                "schema_version": 1,
                "task_id": "original",
            }
        ),
    ):
        assert events.task_id_from_notification(raw) is None


def test_settings_require_service_token_and_header_safe_origin(monkeypatch):
    from modstore_server import cred_vault
    from modstore_server import para_delegate_handler as para

    monkeypatch.setenv("MODSTORE_PARA_TASK_EVENTS_ENABLED", "1")
    monkeypatch.setattr(para, "_api_base", lambda: "https://para.example.test/control/")
    monkeypatch.setattr(cred_vault, "get_credential", lambda *a, **kw: "pst_private")
    assert events._connection_settings() == (
        "wss://para.example.test/control/ws/task-events",
        "pst_private",
    )
    monkeypatch.setattr(cred_vault, "get_credential", lambda *a, **kw: "browser-jwt")
    assert events._connection_settings() is None
    monkeypatch.setattr(cred_vault, "get_credential", lambda *a, **kw: "pst_private")
    for base in (
        "https://user:secret@para.test",
        "https://para.test?token=secret",
        "file:///tmp",
    ):
        monkeypatch.setattr(para, "_api_base", lambda value=base: value)
        assert events._connection_settings() is None
    monkeypatch.setenv("MODSTORE_PARA_TASK_EVENTS_ENABLED", "0")
    assert events._connection_settings() is None


def test_reconnect_refreshes_header_and_ready_sweeps_missed_receipts(monkeypatch):
    settings = iter(
        [
            ("wss://para.test/ws/task-events", "pst_old"),
            ("wss://para.test/ws/task-events", "pst_rotated"),
        ]
    )
    calls, waits = [], []
    listener = events.TaskEventListener(lambda _: None, settings=lambda: next(settings))
    frames = iter(
        [
            json.dumps({"type": "task_events_ready", "schema_version": 1, "live_only": True}),
            json.dumps(
                {
                    "type": "task_status",
                    "schema_version": 1,
                    "task_id": "saved",
                    "status": "completed",
                }
            ),
            json.dumps({"type": "task_status", "schema_version": 1, "task_id": "saved"}),
            json.dumps({"type": "execute_task", "task_id": "injected"}),
        ]
    )

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def recv(self, **kwargs):
            try:
                return next(frames)
            except StopIteration:
                listener.stopped.set()
                return "{}"

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            raise ConnectionError("network unavailable")
        return Socket()

    listener.connector = connect
    monkeypatch.setattr(
        listener.stopped,
        "wait",
        lambda delay: waits.append(delay) or listener.stopped.is_set(),
    )
    listener._receive()
    assert [kwargs["additional_headers"]["Authorization"] for _, kwargs in calls] == [
        "Bearer pst_old",
        "Bearer pst_rotated",
    ]
    assert all(
        "pst_" not in url and kwargs["max_queue"] == 16 and kwargs["proxy"] is None
        for url, kwargs in calls
    )
    assert waits == [1, 1]
    assert listener.pending.get_nowait() is None
    assert listener.pending.get_nowait() == "saved"
    assert listener.pending.empty()


def test_hint_queue_is_bounded_and_readback_failure_does_not_replay_dispatch(caplog):
    seen = []
    listener = events.TaskEventListener(lambda _: None)
    listener.enqueue("original")
    listener.enqueue("original")
    listener.enqueue(None)

    def notice(task_id):
        seen.append(task_id)
        if task_id is not None:
            raise ValueError("sensitive raw response must not be logged")
        listener.stopped.set()

    listener.on_notice = notice
    listener._drain()
    assert seen == ["original", None]
    assert listener.queued == set()
    assert "sensitive raw response" not in caplog.text
    for index in range(300):
        listener.enqueue(str(index))
    assert listener.pending.qsize() == len(listener.queued) == 256


def test_notification_uses_saved_receipt_and_original_get_before_advancing(incident, monkeypatch):
    executed, reads = [], []
    monkeypatch.setattr(
        team,
        "_execute_employee_task_with_timeout",
        lambda employee, task, runtime, **kw: (
            executed.append(runtime["role"]) or _accepted(runtime["role"])
        ),
    )
    team.dispatch_incident_team(incident)
    assert completion.reconcile_task_notification(
        "unknown", fetcher=lambda *a: pytest.fail("Unknown ID must not GET")
    ) == {"matched_events": []}

    def running(base, task_id):
        reads.append(task_id)
        return _terminal(task_id, "running")

    # A fabricated success status cannot finish the original running task.
    hint = events.task_id_from_notification(
        json.dumps(
            {
                "type": "task_status",
                "schema_version": 1,
                "task_id": "p-scout",
                "status": "completed",
                "event_id": "untrusted",
            }
        )
    )
    assert completion.reconcile_task_notification(hint, fetcher=running) == {
        "matched_events": [incident]
    }
    assert reads == ["p-scout"] and executed == ["scout"]
    assert _claim(incident)["team"][0]["status"] == "pending"
    completion.reconcile_task_notification(hint, fetcher=lambda base, task_id: _terminal(task_id))
    assert executed == ["scout", "fix"]
    completion.reconcile_task_notification(hint, fetcher=running)
    assert executed == ["scout", "fix"]
    assert set(reads) == {"p-scout", "p-fix"}


def test_periodic_recovery_remains_registered_when_notifications_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(events, "_LISTENER", None)
    monkeypatch.setattr(
        events,
        "_connection_settings",
        lambda: (_ for _ in ()).throw(ValueError("vault unavailable")),
    )
    jobs = []

    class Scheduler:
        def add_job(self, callback, trigger, **kwargs):
            jobs.append((callback, trigger, kwargs))

    completion.register_completion_job(Scheduler(), track_job=lambda *a: None)
    assert len(jobs) == 1
    assert jobs[0][1] == "interval" and jobs[0][2]["seconds"] == 30
    assert jobs[0][2]["max_instances"] == 1
