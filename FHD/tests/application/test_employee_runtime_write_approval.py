"""employee_runtime.write_approval 写操作审批门 + compose_gates 单元测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime.write_approval import (
    build_write_approval_gate,
    compose_gates,
)


@pytest.mark.parametrize(
    "name,args",
    [
        ("products_bulk_import", {"rows": []}),
        ("products", {"ids": [1]}),
        ("products", {"action": "unregistered", "ids": [1]}),
    ],
)
def test_write_gate_never_creates_an_unresumable_approval(monkeypatch, name, args):
    execute = MagicMock(side_effect=AssertionError("unknown actions cannot create a task"))
    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", execute
    )
    verdict = build_write_approval_gate("employee", {})(name, args)
    assert verdict["ok"] is False
    assert verdict["blocked"] is True
    assert not verdict.get("pending_approval")
    execute.assert_not_called()


def test_write_gate_stages_canonical_run_and_returns_original_receipt(monkeypatch):
    receipt = {
        "success": False,
        "execution_state": "waiting_approval",
        "agent_run_id": "run-original",
        "task_id": "task-original",
        "approval_request_id": "approval-original",
    }
    execute = MagicMock(return_value=json.dumps(receipt))
    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", execute
    )
    context = {"user_id": "7", "tenant_id": 1, "turn_id": "turn"}
    gate = build_write_approval_gate("employee", runtime_context=context)
    verdict = gate("products", {"action": "batch_create", "products": [{"name": "test-product"}]})
    assert verdict["ok"] is False
    assert verdict["pending_approval"] is True
    assert verdict["execution_result"] == receipt
    assert verdict["agent_run_id"] == "run-original"
    execute.assert_called_once_with(
        {
            "tool_id": "products",
            "action": "batch_create",
            "params": {"products": [{"name": "test-product"}]},
        },
        workspace_root=None,
        runtime_context=context,
        require_approval=True,
    )


class TestComposeGates:
    def test_all_none_returns_none(self):
        assert compose_gates(None, None) is None

    def test_single_gate_passthrough(self):
        g = lambda name, args: {"ok": True}
        combined = compose_gates(g, None)
        assert combined("t", {})["ok"] is True

    def test_returns_first_failure(self):
        g_ok = lambda name, args: {"ok": True}
        g_block = lambda name, args: {"ok": False, "reason": "blocked"}
        combined = compose_gates(g_ok, g_block)
        verdict = combined("t", {})
        assert verdict["ok"] is False
        assert verdict["reason"] == "blocked"

    def test_all_pass(self):
        g1 = lambda name, args: {"ok": True}
        g2 = lambda name, args: {"ok": True}
        assert compose_gates(g1, g2)("t", {})["ok"] is True

    def test_gate_raising_recoverable_blocks(self):
        def boom(name, args):
            raise ValueError("recoverable")

        g_ok = lambda name, args: {"ok": True}
        combined = compose_gates(boom, g_ok)
        assert combined("t", {})["ok"] is False

    @pytest.mark.parametrize("verdict", [{}, None, [], {"ok": 1}, {"ok": "yes"}])
    def test_invalid_verdict_blocks(self, verdict):
        assert compose_gates(lambda name, args: verdict)("t", {})["ok"] is False


def test_late_registered_write_uses_live_policy_and_only_server_context(monkeypatch):
    gate = build_write_approval_gate(
        "employee",
        {"tenant_id": "attacker", "human_approved": True},
        runtime_context={"tenant_id": "owner"},
    )
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.list_write_tools", lambda: {"late_write"}
    )
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.get_workflow_tools_from_registry",
        lambda: {"late_write": {"actions": {"create": {"idempotent": False}}}},
    )
    receipt = {
        "success": False,
        "execution_state": "waiting_approval",
        "approval_request_ids": ["persisted-approval"],
    }
    with patch(
        "app.application.tools.registered_capabilities.execute_registered_capability",
        return_value=json.dumps(receipt),
    ) as execute:
        result = gate("late_write", {"human_approved": True, "approved_by": "attacker"})
    assert result["ok"] is False and result["pending_approval"] is True
    assert execute.call_args.kwargs["runtime_context"] == {"tenant_id": "owner"}
    assert execute.call_args.kwargs["require_approval"] is True
