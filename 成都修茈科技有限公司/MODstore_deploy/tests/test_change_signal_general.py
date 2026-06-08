"""员工任务生命周期事件发布。"""

from __future__ import annotations


def test_emit_task_lifecycle_event_success(monkeypatch):
    published: list[tuple[str, str, dict]] = []

    def fake_publish(event_type: str, payload: dict, *, source: str) -> bool:
        published.append((event_type, source, payload))
        return True

    monkeypatch.setattr("modstore_server.incident_bus.publish", fake_publish)
    from modstore_server.services.change_signal import emit_task_lifecycle_event

    emit_task_lifecycle_event(
        "test-qa-runner",
        "run pytest",
        status="success",
        result={"result": {"outputs": []}},
    )
    assert published
    et, src, payload = published[0]
    assert et == "employee.task.done"
    assert src == "test-qa-runner"
    assert payload.get("finished_employee_id") == "test-qa-runner"


def test_emit_task_lifecycle_event_failed(monkeypatch):
    published: list[tuple[str, str, dict]] = []

    def fake_publish(event_type: str, payload: dict, *, source: str) -> bool:
        published.append((event_type, source, payload))
        return True

    monkeypatch.setattr("modstore_server.incident_bus.publish", fake_publish)
    from modstore_server.services.change_signal import emit_task_lifecycle_event

    emit_task_lifecycle_event("modstore-backend-api", "task", status="failed", error="boom")
    et, src, _payload = published[0]
    assert et == "employee.task.failed"
    assert src == "modstore-backend-api"


def test_emit_execution_recovery_event(monkeypatch):
    published: list[tuple[str, str, dict]] = []

    def fake_publish(event_type: str, payload: dict, *, source: str) -> bool:
        published.append((event_type, source, payload))
        return True

    monkeypatch.setattr("modstore_server.incident_bus.publish", fake_publish)
    from modstore_server.services.change_signal import emit_execution_recovery_event

    ok = emit_execution_recovery_event(
        "mods-and-eskill-curator",
        "audit manifest",
        recovery_action="cognition_retry",
        success=True,
        original_error="timeout",
        attempts=2,
    )
    assert ok is True
    et, src, payload = published[0]
    assert et == "employee.execution.recovery"
    assert src == "mods-and-eskill-curator"
    assert payload.get("recovery_action") == "cognition_retry"
    assert payload.get("attempts") == 2
