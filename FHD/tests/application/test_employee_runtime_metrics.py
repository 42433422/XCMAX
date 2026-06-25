"""employee_runtime.metrics 进程内计数器单元测试（happy/边界/聚合/重置）。"""

from __future__ import annotations

import pytest

from app.application.employee_runtime import metrics as m


@pytest.fixture(autouse=True)
def _reset_metrics():
    m.reset_employee_runtime_metrics()
    yield
    m.reset_employee_runtime_metrics()


class TestRecordRun:
    def test_success_run(self):
        m.record_employee_run("e1", success=True)
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_total"] == 1
        assert snap["runs_success"] == 1
        assert snap["runs_failed"] == 0
        assert snap["by_employee"]["e1"]["runs_success"] == 1

    def test_failed_run(self):
        m.record_employee_run("e1", success=False)
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_failed"] == 1
        assert snap["runs_success"] == 0

    def test_blocked_run_takes_precedence(self):
        m.record_employee_run("e1", success=True, blocked=True)
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_blocked"] == 1
        assert snap["runs_success"] == 0

    def test_multiple_employees_isolated(self):
        m.record_employee_run("e1", success=True)
        m.record_employee_run("e2", success=False)
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_total"] == 2
        assert snap["by_employee"]["e1"]["runs_success"] == 1
        assert snap["by_employee"]["e2"]["runs_failed"] == 1


class TestRecordTrigger:
    def test_trigger_counts_by_event(self):
        m.record_employee_trigger("e1", "employee.task.failed")
        m.record_employee_trigger("e1", "employee.task.failed")
        m.record_employee_trigger("e1", "employee.quality.failed")
        snap = m.get_employee_runtime_metrics()
        assert snap["triggers_total"] == 3
        by_event = snap["by_employee"]["e1"]["triggers_by_event"]
        assert by_event["employee.task.failed"] == 2
        assert by_event["employee.quality.failed"] == 1


class TestOtherCounters:
    def test_orchestration_and_write_block(self):
        m.record_orchestration("e1")
        m.record_write_block("e1")
        snap = m.get_employee_runtime_metrics()
        assert snap["orchestrations_total"] == 1
        assert snap["write_blocks_total"] == 1

    def test_bump_without_employee_id(self):
        m._bump("runs_total")
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_total"] == 1
        assert snap["by_employee"] == {}

    def test_bump_custom_delta(self):
        m._bump("runs_total", "e1", delta=5)
        assert m.get_employee_runtime_metrics()["runs_total"] == 5


class TestReset:
    def test_reset_clears_all(self):
        m.record_employee_run("e1", success=True)
        m.record_orchestration("e2")
        m.reset_employee_runtime_metrics()
        snap = m.get_employee_runtime_metrics()
        assert snap["runs_total"] == 0
        assert snap["orchestrations_total"] == 0
        assert snap["by_employee"] == {}
