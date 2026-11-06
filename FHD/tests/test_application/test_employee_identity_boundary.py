"""Untrusted role identities never become durable chain or handoff metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.application.employee_runtime.task_continuity import (
    CONTINUE_TEXT,
    TaskContinuityRuntime,
    ledger_path,
)

EMPLOYEES = [f"identity-{name}" for name in "abcd"]
UNTRUSTED = "unregistered-private-identity-marker"


class _IdentityLike:
    def __str__(self) -> str:
        return UNTRUSTED


class _UnformattableIdentity:
    def __str__(self) -> str:
        raise AssertionError("Identity candidates must not be formatted")


def _card(workspace: Path, employee: str, **fields: Any) -> None:
    folder = workspace / "employees"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{employee}.json").write_text(
        json.dumps({"employee_id": employee, "tenant_id": "17", **fields}), encoding="utf-8"
    )


def _invoke(workspace: Path, operation: str, **payload: Any) -> dict[str, Any]:
    runtime = TaskContinuityRuntime(ledger_path(workspace), workspace=workspace)
    return runtime.dispatch(
        EMPLOYEES[0],
        "身份边界回归",
        {"op": operation, "tenant_id": "17", "user_id": "23", **payload},
    )


def _state(workspace: Path) -> dict[str, Any]:
    return json.loads(ledger_path(workspace).read_text(encoding="utf-8"))


def _save(workspace: Path, state: dict[str, Any]) -> bytes:
    path = ledger_path(workspace)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return path.read_bytes()


def _plan(employees: list[Any] | None = None) -> dict[str, Any]:
    return {
        "employees": list(EMPLOYEES) if employees is None else employees,
        "permissions": ["customers.query"],
        "steps": [
            {
                "step_id": f"lookup-{index}",
                "tool": "customers",
                "action": "query",
                "params": {"keyword": "身份边界"},
            }
            for index in range(4)
        ],
    }


@pytest.fixture
def started(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "identity-workspace"
    for employee in EMPLOYEES:
        # A real unavailable first hop keeps these boundary cases independent
        # of business execution; the E26/E27 suite executes the complete chain.
        _card(workspace, employee, available=employee != EMPLOYEES[0])
    result = _invoke(workspace, "start")
    assert result["success"] is True
    return workspace, result["task_id"]


def _assert_unchanged_rejection(
    workspace: Path, before: bytes, result: dict[str, Any], error_code: str
) -> None:
    assert result["success"] is False
    assert result["business_success"] is False
    assert result["error_code"] == error_code
    assert UNTRUSTED not in json.dumps(result, ensure_ascii=False)
    assert ledger_path(workspace).read_bytes() == before


@pytest.mark.parametrize(
    ("candidate", "error_code"),
    [
        pytest.param({"private": UNTRUSTED}, "chain_shape", id="dictionary"),
        pytest.param([UNTRUSTED], "chain_shape", id="list"),
        pytest.param(_IdentityLike(), "chain_shape", id="stringifiable-object"),
        pytest.param(_UnformattableIdentity(), "chain_shape", id="unformattable-object"),
        pytest.param(123, "chain_shape", id="integer"),
        pytest.param(True, "chain_shape", id="boolean"),
        pytest.param(f"../{UNTRUSTED}", "handoff_unknown_employee", id="parent-path"),
        pytest.param(f"..\\{UNTRUSTED}", "handoff_unknown_employee", id="windows-path"),
        pytest.param(f"x:{UNTRUSTED}", "handoff_unknown_employee", id="drive-path"),
        pytest.param(f"{UNTRUSTED}\nrole", "handoff_unknown_employee", id="control-character"),
        pytest.param(UNTRUSTED, "handoff_unknown_employee", id="unknown-role"),
    ],
)
def test_chain_rejects_raw_identity_before_any_ledger_write(started, candidate, error_code):
    workspace, task_id = started
    candidates = [*EMPLOYEES[:3], candidate]
    before = ledger_path(workspace).read_bytes()

    result = _invoke(workspace, "chain", task_id=task_id, **_plan(candidates))

    _assert_unchanged_rejection(workspace, before, result, error_code)
    assert "chain" not in _state(workspace)["tasks"][task_id]
    assert UNTRUSTED.encode() not in before


@pytest.mark.parametrize(
    ("fields", "error_code"),
    [
        pytest.param({"tenant_id": "18"}, "handoff_cross_tenant", id="other-tenant"),
        pytest.param(
            {"employee_id": UNTRUSTED}, "handoff_identity_unverified", id="mismatched-card-id"
        ),
        pytest.param(
            {"employee_id": {"private": UNTRUSTED}},
            "handoff_identity_unverified",
            id="structured-card-id",
        ),
        pytest.param(
            {"tenant_id": {"private": UNTRUSTED}},
            "handoff_identity_unverified",
            id="structured-card-tenant",
        ),
    ],
)
def test_chain_requires_registered_matching_identity_in_the_task_tenant(
    started, fields, error_code
):
    workspace, task_id = started
    _card(workspace, EMPLOYEES[-1], **fields)
    before = ledger_path(workspace).read_bytes()

    result = _invoke(workspace, "chain", task_id=task_id, **_plan())

    _assert_unchanged_rejection(workspace, before, result, error_code)


@pytest.mark.parametrize("tenant_id", ["17", 17])
def test_registered_unavailable_roles_pass_identity_validation_and_store_only_canonical_ids(
    started, tenant_id
):
    workspace, task_id = started
    _card(workspace, EMPLOYEES[-1], tenant_id=tenant_id, available=False, private=UNTRUSTED)
    candidates = [EMPLOYEES[0], f" {EMPLOYEES[1]} ", *EMPLOYEES[2:]]

    result = _invoke(workspace, "chain", task_id=task_id, **_plan(candidates))

    assert result["success"] is True
    assert result["business_success"] is False
    assert result["error_code"] == "employee_unavailable"
    assert result["handoff"]["target_employee"] == EMPLOYEES[0]
    state = _state(workspace)
    assert state["tasks"][task_id]["chain"]["employees"] == EMPLOYEES
    assert state["tasks"][task_id]["chain"]["completed"] == {}
    assert len(state["handoffs"]) == 1
    assert state["tool_calls"] == {}
    assert UNTRUSTED not in ledger_path(workspace).read_text(encoding="utf-8")
    assert UNTRUSTED not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param({"private": UNTRUSTED}, id="dictionary"),
        pytest.param([UNTRUSTED], id="list"),
        pytest.param(UNTRUSTED, id="unknown-role"),
        pytest.param(f"../{UNTRUSTED}", id="parent-path"),
        pytest.param(_IdentityLike(), id="stringifiable-object"),
        pytest.param(_UnformattableIdentity(), id="unformattable-object"),
    ],
)
def test_direct_handoff_default_key_does_not_serialize_unverified_target(started, candidate):
    workspace, task_id = started

    result = _invoke(
        workspace,
        "handoff",
        task_id=task_id,
        target_employee=candidate,
        permissions=["customers.query"],
        delegated_tool="customers",
        delegated_action="query",
        delegated_params={},
    )

    assert result["business_success"] is False
    assert result["error_code"] == "handoff_unknown_employee"
    assert result["handoff"]["target_employee"] == ""
    assert UNTRUSTED not in json.dumps(result, ensure_ascii=False)
    serialized = ledger_path(workspace).read_text(encoding="utf-8")
    assert UNTRUSTED not in serialized
    state = json.loads(serialized)
    assert state["tool_calls"] == {}
    assert state["side_effects"] == {}
    assert state["tasks"][task_id]["authorized_employees"] == [EMPLOYEES[0]]


def _failed_chain(workspace: Path, task_id: str) -> dict[str, Any]:
    result = _invoke(workspace, "chain", task_id=task_id, **_plan())
    assert result["error_code"] == "employee_unavailable"
    return _state(workspace)


@pytest.mark.parametrize(
    "operation", ["resume", "retry_handoff", "restart", "global_restart", "other_focus_restart"]
)
def test_recovering_a_legacy_invalid_chain_neither_rewrites_nor_reflects_it(started, operation):
    workspace, task_id = started
    other_id = _invoke(workspace, "start")["task_id"]
    state = _failed_chain(workspace, task_id)
    if operation == "resume":
        paused = _invoke(workspace, "pause", task_id=task_id)
        assert paused["success"] is True
        state = _state(workspace)
        assert state["tasks"][task_id]["status"] == "paused"
    state["tasks"][task_id]["chain"]["employees"][-1] = UNTRUSTED
    before = _save(workspace, state)
    payload = {} if operation == "global_restart" else {"task_id": task_id}
    if operation == "other_focus_restart":
        payload = {"task_id": other_id}
    if operation == "resume":
        payload["text"] = CONTINUE_TEXT
    action = "restart" if operation.endswith("restart") else operation

    result = _invoke(workspace, action, **payload)

    _assert_unchanged_rejection(workspace, before, result, "handoff_unknown_employee")


@pytest.mark.parametrize("field", ["source_employee", "target_employee"])
@pytest.mark.parametrize("policy", ["retry", "rollback"])
def test_retry_validates_legacy_handoff_identity_before_increment_or_rollback(
    started, field, policy
):
    workspace, task_id = started
    state = _failed_chain(workspace, task_id)
    previous_id = state["tasks"][task_id]["handoff_ids"][-1]
    state["handoffs"][previous_id][field] = {"private": UNTRUSTED}
    before = _save(workspace, state)

    result = _invoke(workspace, "retry_handoff", task_id=task_id, policy=policy)

    _assert_unchanged_rejection(workspace, before, result, "handoff_unknown_employee")
    assert _state(workspace)["tasks"][task_id]["retry_count"] == 0


def test_archived_chain_can_be_read_and_other_tasks_started_after_cards_are_uninstalled(started):
    workspace, task_id = started
    state = _state(workspace)
    # An imported historical snapshot tests storage compatibility only; this
    # fixture does not stand in for successful execution of the business chain.
    state["tasks"][task_id]["status"] = "completed"
    state["tasks"][task_id]["chain"] = _plan() | {"completed": {}}
    before = _save(workspace, state)
    for path in (workspace / "employees").glob("*.json"):
        path.unlink()

    historical = _invoke(workspace, "read", task_id=task_id)

    assert historical["success"] is True
    assert historical["task_id"] == task_id
    assert ledger_path(workspace).read_bytes() == before
    created = _invoke(workspace, "start")
    assert created["success"] is True
    assert created["task_id"] != task_id
    restarted = _invoke(workspace, "restart")
    assert restarted["success"] is True
    assert _state(workspace)["tasks"][task_id] == state["tasks"][task_id]
    left = _invoke(workspace, "leave", task_id=task_id)
    assert left["success"] is True
    reentered = _invoke(
        workspace,
        "reenter",
        conversation_id=state["tasks"][task_id]["conversation_id"],
    )
    assert reentered["success"] is True
    assert reentered["task_id"] == task_id
    assert _state(workspace)["tasks"][task_id]["chain"] == state["tasks"][task_id]["chain"]
