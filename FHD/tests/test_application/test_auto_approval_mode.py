"""自动审批模式：只有用户明确开启后才按共享自治策略授权步骤。"""

from __future__ import annotations

import json
from pathlib import Path

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.run_repair import RunRepair


def _step(tool_id: str = "employee", action: str = "execute", risk: str = "medium") -> AgentStep:
    return AgentStep(
        node_id="n1",
        tool_id=tool_id,
        action=action,
        risk=risk,
        idempotent=False,
    )


def test_medium_write_step_still_waits_without_auto_mode():
    assert RunRepair.can_auto_execute(_step()) is False
    assert RunRepair.can_auto_execute(_step(), {}) is False
    assert RunRepair.can_auto_execute(_step(), {"chat_approval_mode": "manual"}) is False


def test_auto_mode_uses_shared_autonomy_policy_for_registered_medium_action(tmp_path, monkeypatch):
    from app.domain.autonomy import autonomy_guard

    registry = json.loads(
        (Path(__file__).parents[2] / "config/risk_actions.registry.json").read_text()
    )
    registry["tools"]["employee"]["actions"]["execute"]["allow_auto_execute"] = True
    path = tmp_path / "risk-actions.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setenv("XCAGI_RISK_REGISTRY_PATH", str(path))
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "auto_approve")
    monkeypatch.setattr(autonomy_guard, "_GUARD", None)
    monkeypatch.setattr(autonomy_guard, "_GUARD_POLICY_ENV", "")
    decision = RunRepair.auto_execution_decision(_step(), {"chat_approval_mode": "auto"})
    assert decision is not None
    assert decision["decision"] == "auto_approved"
    assert decision["risk"] == "medium"


def test_auto_mode_preserves_registered_human_approval_requirement():
    assert RunRepair.auto_execution_decision(_step(), {"chat_approval_mode": "auto"}) is None


def test_auto_mode_never_bypasses_hard_boundary():
    # 未注册动作由自治策略 fail-closed，自动审批模式也不能放行。
    decision = RunRepair.auto_execution_decision(
        _step(tool_id="unknown_tool", action="unknown_action"),
        {"chat_approval_mode": "auto"},
    )
    assert decision is None
    decision = RunRepair.auto_execution_decision(
        _step(tool_id="", action="db_migration"),
        {"chat_approval_mode": "auto"},
    )
    assert decision is None
