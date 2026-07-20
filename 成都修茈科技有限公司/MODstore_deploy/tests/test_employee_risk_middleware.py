"""employee_risk_middleware delegates to the autonomy risk SSOT."""

from __future__ import annotations

from modstore_server.employee_risk_middleware import assess_risk, gate_action_or_block


def _reload_guard() -> None:
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    reload_autonomy_guard()


def test_assess_risk_agent_handler_is_medium() -> None:
    level, _reason = assess_risk({}, ["llm_md", "echo", "agent"])
    assert level == "medium"


def test_gate_auto_approves_registered_medium_action_by_default(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    _reload_guard()
    manifest = {"employee_config_v2": {}}
    gate = gate_action_or_block("some-employee", manifest, ["agent"], {})
    assert gate.get("ok") is True
    assert gate.get("risk_level") == "medium"
    assert gate.get("decision") == "auto_approve"


def test_legacy_manifest_self_approve_does_not_override_registry_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    _reload_guard()
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
    assert gate.get("decision") == "auto_approve"


def test_env_policy_auto_approves_medium(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "auto_approve")
    _reload_guard()
    gate = gate_action_or_block("x", {}, ["agent"], {})
    assert gate.get("ok") is True
    assert gate.get("decision") == "auto_approve"


def test_gate_allows_medium_with_allow_medium_risk_payload() -> None:
    gate = gate_action_or_block("x", {}, ["agent"], {"allow_medium_risk": True})
    assert gate.get("ok") is True
