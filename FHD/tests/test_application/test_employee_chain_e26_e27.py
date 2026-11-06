"""Business handoffs keep real tool results, files, and recovery identity."""

from __future__ import annotations

import json

import pytest

from app.application.employee_runtime.task_continuity import ledger_path, load_employee_task_ledger
from tests.fixtures.employee_business_chain import (
    EMPLOYEES,
    business_plan,
    business_workspace,
    invoke,
    run_business_chain,
)


def test_four_employees_query_export_and_summarize(tmp_path):
    proof = run_business_chain(tmp_path / "chain")
    assert proof["complete"], proof
    assert len(proof["tool_calls"]) == 4
    assert len(proof["artifacts"]) == 1


def test_failed_last_hop_resumes_without_replaying_export(tmp_path):
    proof = run_business_chain(tmp_path / "recovery", fail_last_hop=True)
    assert proof["complete"], proof
    assert proof["recovered"], proof


def test_empty_chain_cannot_claim_business_success(tmp_path):
    workspace = tmp_path / "missing"
    with business_workspace(workspace):
        task_id = invoke(workspace, "start")["task_id"]
        result = invoke(
            workspace, "chain", task_id=task_id, employees=EMPLOYEES, permissions=["continue"]
        )
    assert result["business_success"] is False
    assert result["error_code"] == "chain_context_missing"


def test_chain_cannot_delegate_tools_outside_its_scope(tmp_path):
    workspace = tmp_path / "scope"
    with business_workspace(workspace):
        task_id = invoke(workspace, "start")["task_id"]
        plan = business_plan()
        plan["permissions"] = ["customers.query"]
        result = invoke(workspace, "chain", task_id=task_id, **plan)
    assert result["business_success"] is False
    assert result["error_code"] == "handoff_unauthorized"
    assert result["handoff"]["target_employee"] == EMPLOYEES[1]


def test_failed_self_handoff_does_not_expand_permissions(tmp_path):
    workspace = tmp_path / "self-handoff"
    with business_workspace(workspace):
        task_id = invoke(workspace, "start")["task_id"]
        state = load_employee_task_ledger(workspace)
        state["tasks"][task_id]["grants"][EMPLOYEES[0]] = ["customers.query"]
        ledger_path(workspace).write_text(json.dumps(state), encoding="utf-8")
        for _ in range(2):
            result = invoke(
                workspace,
                "handoff",
                task_id=task_id,
                target_employee=EMPLOYEES[0],
                permissions=["reports.export"],
                delegated_tool="reports",
                delegated_action="export",
                delegated_params={"report_type": "sales"},
            )
            assert result["business_success"] is False
            assert result["error_code"] == "handoff_unauthorized"
            task = load_employee_task_ledger(workspace)["tasks"][task_id]
            assert task["grants"][EMPLOYEES[0]] == ["customers.query"]


@pytest.mark.parametrize("operation", ["handoff", "run_tools"])
def test_replay_cannot_read_another_tasks_receipt(tmp_path, operation):
    workspace = tmp_path / operation
    with business_workspace(workspace):
        first_id = invoke(workspace, "start", user_id="22")["task_id"]
        task_id = invoke(
            workspace,
            "start",
            steps=[
                {
                    "tool": "list_customers",
                    "params": {},
                    "idempotency_key": "shared-key",
                }
            ],
        )["task_id"]
        state = load_employee_task_ledger(workspace)
        state["side_effects"]["shared-key"] = {
            "task_id": first_id,
            "invocations": 1,
            "result": {"ok": True, "private": "foreign-receipt"},
        }
        ledger_path(workspace).write_text(json.dumps(state), encoding="utf-8")
        result = invoke(
            workspace,
            operation,
            task_id=task_id,
            idempotency_key="shared-key",
            target_employee=EMPLOYEES[1],
            permissions=["customers.query"],
            delegated_tool="customers",
            delegated_action="query",
            delegated_params={},
        )
        task = load_employee_task_ledger(workspace)["tasks"][task_id]
        assert result["business_success"] is False
        error = result["error_code"] if operation == "handoff" else task["steps"][0]["error_code"]
        assert error == "idempotency_scope_conflict"
        assert "foreign-receipt" not in json.dumps(result)
