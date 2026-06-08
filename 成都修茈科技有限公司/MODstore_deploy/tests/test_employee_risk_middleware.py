"""employee_risk_middleware：handlers 推断与 manifest 自治闸门。"""

from __future__ import annotations

from modstore_server.employee_risk_middleware import assess_risk, gate_action_or_block


def test_assess_risk_agent_handler_is_medium() -> None:
    level, _reason = assess_risk({}, ["llm_md", "echo", "agent"])
    assert level == "medium"


def test_gate_blocks_medium_without_autonomy() -> None:
    manifest = {"employee_config_v2": {}}
    gate = gate_action_or_block("some-employee", manifest, ["agent"], {})
    assert gate.get("ok") is False
    assert gate.get("risk_level") == "medium"


def test_gate_allows_medium_with_medium_self_approve() -> None:
    manifest = {
        "employee_config_v2": {
            "autonomy": {"medium_self_approve": True},
        }
    }
    gate = gate_action_or_block(
        "change-request-auditor",
        manifest,
        ["llm_md", "echo", "agent"],
        {},
    )
    assert gate.get("ok") is True
    assert gate.get("risk_level") == "medium"


def test_gate_allows_medium_with_allow_medium_risk_payload() -> None:
    gate = gate_action_or_block("x", {}, ["agent"], {"allow_medium_risk": True})
    assert gate.get("ok") is True
