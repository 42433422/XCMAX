"""员工触发器：事件匹配与 publish_employee_task_failed。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime import triggers as trig
from app.domain.employee.events import EVENT_TASK_FAILED


@pytest.fixture(autouse=True)
def _clear_active_subs():
    trig._ACTIVE_SUBSCRIPTIONS.clear()
    yield
    trig._ACTIVE_SUBSCRIPTIONS.clear()


class TestEventMatchesEmployee:
    def test_empty_payload_matches(self):
        ev = SimpleNamespace(payload={})
        assert trig._event_matches_employee(ev, "emp-1") is True

    def test_matching_employee_id(self):
        ev = SimpleNamespace(payload={"employee_id": "emp-1"})
        assert trig._event_matches_employee(ev, "emp-1") is True

    def test_other_employee_blocked(self):
        ev = SimpleNamespace(payload={"employee_id": "emp-2"})
        assert trig._event_matches_employee(ev, "emp-1") is False

    def test_target_employee_alias(self):
        ev = SimpleNamespace(payload={"target_employee": "emp-1"})
        assert trig._event_matches_employee(ev, "emp-1") is True


def test_publish_employee_task_failed_success():
    bus = MagicMock()
    bus.publish.return_value = True
    with patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus):
        ok = trig.publish_employee_task_failed("emp-a", task="t", message="m")
    assert ok is True
    event = bus.publish.call_args[0][0]
    assert event.event_type == EVENT_TASK_FAILED
    assert event.payload["employee_id"] == "emp-a"
    assert event.payload["origin_employee_id"] == "emp-a"


def test_task_failed_handler_skips_own_failure_event():
    employee_cls = MagicMock()
    record_trigger = MagicMock()
    event = SimpleNamespace(
        event_type=EVENT_TASK_FAILED,
        payload={"employee_id": "emp-a", "origin_employee_id": "emp-a"},
    )

    with (
        patch("app.application.employee_runtime.agent.EmployeeAgent", employee_cls),
        patch(
            "app.application.employee_runtime.metrics.record_employee_trigger",
            record_trigger,
        ),
    ):
        trig._make_handler("emp-a", MagicMock())(event)

    employee_cls.assert_not_called()
    record_trigger.assert_not_called()


def test_task_failed_handler_skips_non_retryable_event():
    employee_cls = MagicMock()
    record_trigger = MagicMock()
    event = SimpleNamespace(
        event_type=EVENT_TASK_FAILED,
        payload={
            "employee_id": "emp-a",
            "origin_employee_id": "upstream-employee",
            "retryable": False,
        },
    )

    with (
        patch("app.application.employee_runtime.agent.EmployeeAgent", employee_cls),
        patch(
            "app.application.employee_runtime.metrics.record_employee_trigger",
            record_trigger,
        ),
    ):
        trig._make_handler("emp-a", MagicMock())(event)

    employee_cls.assert_not_called()
    record_trigger.assert_not_called()


def test_task_failed_handler_allows_distinct_retryable_origin():
    employee = MagicMock()
    employee.run.return_value = {"success": True}
    employee_cls = MagicMock(return_value=employee)
    record_trigger = MagicMock()
    event = SimpleNamespace(
        event_type=EVENT_TASK_FAILED,
        payload={
            "employee_id": "emp-a",
            "origin_employee_id": "upstream-employee",
            "retryable": True,
            "task": "repair upstream failure",
        },
    )

    with (
        patch("app.application.employee_runtime.agent.EmployeeAgent", employee_cls),
        patch(
            "app.application.employee_runtime.metrics.record_employee_trigger",
            record_trigger,
        ),
    ):
        trig._make_handler("emp-a", MagicMock())(event)

    employee_cls.assert_called_once_with("emp-a")
    employee.run.assert_called_once()
    record_trigger.assert_called_once_with("emp-a", EVENT_TASK_FAILED)


def test_task_failed_handler_keeps_legacy_target_without_origin():
    employee = MagicMock()
    employee.run.return_value = {"success": True}
    employee_cls = MagicMock(return_value=employee)
    event = SimpleNamespace(
        event_type=EVENT_TASK_FAILED,
        payload={"employee_id": "emp-a", "task": "legacy upstream failure"},
    )

    with (
        patch("app.application.employee_runtime.agent.EmployeeAgent", employee_cls),
        patch("app.application.employee_runtime.metrics.record_employee_trigger"),
    ):
        trig._make_handler("emp-a", MagicMock())(event)

    employee.run.assert_called_once()


def test_publish_employee_task_failed_bus_unavailable():
    with patch("app.neuro_bus.bus.get_neuro_bus", side_effect=RuntimeError("no bus")):
        assert trig.publish_employee_task_failed("emp-a") is False


def test_refresh_employee_triggers_no_bus():
    with patch("app.neuro_bus.bus.get_neuro_bus", side_effect=RuntimeError("down")):
        out = trig.refresh_employee_triggers()
    assert out["registered"] == []
    assert "error" in out


def test_refresh_employee_triggers_registers(monkeypatch: pytest.MonkeyPatch):
    bus = MagicMock()
    bus.subscribe.return_value = "sub-1"
    pack = {
        "pack_id": "test-emp",
        "manifest": {"triggers": {"on_error": True}},
    }
    with (
        patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus),
        patch(
            "app.application.employee_runtime.triggers.list_installed_pack_records",
            return_value=[pack],
        ),
    ):
        out = trig.refresh_employee_triggers()
    assert out["active_employees"] == ["test-emp"]
    assert any(r["event_type"] == EVENT_TASK_FAILED for r in out["registered"])
