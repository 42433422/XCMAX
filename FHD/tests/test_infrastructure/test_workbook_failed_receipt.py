"""A known file with bad predictions releases planning, never quality or replay."""

import copy

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    canonical_hash,
    verified_step_output,
    verify_step_result,
)
from app.application.agent_orchestrator.verification_workbook import (
    known_workbook_expectation_failure,
)
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.domain.task_lifecycle.agent_runtime_results import (
    receipt_artifact_failure,
    receipt_settled_failure,
)
from app.domain.workbook_write_contract import WORKBOOK_WRITER
from app.infrastructure.xiaox.receipts import _failed_execution_receipt
from tests.fixtures.result_verification import _adapter, _receipt


def bound_failure(monkeypatch):
    run, step, call, context = _receipt(
        tool_id="employee",
        action="execute",
        params={
            "employee_id": WORKBOOK_WRITER,
            "input": {"template_path": "absent-test-template.xlsx", "plan": {"phases": []}},
        },
    )
    run.status = "blocked"
    artifact = {
        "artifact_type": "file",
        "artifact_id": "copy",
        "metadata": {"run_id": run.run_id, "sha256": "a" * 64},
    }
    step.output = {"success": True, "artifacts": [artifact]}
    call.output = copy.deepcopy(step.output)
    contract = call.metadata["verification_contract"]
    contract["workbook_template"] = {"sha256": "b" * 64}
    contract["contract_sha256"] = canonical_hash(
        {k: v for k, v in contract.items() if k != "contract_sha256"}
    )
    bind_execution_receipt(call)
    checks = [
        {
            "check_id": "file",
            "source": "run_artifact",
            "status": "passed",
            "evidence": {"run_id": run.run_id, "artifact_id": "copy", "sha256": "a" * 64},
        },
        {
            "check_id": "quality",
            "source": "workbook_qc",
            "status": "failed",
            "evidence": {
                "template_sha256": "b" * 64,
                "artifact_sha256": "a" * 64,
                "sections": {"conformance": "pass", "formulas": "pass"},
                "formula_recalculation": {
                    "evaluation_completed": True,
                    "source_unchanged": True,
                    "code": "formula_recalculation_value_mismatch",
                    "formula_error_count": 0,
                    "expectation_mismatch_count": 1,
                },
            },
        },
    ]
    _adapter(
        monkeypatch,
        lambda **_: {
            "status": "failed",
            "code": "formula_recalculation_value_mismatch",
            "checks": checks,
        },
    )
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["status"] == "failed", report
    return run, step, call


def failure_row(run, step, call):
    operation = {"tool_id": step.tool_id, "action": step.action, "params": step.params}
    return {
        **operation,
        "state": "failed",
        "fingerprint": canonical_digest(operation),
        "child_run_id": run.run_id,
        "child_task_id": "original-task",
        "receipt": {
            "status": "failed",
            "run_id": run.run_id,
            "task_id": "original-task",
            "success": False,
            "verified": False,
            "error_code": "artifact_expectation_mismatch",
            "execution": _failed_execution_receipt(run, step, call),
            "verification": {"status": "failed", "accepted": False},
        },
    }


def test_failed_quality_is_settled_but_not_success_and_raw_receipt_stays(monkeypatch):
    run, step, call = bound_failure(monkeypatch)
    before = copy.deepcopy(
        (step.output, call.output, call.params, call.metadata["verification_contract"])
    )
    assert known_workbook_expectation_failure(run, step, call)
    output = verified_step_output(run, step)
    assert output["success"] is False and output["reconciliation_required"] is False
    assert output["execution"]["committed"] is True and output["retryable"] is False
    assert output["verification"]["accepted"] is False
    row = failure_row(run, step, call)
    assert receipt_artifact_failure(row) and receipt_settled_failure(row)
    assert before == (step.output, call.output, call.params, call.metadata["verification_contract"])


@pytest.mark.parametrize("conflicting", [False, True])
def test_nested_employee_file_projection_requires_identical_descriptors(monkeypatch, conflicting):
    run, step, call = bound_failure(monkeypatch)
    duplicate = copy.deepcopy(call.output["artifacts"])
    if conflicting:
        duplicate[0]["metadata"]["sha256"] = "c" * 64
    step.output["data"] = {"result": {"success": True, "artifacts": duplicate}}
    call.output = copy.deepcopy(step.output)
    bind_execution_receipt(call)
    verify_step_result(run=run, step=step, call=call, context=run.metadata["runtime_context"])
    assert known_workbook_expectation_failure(run, step, call) is not conflicting


@pytest.mark.parametrize(
    "mutation",
    [
        "billing",
        "unknown",
        "params",
        "foreign_file",
        "foreign_check",
        "changed_report",
        "missing_template",
        "failed_formula",
        "reconciliation",
    ],
)
def test_unsettled_or_unbound_effect_cannot_use_file_failure_exception(monkeypatch, mutation):
    run, step, call = bound_failure(monkeypatch)
    report = call.metadata["verification"]
    if mutation == "billing":
        call.metadata["billing_status"] = "unknown"
    elif mutation == "unknown":
        call.output["execution"] = {"outcome": "unknown"}
    elif mutation == "params":
        call.params["employee_id"] = "financial-writer"
    elif mutation == "foreign_file":
        call.output["artifacts"][0]["metadata"]["run_id"] = "foreign"
    elif mutation == "foreign_check":
        report["checks"][0]["evidence"]["run_id"] = "foreign"
    elif mutation == "changed_report":
        report["checks"][1]["evidence"]["formula_recalculation"]["expectation_mismatch_count"] = 0
    elif mutation == "missing_template":
        call.metadata["verification_contract"]["workbook_template"] = {}
    elif mutation == "failed_formula":
        report["checks"][1]["evidence"]["formula_recalculation"]["formula_error_count"] = 1
    else:
        run.metadata["non_retryable"] = True
    assert not known_workbook_expectation_failure(run, step, call)
    assert _failed_execution_receipt(run, step, call) is None


@pytest.mark.parametrize(
    "mutation", ["missing_ids", "foreign", "fingerprint", "financial", "unknown", "success"]
)
def test_projection_marker_is_bound_to_original_file_operation(monkeypatch, mutation):
    run, step, call = bound_failure(monkeypatch)
    row = failure_row(run, step, call)
    if mutation == "missing_ids":
        row["child_run_id"] = row["receipt"]["run_id"] = None
    elif mutation == "foreign":
        row["receipt"]["task_id"] = "foreign"
    elif mutation == "fingerprint":
        row["fingerprint"] = "changed"
    elif mutation == "financial":
        row["params"] = {"employee_id": "financial-writer"}
        row["fingerprint"] = canonical_digest({k: row[k] for k in ("tool_id", "action", "params")})
    elif mutation == "unknown":
        row["receipt"]["execution"]["outcome"] = "unknown"
    else:
        row["receipt"]["success"] = True
    assert not receipt_artifact_failure(row)
    assert not receipt_settled_failure(row)
