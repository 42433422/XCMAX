"""Physical-device fencing and durable receipts across the existing Agent boundary."""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace

import pytest
from filelock import FileLock

from app.application import computer_use as module
from app.application.computer_use import ComputerUseService


class Adapter:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "success": True,
            "executed": True,
            "verified": True,
            "status": "verified",
            "steps_completed": 1,
            "observation": {
                "data_url": "data:image/png;base64,private",
                "aria_snapshot": "private",
                "width": 100,
            },
        }

    def validate(self, steps, verification):
        if steps == [{"action": "unsafe"}]:
            raise ValueError("unknown action")

    def execute(self, steps, verification, *, cancelled, **kwargs):
        self.calls.append((steps, verification))
        if cancelled():
            return {
                "success": False,
                "status": "cancelled",
                "verified": False,
                "steps_completed": 0,
            }
        return copy.deepcopy(self.result)

    def observe(self):
        return {
            "success": True,
            "data_url": "data:image/png;base64,private",
            "sha256": "a" * 64,
            "width": 100,
            "height": 200,
            "input_width": 100,
            "input_height": 200,
            "coordinate_space": "input",
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import run_repository, tool_permission
    from app.infrastructure.auth import agent_mod_scope

    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_USER_ID", "7")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_TENANT_ID", "9")
    monkeypatch.setattr(
        agent_mod_scope,
        "_bound_actor",
        lambda context: SimpleNamespace(id=context["user_id"], tenant_id=context["tenant_id"]),
    )
    params = {
        "request_id": "receipt-1",
        "target": "browser",
        "steps": [{"action": "navigate", "url": "https://example.com"}],
        "verification": {"kind": "url", "expected": "https://example.com/"},
    }
    context = {"user_id": "7", "tenant_id": "9", "run_id": "run-1", "step_id": "step-1"}
    run = SimpleNamespace(
        status="running",
        steps=[
            SimpleNamespace(
                step_id="step-1",
                tool_id="desktop_automation",
                action="computer_execute",
                status="running",
                params=copy.deepcopy(params),
            )
        ],
        metadata={
            "runtime_context": context.copy(),
            "approval_receipt": {
                "step_id": "step-1",
                "tool_id": "desktop_automation",
                "action": "computer_execute",
                "approved_by": "reviewer",
            },
        },
    )
    repo = SimpleNamespace(
        get=lambda run_id: run if run_id == "run-1" else None,
        latest_task_control=lambda run_id: None,
    )
    monkeypatch.setattr(run_repository, "get_agent_run_repository", lambda: repo)
    monkeypatch.setattr(tool_permission, "approval_execution_denial", lambda *args: None)
    adapter = Adapter()
    service = ComputerUseService(tmp_path / "computer-use")
    monkeypatch.setattr(service, "_browser", lambda: adapter)
    monkeypatch.setattr(service, "_desktop", lambda: adapter)
    return service, adapter, params, context, run, repo


def test_replays_only_original_receipt_without_repeating_input(setup):
    service, adapter, params, context, *_ = setup
    assert service.invoke("computer_execute", params, context)["verified"] is True
    reloaded = ComputerUseService(service.root)
    replay = reloaded.invoke("computer_execute", params, context)
    assert replay["replayed"] is True and replay["verified"] is True
    assert len(adapter.calls) == 1
    saved = list(service.root.rglob("effect-*.json"))[0].read_text()
    assert "data:image" not in saved and "aria_snapshot" not in saved
    assert replay["observation"]["width"] == 100


def test_same_request_with_changed_plan_is_never_executed(setup):
    service, adapter, params, context, *_ = setup
    service.invoke("computer_execute", params, context)
    changed = {**params, "steps": [{"action": "click", "target": {"selector": "#submit"}}]}
    assert (
        service.invoke("computer_execute", changed, context)["error_code"]
        == "computer_request_conflict"
    )
    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "mutation", ["unapproved", "waiting", "wrong_step", "tampered_params", "wrong_tenant"]
)
def test_requires_persisted_matching_approved_agent_step(setup, mutation):
    service, adapter, params, context, run, _ = setup
    if mutation == "unapproved":
        run.metadata.pop("approval_receipt")
    elif mutation == "waiting":
        run.status = "waiting_user"
    elif mutation == "wrong_step":
        context["step_id"] = "other"
    elif mutation == "tampered_params":
        params["steps"] = [{"action": "click", "target": {"selector": "#delete"}}]
    else:
        run.metadata["runtime_context"]["tenant_id"] = "88"
    assert (
        service.invoke("computer_execute", params, context)["error_code"]
        == "computer_permission_denied"
    )
    assert adapter.calls == []


def test_unbound_identity_cannot_grant_desktop_by_claiming_user_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_COMPUTER_USE_USER_ID", "7")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_TENANT_ID", "9")
    result = ComputerUseService(tmp_path).invoke(
        "computer_status", {}, {"user_id": "7", "tenant_id": "9", "approved": True}
    )
    assert result["error_code"] == "computer_permission_denied"


@pytest.mark.parametrize("changes", [{"user_id": "8"}, {"tenant_id": "8"}])
def test_receipts_are_owner_and_tenant_bound(setup, changes):
    service, adapter, params, context, *_ = setup
    service.invoke("computer_execute", params, context)
    result = service.invoke(
        "computer_result", {"request_id": params["request_id"]}, {**context, **changes}
    )
    assert result["error_code"] == "computer_permission_denied"


def test_unknown_write_receipt_survives_restart_and_is_not_replayed(setup, monkeypatch):
    service, adapter, params, context, *_ = setup

    def lost(*args, **kwargs):
        adapter.calls.append("input issued")
        raise RuntimeError("reply lost")

    monkeypatch.setattr(adapter, "execute", lost)
    result = service.invoke("computer_execute", params, context)
    assert result["reconciliation_required"] and not result["retryable"]
    replay = ComputerUseService(service.root).invoke("computer_execute", params, context)
    assert replay["replayed"] and replay["outcome"] == "unknown"
    assert len(adapter.calls) == 1


def test_started_receipt_cannot_be_reexecuted_after_crash(setup):
    service, adapter, params, context, *_ = setup
    path = service._path(service._owner(context), "effect", params["request_id"])
    service._write(path, {"state": "running", "fingerprint": module._fingerprint(params)})
    result = service.invoke("computer_execute", params, context)
    assert result["error_code"] == "computer_outcome_unknown"
    assert result["reconciliation_required"] and adapter.calls == []


def test_executed_but_unverified_is_not_business_success(setup):
    service, adapter, params, context, *_ = setup
    adapter.result.update(success=False, verified=False, status="needs_verification")
    result = service.invoke("computer_execute", params, context)
    assert result["success"] is False and result["reconciliation_required"] is True
    assert service.invoke("computer_execute", params, context)["replayed"] is True
    assert len(adapter.calls) == 1


def test_partial_first_input_is_reconciled_even_with_zero_complete_steps(setup):
    service, adapter, params, context, *_ = setup
    adapter.result = {
        "success": False,
        "verified": False,
        "status": "cancelled",
        "code": "failsafe",
        "executed": None,
        "may_have_executed": True,
        "steps_completed": 0,
    }
    result = service.invoke("computer_execute", params, context)
    assert result["reconciliation_required"] and result["outcome"] == "unknown"
    assert result["error_code"] == "failsafe"


def test_same_request_cannot_cross_target_locks(setup):
    service, adapter, params, context, *_ = setup
    path = service._path(service._owner(context), "effect", params["request_id"])
    path.parent.mkdir(parents=True)
    with FileLock(str(path) + ".lock"):
        browser = service.invoke("computer_execute", params, context)
        desktop = service.invoke("computer_execute", {**params, "target": "desktop"}, context)
    assert browser["error_code"] == desktop["error_code"] == "computer_busy"
    assert adapter.calls == []


def test_device_lease_prevents_parallel_observation(setup):
    service, adapter, params, context, *_ = setup
    service.root.mkdir()
    with FileLock(str(service.root / "device.lock")):
        assert service.invoke("computer_observe", {}, context)["error_code"] == "computer_busy"


def test_stale_observation_and_reuse_are_rejected(setup):
    service, adapter, params, context, run, _ = setup
    observed = service.invoke("computer_observe", {}, context)
    params.update(target="desktop", snapshot_id=observed["snapshot_id"])
    run.steps[0].params = copy.deepcopy(params)
    assert service.invoke("computer_execute", params, context)["success"] is True
    params["request_id"] = "another"
    run.steps[0].params = copy.deepcopy(params)
    result = service.invoke("computer_execute", params, context)
    assert result["error_code"] == "stale_observation"
    assert len(adapter.calls) == 1


def test_expired_observation_is_rejected_before_input(setup):
    service, adapter, params, context, run, _ = setup
    observed = service.invoke("computer_observe", {}, context)
    path = service._path(service._owner(context), "observation", observed["snapshot_id"])
    body = service._read(path)
    service._write(path, {**body, "created_at": 1})
    params.update(target="desktop", snapshot_id=observed["snapshot_id"])
    run.steps[0].params = copy.deepcopy(params)
    assert service.invoke("computer_execute", params, context)["error_code"] == "stale_observation"
    assert adapter.calls == []


def test_stop_signal_does_not_wait_for_execution_lock(setup, monkeypatch):
    service, adapter, params, context, *_ = setup
    entered, proceed = threading.Event(), threading.Event()

    def execute(*args, cancelled, **kwargs):
        entered.set()
        assert proceed.wait(5)
        return (
            {
                "success": False,
                "status": "cancelled",
                "verified": False,
                "executed": False,
                "steps_completed": 0,
            }
            if cancelled()
            else {"success": True}
        )

    monkeypatch.setattr(adapter, "execute", execute)
    outputs = []
    thread = threading.Thread(
        target=lambda: outputs.append(service.invoke("computer_execute", params, context))
    )
    thread.start()
    try:
        assert entered.wait(5)
        result = service.invoke("computer_stop", {"request_id": params["request_id"]}, context)
        assert result["status"] == "stop_requested" and not result["stopped"]
    finally:
        proceed.set()
        thread.join(5)
    assert not thread.is_alive() and outputs[0]["status"] == "cancelled"


def test_task_cancel_command_is_observed_before_input(setup):
    service, adapter, params, context, run, repo = setup
    repo.latest_task_control = lambda run_id: SimpleNamespace(action="cancel")
    assert service.invoke("computer_execute", params, context)["status"] == "cancelled"


def test_terminal_receipt_write_failure_stays_unknown(setup, monkeypatch):
    service, adapter, params, context, *_ = setup
    write = service._write

    def failed_write(path, body):
        if body.get("state") == "finished":
            raise OSError("disk full")
        return write(path, body)

    monkeypatch.setattr(service, "_write", failed_write)
    result = service.invoke("computer_execute", params, context)
    assert result["error_code"] == "computer_receipt_unknown"
    assert (
        ComputerUseService(service.root).invoke("computer_execute", params, context)["outcome"]
        == "unknown"
    )
    assert len(adapter.calls) == 1


def test_host_disabled_still_allows_owned_receipt_lookup(setup, monkeypatch):
    service, adapter, params, context, *_ = setup
    service.invoke("computer_execute", params, context)
    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "0")
    assert (
        service.invoke("computer_result", {"request_id": params["request_id"]}, context)["verified"]
        is True
    )
    assert (
        service.invoke("computer_execute", {**params, "request_id": "new"}, context)["error_code"]
        == "computer_use_disabled"
    )


def test_full_browser_plan_is_validated_before_started_receipt(setup):
    service, adapter, params, context, run, _ = setup
    params["steps"] = [{"action": "unsafe"}]
    run.steps[0].params = copy.deepcopy(params)
    assert (
        service.invoke("computer_execute", params, context)["error_code"]
        == "computer_params_invalid"
    )
    assert not list(service.root.rglob("effect-*.json")) and adapter.calls == []


def test_catalog_declares_approval_no_automatic_input_retry():
    from pathlib import Path

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    spec = get_tool_action_spec("desktop_automation", "computer_execute")
    assert spec.risk == "high" and not spec.idempotent and spec.retry["max_attempts"] == 1
    source = Path(__file__).resolve().parents[1] / "config/risk_actions.registry.json"
    registry = json.loads(source.read_text())
    assert (
        registry["tools"]["desktop_automation"]["actions"]["computer_execute"]["approval"]
        == "always"
    )
