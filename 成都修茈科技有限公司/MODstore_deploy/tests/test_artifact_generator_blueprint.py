from __future__ import annotations

from modstore_server.artifact_generator_blueprint import (
    artifact_generator_preflight,
    validate_upstream_employee_plan,
)
from modstore_server.craft_failure_signals import _employee_trigger_limits


def test_validate_upstream_employee_plan_ok() -> None:
    plan = {
        "employee_name": "考勤处理员",
        "employee_brief": "处理考勤表",
        "script_brief": "读 inputs 写 outputs",
        "workflow_brief": "上传→转换→交付",
    }
    status, missing = validate_upstream_employee_plan(plan)
    assert status == "ok"
    assert missing == []


def test_validate_upstream_employee_plan_missing_fields() -> None:
    status, missing = validate_upstream_employee_plan({"employee_name": "x"})
    assert status == "error"
    assert "employee_brief" in missing
    assert "script_brief" in missing


def test_artifact_generator_preflight_error_with_incomplete_plan() -> None:
    out = artifact_generator_preflight(
        payload={"employee_plan": {"employee_name": "only-name"}},
        brief="brief",
    )
    assert out["status"] == "error"
    assert out["missing_fields"]
    assert "employee_brief" in out["missing_fields"]


def test_artifact_generator_preflight_skips_when_no_plan() -> None:
    out = artifact_generator_preflight(payload={}, brief="仅 brief 驱动")
    assert out["status"] == "ok"
    assert out["validation_result"]["blueprint"] == "skipped"


def test_employee_trigger_limits_reads_yaml() -> None:
    limits = _employee_trigger_limits("artifact-generator")
    assert limits["max_patch_budget_tokens"] >= 4000
    assert limits["max_patch_steps"] >= 1
