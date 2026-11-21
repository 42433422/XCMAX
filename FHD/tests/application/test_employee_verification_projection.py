"""Real employee ledger observations never promote a claimed result into proof."""

from __future__ import annotations

import copy
import json

import pytest

from app.db.models.employee_run_log import EmployeeRunLog
from app.fastapi_routes.admin_control.employee_backend import CanonicalEmployeeBackend
from app.fastapi_routes.admin_control.employee_run import EmployeeRunner, EmployeeWork
from tests.application.test_employee_run_tenant_isolation import ledger as ledger


class ReceiptBackend(CanonicalEmployeeBackend):
    def __init__(self, *outcomes):
        self.outcomes = outcomes
        self.run_ids = []

    def execute(self, work, run_id):
        self.run_ids.append(run_id)
        return copy.deepcopy(self.outcomes[len(self.run_ids) - 1])


def run_receipts(*outcomes):
    backend = ReceiptBackend(*outcomes)
    response = EmployeeRunner(backend).run(
        EmployeeWork("clerk", "perform original work", {}, 7, 1, "session", None)
    )
    return backend, response


@pytest.mark.parametrize(
    "claim",
    [
        {},
        {"verified": True, "independent_verified": True},
        {
            "verification": {"status": "verified", "accepted": True, "verified": True},
            "agent_run_id": "another-real-run",
            "validation_scope": "independent_business_result",
        },
    ],
)
def test_successful_execution_preserves_receipt_without_claiming_verification(ledger, claim):
    receipt = {"success": True, "summary": "done", **claim}
    backend, response = run_receipts(receipt)
    assert response["success"] is True and response["result_valid"] is True
    assert response["data"] == receipt
    assert backend.run_ids == [response["run_id"]]
    assert response["validation_scope"] == "execution_envelope"
    assert response["verified"] is False and response["independent_verified"] is False
    assert response["verification"]["status"] == "inconclusive"
    assert response["verification"]["code"] == "result_verifier_unavailable"
    with ledger.get_db() as db:
        row = db.get(EmployeeRunLog, response["run_id"])
        assert row.status == "success" and row.verified == 0
        assert json.loads(row.output_json) == receipt
    record = ledger.list_employee_run_logs("clerk", tenant_id=1)[0]
    assert record["result_valid"] is True and record["verified"] is False
    assert record["verification"] == response["verification"]
    assert "legacy_result_valid" not in record


@pytest.mark.parametrize(
    "negative",
    [
        {"verification": {"status": "failed", "reason": "wrong customer"}},
        {"artifact_postcondition": {"verified": False, "reason": "file missing"}},
        {"result": {"summary": "done", "verification": {"accepted": False}}},
    ],
)
def test_explicit_failure_is_not_overwritten_by_unavailable_projection(ledger, negative):
    receipt = {"success": True, "summary": "claimed done", **negative}
    backend, response = run_receipts(receipt)
    assert response["success"] is False and response["result_valid"] is False
    assert response["data"] == receipt and response["message"]
    assert response["verification"]["status"] == "failed"
    assert response["verification"]["code"] == "employee_result_invalid"
    assert backend.run_ids == [response["run_id"]]
    record = ledger.list_employee_run_logs("clerk", tenant_id=1)[0]
    assert record["status"] == "failed" and record["independent_verified"] is False
    assert record["verification"]["status"] == "failed"


def test_final_projection_does_not_enter_the_same_run_retry_loop(ledger, monkeypatch):
    monkeypatch.setattr("app.fastapi_routes.admin_control.employee_run.time.sleep", lambda _: None)
    timeout = {"success": False, "error": "upstream timeout", "error_code": "timeout"}
    receipt = {"success": True, "summary": "done after retry"}
    backend, response = run_receipts(timeout, timeout, receipt)
    assert backend.run_ids == [response["run_id"]] * 3
    assert response["attempts"] == 3 and response["success"] is True
    assert response["data"] == receipt
    assert response["verification"]["status"] == "inconclusive"
    record = ledger.list_employee_run_logs("clerk", tenant_id=1)[0]
    assert record["attempts"] == 3 and record["status"] == "success"


@pytest.mark.parametrize("boundary", ["backend", "ledger"])
def test_legacy_verified_argument_cannot_promote_new_ledger_rows(ledger, boundary):
    run_id = ledger.create_employee_run_log(employee_id="clerk", tenant_id=1)
    finish = (
        CanonicalEmployeeBackend().finish
        if boundary == "backend"
        else ledger.finish_employee_run_log
    )
    finish(
        run_id,
        tenant_id=1,
        status="success",
        output={"success": True, "summary": "done", "verified": True},
        verified=True,
        error="",
    )
    with ledger.get_db() as db:
        assert db.get(EmployeeRunLog, run_id).verified == 0
    assert (
        ledger.employee_lifecycle(run_id, tenant_id=1)["validation_scope"] == "execution_envelope"
    )


@pytest.mark.parametrize("old_verified", [0, 1])
def test_historical_flags_are_exposed_only_as_legacy_validation(ledger, old_verified):
    run_id = ledger.create_employee_run_log(employee_id="clerk", tenant_id=1)
    with ledger.get_db() as db:
        row = db.get(EmployeeRunLog, run_id)
        row.status = "success"
        row.verified = old_verified
        # Even a claimed server scope in the old output cannot upgrade history.
        row.output_json = json.dumps(
            {
                "validation_scope": "execution_envelope",
                "verification": {"status": "verified", "accepted": True},
            }
        )
        db.commit()
    record = ledger.list_employee_run_logs("clerk", tenant_id=1)[0]
    assert record["id"] == run_id and record["status"] == "success"
    assert record["validation_scope"] == "legacy_execution_envelope"
    assert record["legacy_result_valid"] is bool(old_verified)
    assert record["verified"] is False and record["independent_verified"] is False
    assert record["verification"]["status"] == "inconclusive"
    with ledger.get_db() as db:
        assert db.get(EmployeeRunLog, run_id).verified == old_verified
