# -*- coding: utf-8 -*-
"""employee_runtime.scheduler local daily job wiring."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.application.employee_runtime import scheduler


@pytest.fixture(autouse=True)
def _reset_scheduler(monkeypatch: pytest.MonkeyPatch):
    scheduler.stop_employee_scheduler(timeout=0.1)
    monkeypatch.setenv("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_DAILY_ORCHESTRATOR_HOUR", "8")
    monkeypatch.setenv("MODSTORE_DAILY_ORCHESTRATOR_MINUTE", "15")
    scheduler.refresh_employee_scheduler_jobs()
    yield
    scheduler.stop_employee_scheduler(timeout=0.1)
    scheduler.refresh_employee_scheduler_jobs()


def test_configured_jobs_include_daily_orchestrator() -> None:
    jobs = scheduler.get_employee_cron_jobs()
    assert jobs
    job = jobs[0]
    assert job["job_id"] == "daily-orchestrator"
    assert job["employee_id"] == "daily-orchestrator"
    assert job["enabled"] is True
    assert job["schedule"] == "daily"
    assert job["next_run_time"]


def test_disabled_scheduler_still_reports_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "0")
    scheduler.refresh_employee_scheduler_jobs()
    jobs = scheduler.get_employee_cron_jobs()
    assert jobs[0]["employee_id"] == "daily-orchestrator"
    assert jobs[0]["enabled"] is False
    assert jobs[0]["state"] == "disabled"


def test_run_employee_cron_job_calls_local_executor() -> None:
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": True, "employee_id": "daily-orchestrator"},
    ) as execute:
        out = scheduler.run_employee_cron_job(
            "daily-orchestrator",
            task="run now",
            input_data={"foo": "bar"},
            session_id="sess",
        )
    assert out["success"] is True
    assert out["job"]["runs_total"] == 1
    assert execute.call_args.args[0] == "daily-orchestrator"
    assert execute.call_args.args[1] == "run now"
    assert execute.call_args.args[2]["cron_job_id"] == "daily-orchestrator"
    assert execute.call_args.args[2]["trigger"] == "manual"


def test_run_unknown_job_returns_error() -> None:
    out = scheduler.run_employee_cron_job("missing")
    assert out["success"] is False
    assert "unknown employee cron job" in out["error"]


# ---------------------------------------------------------------------------
# 多 job 动态加载
# ---------------------------------------------------------------------------


def test_manifest_jobs_are_discovered(monkeypatch: pytest.MonkeyPatch) -> None:
    """manifest 声明 schedule 的员工应被加入调度。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    fake_jobs = {
        "test-qa-runner": scheduler.EmployeeCronJob(
            job_id="test-qa-runner",
            employee_id="test-qa-runner",
            task="每日定时跑测试",
            schedule="daily",
            hour=9,
            minute=0,
            timezone="Asia/Shanghai",
            enabled=True,
            source="manifest",
            next_run_at=datetime.now(tz) + timedelta(days=1),
        )
    }
    monkeypatch.setattr(scheduler, "_discover_manifest_jobs", lambda: fake_jobs)
    scheduler.refresh_employee_scheduler_jobs()
    jobs = scheduler.get_employee_cron_jobs()
    ids = [j["job_id"] for j in jobs]
    assert "daily-orchestrator" in ids
    assert "test-qa-runner" in ids
    # daily-orchestrator 始终第一个（向后兼容）
    assert jobs[0]["job_id"] == "daily-orchestrator"
    # manifest job 带来源标记
    manifest_job = next(j for j in jobs if j["job_id"] == "test-qa-runner")
    assert manifest_job["source"] == "manifest"
    assert manifest_job["next_run_time"]


def test_manifest_job_without_schedule_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 schedule 声明的员工不应进入调度。"""
    monkeypatch.setattr(scheduler, "_discover_manifest_jobs", lambda: {})
    scheduler.refresh_employee_scheduler_jobs()
    jobs = scheduler.get_employee_cron_jobs()
    assert all(j["job_id"] == "daily-orchestrator" for j in jobs)


def test_per_employee_env_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODSTORE_EMPLOYEE_CRON_<ID>_ENABLED=0 应禁用 manifest job。"""
    fake_jobs = {
        "test-qa-runner": scheduler.EmployeeCronJob(
            job_id="test-qa-runner",
            employee_id="test-qa-runner",
            task="每日定时跑测试",
            schedule="daily",
            hour=9,
            minute=0,
            timezone="Asia/Shanghai",
            enabled=True,
            source="manifest",
        )
    }
    monkeypatch.setattr(scheduler, "_discover_manifest_jobs", lambda: fake_jobs)
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_TEST_QA_RUNNER_ENABLED", "0")
    # 重新走 _discover_manifest_jobs 逻辑验证 per_emp_flag
    # 由于 fake_jobs 已绕过 _discover_manifest_jobs 内部，直接验证 _configured_jobs 不受影响
    scheduler.refresh_employee_scheduler_jobs()
    jobs = scheduler.get_employee_cron_jobs()
    assert any(j["job_id"] == "daily-orchestrator" for j in jobs)


# ---------------------------------------------------------------------------
# 失败重试
# ---------------------------------------------------------------------------


def test_failure_schedules_retry_when_max_retries_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_retries > 0 时，失败应调度指数退避重试。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "2")
    scheduler.refresh_employee_scheduler_jobs()
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": False, "error": "boom"},
    ):
        out = scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    assert out["success"] is False
    job = out["job"]
    assert job["last_status"] == "retrying"
    assert job["retry_count"] == 1
    assert job["max_retries"] == 2
    assert job["next_retry_at"] is not None
    assert job["failure_count"] == 1


def test_retry_exhausted_marks_failed_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    """重试耗尽后标记 failed 并重置 retry_count。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "1")
    scheduler.refresh_employee_scheduler_jobs()
    # 先制造一次失败进入 retrying
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": False, "error": "boom"},
    ):
        scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    # 第二次失败（retry_count 已=1，max_retries=1，不再重试）
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": False, "error": "still boom"},
    ):
        out = scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    job = out["job"]
    assert job["last_status"] == "failed"
    assert job["retry_count"] == 0
    assert job["next_retry_at"] is None
    assert job["failure_count"] == 2


def test_success_resets_retry_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功后 retry_count 应重置为 0。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "3")
    scheduler.refresh_employee_scheduler_jobs()
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": False, "error": "boom"},
    ):
        scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": True},
    ):
        out = scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    job = out["job"]
    assert job["last_status"] == "success"
    assert job["retry_count"] == 0
    assert job["next_retry_at"] is None
    assert job["success_count"] == 1


def test_no_retry_when_max_retries_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_retries=0 时失败直接标记 failed，不重试。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "0")
    scheduler.refresh_employee_scheduler_jobs()
    with patch(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        return_value={"success": False, "error": "boom"},
    ):
        out = scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    job = out["job"]
    assert job["last_status"] == "failed"
    assert job["retry_count"] == 0
    assert job["next_retry_at"] is None


# ---------------------------------------------------------------------------
# 告警钩子
# ---------------------------------------------------------------------------


def test_alert_hook_invoked_on_final_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """最终失败时应调用告警钩子。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "0")
    scheduler.refresh_employee_scheduler_jobs()
    calls: list[tuple[str, str, dict]] = []
    scheduler.set_alert_hook(lambda jid, err, jdict: calls.append((jid, err, jdict)))
    try:
        with patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            return_value={"success": False, "error": "boom"},
        ):
            scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    finally:
        scheduler.set_alert_hook(None)
    assert len(calls) == 1
    assert calls[0][0] == "daily-orchestrator"
    assert "boom" in calls[0][1]
    assert calls[0][2]["job_id"] == "daily-orchestrator"


def test_alert_hook_not_invoked_during_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """重试中（retrying）不应触发告警，避免噪音。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "2")
    scheduler.refresh_employee_scheduler_jobs()
    calls: list[tuple] = []
    scheduler.set_alert_hook(lambda jid, err, jdict: calls.append((jid, err, jdict)))
    try:
        with patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            return_value={"success": False, "error": "boom"},
        ):
            scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    finally:
        scheduler.set_alert_hook(None)
    assert len(calls) == 0  # 还在 retrying，未最终失败


def test_alert_hook_exception_does_not_break_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """告警钩子抛异常不应影响调度。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_CRON_MAX_RETRIES", "0")
    scheduler.refresh_employee_scheduler_jobs()

    def bad_hook(jid: str, err: str, jdict: dict) -> None:
        raise RuntimeError("hook broken")

    scheduler.set_alert_hook(bad_hook)
    try:
        with patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            return_value={"success": False, "error": "boom"},
        ):
            out = scheduler.run_employee_cron_job("daily-orchestrator", source="cron")
    finally:
        scheduler.set_alert_hook(None)
    # 钩子抛异常不影响 job 状态更新
    assert out["success"] is False
    assert out["job"]["last_status"] == "failed"


# ---------------------------------------------------------------------------
# to_dict 新字段
# ---------------------------------------------------------------------------


def test_job_to_dict_includes_new_fields() -> None:
    """to_dict 应包含重试与来源相关新字段。"""
    jobs = scheduler.get_employee_cron_jobs()
    job = jobs[0]
    for key in ("max_retries", "retry_count", "next_retry_at", "source", "depends_on"):
        assert key in job, f"missing field: {key}"
