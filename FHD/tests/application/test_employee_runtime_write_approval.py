"""employee_runtime.write_approval 写操作审批门 + compose_gates 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime.write_approval import (
    build_write_approval_gate,
    compose_gates,
)


def test_late_registered_write_uses_live_policy_and_only_server_context(monkeypatch):
    gate = build_write_approval_gate(
        "employee",
        {"tenant_id": "attacker", "human_approved": True},
        runtime_context={"tenant_id": "owner"},
    )
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.list_write_tools", lambda: {"late_write"}
    )
    with patch("app.application.workflow.approval_policy.WorkflowApprovalPolicy") as policy:
        policy.return_value.evaluate_plan.return_value = MagicMock(
            all_approved=False,
            any_rejected=False,
            pending_approval=True,
            approval_request_ids=["persisted-approval"],
        )
        result = gate("late_write", {"human_approved": True, "approved_by": "attacker"})
    assert result["ok"] is False and result["pending_approval"] is True
    assert policy.return_value.evaluate_plan.call_args.kwargs["runtime_context"] == {
        "tenant_id": "owner"
    }


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
