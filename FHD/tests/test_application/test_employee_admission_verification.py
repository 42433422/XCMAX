"""Employee admission is proved by its original ledger, never by child success."""

import copy
import json

import pytest

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    ensure_terminal_business_result,
)
from app.application.agent_orchestrator.result_verification import (
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.employee_runtime.task_continuity import ledger_path, load_employee_task_ledger
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_sales_verification_readback import verify
from tests.test_application.test_verification_readback import invocation


@pytest.fixture
def admission(tmp_path, monkeypatch, trusted_actor):
    root = tmp_path / "server"
    root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    actor = trusted_actor(role="admin")
    params = {
        "employee_id": "clerk",
        "task": "register original work",
        "continuity_action": "start",
        "goal": "prepare the approved summary",
        "steps": [{"step_id": "later", "tool": "note", "params": {"text": "pending"}}],
        "input": {
            "user_id": "caller-supplied-owner",
            "tenant_id": "caller-supplied-tenant",
            "agent_admission": {"run_id": "caller-supplied-run"},
        },
    }
    case = invocation(actor, tool="employee", action="execute", params=params)
    case.context.update(workspace_root=str(root), node_id=case.step.node_id)
    case.run.metadata["runtime_context"]["workspace_root"] = str(root)
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("employee", "execute"), case.context
    )
    output = AgentToolExecutor().execute(case.step, runtime_context=case.context)
    assert output["success"], output
    return case, output, root, actor


def test_original_admission_is_read_only_and_projects_pending_business(admission, monkeypatch):
    case, output, root, _ = admission
    original = ledger_path(root).read_bytes()

    def no_execution(*_args, **_kwargs):
        pytest.fail("verification replayed an employee action")

    monkeypatch.setattr(
        "app.application.employee_runtime.task_continuity.TaskContinuityRuntime.dispatch",
        no_execution,
    )
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", no_execution
    )
    result = verify(case, output)
    assert result["accepted"], result
    evidence = result["checks"][0]["evidence"]
    assert evidence["scope"] == "task_admission" and evidence["admission_verified"]
    assert evidence["business_effect_verified"] is False
    assert evidence["current_child_status"] == "running"
    assert verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)[
        "accepted"
    ]
    assert ledger_path(root).read_bytes() == original
    tasks = load_employee_task_ledger(root)["tasks"]
    assert len(tasks) == 1
    task = tasks[output["data"]["task_id"]]
    assert task["agent_admission"]["run_id"] == case.run.run_id
    assert task["agent_admission"]["idempotency_key"] == case.context["idempotency_key"]
    assert task["user_id"] == str(case.context["user_id"])
    assert task["tenant_id"] == str(case.context["tenant_id"])
    case.run.status = "completed"
    case.run.final_output["business_result"] = {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "status": "completed",
        "success": True,
    }
    business = ensure_terminal_business_result(case.run)
    assert business["status"] == "pending" and business["success"] is False
    assert business["evidence"]["business_effect_verified"] is False
    assert case.call.output == output and case.step.status == "completed"


@pytest.mark.parametrize(
    "changed",
    [
        "user_id",
        "tenant_id",
        "goal",
        "run_id",
        "node_id",
        "idempotency_key",
        "workspace_sha256",
        "duplicate",
        "ledger_key",
        "grants",
        "current_unknown",
    ],
)
def test_changed_or_foreign_ledger_cannot_prove_original_admission(admission, changed):
    case, output, root, _ = admission
    ledger = load_employee_task_ledger(root)
    row = ledger["tasks"][output["data"]["task_id"]]
    if changed in {"user_id", "tenant_id", "goal"}:
        row[changed] = "another-owner-or-goal"
    elif changed == "duplicate":
        ledger["tasks"]["duplicate-original-admission"] = copy.deepcopy(row)
    elif changed == "ledger_key":
        ledger["tasks"]["another-key"] = ledger["tasks"].pop(row["task_id"])
    elif changed == "grants":
        row["grants"] = {"clerk": []}
    elif changed == "current_unknown":
        row["status"] = "unknown"
    else:
        row["agent_admission"][changed] = "another-original"
    ledger_path(root).write_text(json.dumps(ledger))
    original = ledger_path(root).read_bytes()
    report = verify(case, output)
    assert report["accepted"] is False
    assert ledger_path(root).read_bytes() == original
    assert case.call.output == output


def test_copied_ledger_in_another_workspace_cannot_satisfy_frozen_contract(
    admission, tmp_path, monkeypatch
):
    case, output, root, _ = admission
    other = tmp_path / "other"
    ledger_path(other).parent.mkdir(parents=True)
    ledger_path(other).write_bytes(ledger_path(root).read_bytes())
    monkeypatch.setenv("WORKSPACE_ROOT", str(other))
    case.context["workspace_root"] = str(other)
    report = verify(case, output)
    assert report["accepted"] is False
    assert report["code"] == "result_employee_scope_mismatch"
    assert len(load_employee_task_ledger(root)["tasks"]) == 1
    assert len(load_employee_task_ledger(other)["tasks"]) == 1


@pytest.mark.parametrize(
    "changed",
    [
        "raw_unknown",
        "raw_child_unknown",
        "fake_source",
        "inline_execution",
        "run_tools",
        "foreign_context",
        "revoked_actor",
    ],
)
def test_admission_never_whitens_unknown_or_untrusted_execution(admission, changed):
    case, output, root, actor = admission
    original = ledger_path(root).read_bytes()
    if changed == "raw_unknown":
        output.update(success=False, outcome="unknown", retryable=False)
    elif changed == "raw_child_unknown":
        output["data"]["task"]["status"] = "unknown"
    elif changed == "fake_source":
        output["data"]["source"] = "model-verified"
    elif changed in {"inline_execution", "run_tools"}:
        # Even a freshly frozen contract cannot use a start receipt to prove
        # an action that may execute child tools or a different continuity op.
        case.step.params = copy.deepcopy(case.step.params)
        if changed == "inline_execution":
            case.step.params["execute_limit"] = 1
        else:
            case.step.params["continuity_action"] = "run_tools"
        case.call.params = copy.deepcopy(case.step.params)
        freeze_verification_contract(
            case.run,
            case.step,
            case.call,
            get_tool_action_spec("employee", "execute"),
            case.context,
        )
    elif changed == "foreign_context":
        case.context["tenant_id"] = str(actor.tenant_id + 1)
    else:
        from app.db.models.user import Session

        with actor.factory.begin() as db:
            db.query(Session).delete()
    report = verify(case, output)
    assert report["accepted"] is False
    assert case.call.output == output
    assert ledger_path(root).read_bytes() == original


def test_self_reported_admission_does_not_override_an_unrelated_verified_business_result(admission):
    case, output, _, _ = admission
    assert verify(case, output)["accepted"]
    case.run.status = "completed"
    # A changed source label invalidates the sealed report. The UI must not
    # use tool/output labels alone to invent an admission projection.
    case.call.metadata["verification"]["checks"][0]["source"] = "untrusted-label"
    business = ensure_terminal_business_result(case.run)
    assert "admitted_tasks" not in business["evidence"]
