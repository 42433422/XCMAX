from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from pathlib import Path

from modstore_server import employee_runtime, models, task_router, workflow_scheduler
from modstore_server.duty_workforce_contracts import (
    contract_schedule,
    duty_event_execution_input,
    load_reviewed_duty_manifest,
    load_workforce_contracts,
    matching_duty_event_contract,
    resolve_reviewed_duty_employee_root,
    workforce_contract_map,
    workforce_event_bindings,
)
from modstore_server.employee_executor import _trusted_system_duty_contract_execution


def test_work_contracts_cover_the_roster_exactly() -> None:
    payload = load_workforce_contracts()
    contracts = workforce_contract_map()
    root = Path(__file__).resolve().parents[3]
    roster = json.loads((root / "FHD" / "config" / "duty_roster.json").read_text())
    roster_ids = {employee_id for area in roster["areas"].values() for employee_id in area["ids"]}

    assert payload["schema_version"] == "xcagi.duty_employee_work_contracts/v1"
    assert set(contracts) == roster_ids
    assert len(contracts) == 55
    assert sum(bool(row["trigger"].get("cron")) for row in contracts.values()) == 22
    assert len(workforce_event_bindings()) == 52


def test_contract_schedule_is_safe_and_requires_real_receipt() -> None:
    schedule = contract_schedule(
        {
            "mission": "巡检真实运行",
            "mode": "observe_and_propose",
            "risk_level": "high",
            "trigger": {"cron": "0 3 * * *"},
            "acceptance": ["输出真实证据"],
        }
    )

    assert schedule is not None
    assert schedule["source"] == "duty_work_contract"
    assert schedule["cron"] == "0 3 * * *"
    assert "不得用回显或虚构数据冒充完成" in schedule["task_brief"]
    assert contract_schedule({"trigger": {"events": ["x"]}}) is None


def test_reviewed_duty_manifest_loader_does_not_use_stale_catalog_shell() -> None:
    manifest = load_reviewed_duty_manifest("seo-sitemap-curator")

    assert manifest["id"] == "seo-sitemap-curator"
    assert manifest["employee_config_v2"]["actions"]["handlers"] == ["agent"]


def test_reviewed_duty_employee_root_keeps_manifest_and_module_together() -> None:
    root = resolve_reviewed_duty_employee_root("security-secrets-guard")

    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["id"] == (
        "security-secrets-guard"
    )
    assert (root / "backend/employees/security_secrets_guard.py").is_file()


def _contract_payload(employee_id: str, *, trigger: str, event_type: str = "") -> dict:
    contract = workforce_contract_map()[employee_id]
    return {
        "trigger": trigger,
        "schedule_source": "duty_work_contract",
        "event_type": event_type,
        "work_contract": {
            "schema": "xcagi.duty_employee_work_contracts/v1",
            "mode": contract["mode"],
            "risk_level": contract["risk_level"],
            "acceptance": list(contract["acceptance"]),
        },
    }


def test_trusted_schedule_uses_reviewed_agent_not_stale_catalog_shell() -> None:
    for employee_id in ("flask-entry-keeper", "workbench-ux-stylist"):
        contract, manifest = _trusted_system_duty_contract_execution(
            employee_id,
            _contract_payload(employee_id, trigger="schedule"),
            user_id=0,
        )

        assert contract["risk_level"] == "medium"
        assert manifest["employee_config_v2"]["actions"]["handlers"] == ["agent"]


def test_trusted_event_requires_declared_event_and_rejects_forged_contract() -> None:
    employee_id = "fhd-core-maintainer"
    payload = _contract_payload(employee_id, trigger="event", event_type="on_error")

    contract, manifest = _trusted_system_duty_contract_execution(employee_id, payload, user_id=0)

    assert contract["mode"] == "event"
    assert manifest["employee_config_v2"]["actions"]["handlers"] == ["agent"]

    forged = {**payload, "work_contract": {**payload["work_contract"], "risk_level": "low"}}
    assert _trusted_system_duty_contract_execution(employee_id, forged, user_id=0) == ({}, {})
    assert _trusted_system_duty_contract_execution(
        employee_id,
        _contract_payload(employee_id, trigger="event", event_type="undeclared"),
        user_id=0,
    ) == ({}, {})
    assert _trusted_system_duty_contract_execution(employee_id, payload, user_id=1) == ({}, {})


def test_source_filtered_event_contract_builds_safe_system_input(monkeypatch) -> None:
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", "/opt/xcmax/current")
    contract = matching_duty_event_contract(
        "employee-planner",
        "employee.task.done",
        "intent-analyst",
    )
    assert contract["risk_level"] == "low"
    assert not matching_duty_event_contract(
        "employee-planner",
        "employee.task.done",
        "wrong-source",
    )
    assert not matching_duty_event_contract("deploy-release-officer", "ci.passed", "github")

    payload = duty_event_execution_input(
        "employee-planner",
        event_type="employee.task.done",
        source="intent-analyst",
        incident={"summary": "analysis done"},
    )
    assert payload["trigger"] == "event"
    assert payload["allow_high_risk_real_run"] is False
    assert payload["non_blocking_human_questions"] is True
    assert payload["project_root"] == "/opt/xcmax/current"

    reviewed, manifest = _trusted_system_duty_contract_execution(
        "employee-planner",
        payload,
        user_id=0,
    )
    assert reviewed["risk_level"] == "low"
    assert manifest["id"] == "employee-planner"


def test_employee_project_root_matches_yuangon_scope_base(monkeypatch, tmp_path) -> None:
    company_root = tmp_path / "成都修茈科技有限公司"
    (company_root / "MODstore_deploy").mkdir(parents=True)
    monkeypatch.setattr(
        "modstore_server.integrations.ops_action_handlers.repo_root",
        lambda: tmp_path,
    )

    assert workflow_scheduler._employee_project_root() == str(company_root)

    isolated = tmp_path / "tenant-worktree" / "成都修茈科技有限公司"
    isolated.mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_DUTY_PROJECT_ROOT", str(isolated))
    assert workflow_scheduler._employee_project_root() == str(isolated)


def test_scheduler_registers_contract_cron_jobs(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    contracts = workforce_contract_map()
    profiles = [{"id": employee_id} for employee_id in contracts]
    jobs = []
    registration_rows = []

    class FakeScheduler:
        def add_job(self, fn, trigger, **kwargs):
            jobs.append({"fn": fn, "trigger": trigger, **kwargs})

    monkeypatch.setattr(workflow_scheduler, "_scheduler", FakeScheduler())
    monkeypatch.setattr(task_router, "_load_all_employee_profiles", lambda: profiles)
    monkeypatch.setattr(
        employee_runtime,
        "load_employee_pack",
        lambda session, employee_id: {
            "manifest": json.loads(
                (root / "FHD" / "mods" / "_employees" / employee_id / "manifest.json").read_text()
            )
        },
    )
    monkeypatch.setattr(models, "get_session_factory", lambda: lambda: nullcontext(object()))
    monkeypatch.setattr(
        "modstore_server.scheduler_runtime.record_job_run",
        lambda **kwargs: registration_rows.append(kwargs),
    )
    monkeypatch.setattr(
        "modstore_server.scheduler_runtime.get_runtime_status",
        lambda **_kwargs: {"jobs": []},
    )

    workflow_scheduler._register_employee_cron_jobs()

    employee_jobs = [job for job in jobs if str(job.get("id") or "").startswith("emp_cron_")]
    assert len(employee_jobs) == 22
    assert {job["id"] for job in employee_jobs} >= {
        "emp_cron_seo-sitemap-curator",
        "emp_cron_payment-billing-reconciler",
        "emp_cron_employee-interview-assistant",
    }
    assert "emp_cron_deploy-release-officer" not in {job["id"] for job in employee_jobs}
    assert len(registration_rows) == 22
    assert all(row["status"] == "success" for row in registration_rows)
    assert {row["job_id"] for row in registration_rows} >= {
        "employee_cron_registered:seo-sitemap-curator",
        "employee_cron_registered:payment-billing-reconciler",
    }

    captured = {}

    def fake_execute(employee_id, task, input_data, user_id=0, *, bench_llm_override=None):
        captured.update(
            employee_id=employee_id,
            task=task,
            input_data=input_data,
            user_id=user_id,
            bench_llm_override=bench_llm_override,
        )
        return {"ok": True}

    monkeypatch.setattr(
        "modstore_server.employee_executor.execute_employee_task",
        fake_execute,
    )
    monkeypatch.setattr(
        "modstore_server.services.llm.resolve_platform_bench_llm",
        lambda: ("minimax", "MiniMax-M2.7"),
    )
    monkeypatch.setattr(
        "modstore_server.employee_duty_input_resolver.resolve_employee_duty_input",
        lambda _employee_id: None,
    )
    tracked_job_ids = []

    @contextmanager
    def fake_track_job_run(job_id):
        tracked_job_ids.append(job_id)
        yield

    monkeypatch.setattr(
        "modstore_server.scheduler_runtime.track_job_run",
        fake_track_job_run,
    )
    payment_job = next(
        job for job in employee_jobs if job["id"] == "emp_cron_payment-billing-reconciler"
    )
    payment_job["fn"]()
    assert tracked_job_ids == ["employee_cron:payment-billing-reconciler"]
    assert captured["employee_id"] == "payment-billing-reconciler"
    assert captured["input_data"]["allow_medium_risk"] is True
    assert captured["input_data"]["allow_high_risk_real_run"] is False
    assert captured["input_data"]["non_blocking_human_questions"] is True
    assert captured["bench_llm_override"] == ("minimax", "MiniMax-M2.7")

    tracked_outcomes = []

    @contextmanager
    def fake_track_failed_job(job_id):
        try:
            yield
        except RuntimeError:
            tracked_outcomes.append((job_id, "failed"))
            raise
        else:
            tracked_outcomes.append((job_id, "success"))

    monkeypatch.setattr(
        "modstore_server.scheduler_runtime.track_job_run",
        fake_track_failed_job,
    )
    monkeypatch.setattr(
        "modstore_server.employee_executor.execute_employee_task",
        lambda *_args, **_kwargs: {"ok": False, "status": "handler_failed"},
    )

    payment_job["fn"]()

    assert tracked_outcomes == [("employee_cron:payment-billing-reconciler", "failed")]
