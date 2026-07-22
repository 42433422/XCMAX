"""employee_risk_middleware delegates to the autonomy risk SSOT."""

from __future__ import annotations

import pytest

from modstore_server.employee_risk_middleware import assess_risk, gate_action_or_block


def _reload_guard() -> None:
    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    reload_autonomy_guard()


@pytest.fixture(autouse=True)
def _isolated_autonomy_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    _reload_guard()


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
    assert gate.get("decision") == "auto_approve"


def test_strict_burn_in_contract_is_low_only_when_every_safety_flag_is_present() -> None:
    payload = {
        "burn_in": True,
        "burn_in_read_only": True,
        "suppress_employee_im": True,
        "suppress_handoff": True,
        "suppress_change_requests": True,
        "suppress_lifecycle_events": True,
        "work_contract": {"risk_level": "low"},
    }

    gate = gate_action_or_block("safe-observer", {}, ["llm_md", "echo", "agent"], payload)
    assert gate.get("ok") is True
    assert gate.get("risk_level") == "low"
    assert gate.get("decision") == "allow"

    incomplete = {**payload, "suppress_handoff": False}
    level, _reason = assess_risk({}, ["agent"])
    assert level == "medium"
    fallback = gate_action_or_block("safe-observer", {}, ["agent"], incomplete)
    assert fallback.get("risk_level") == "medium"
