from __future__ import annotations

from retort_engine.contracts import (
    RETORT_CONTRACT_COMPATIBILITY_VERSION,
    RETORT_CONTRACT_SCHEMAS,
    contract_compatibility_report,
    validate_contract,
)


def test_contract_validation_exposes_stable_version_and_accepts_extra_fields() -> None:
    payload = {
        "status": "ready",
        "project": "packages/retort_engine",
        "summary": {},
        "cases": [],
        "evidence": {},
        "future_optional_field": "allowed",
    }

    result = validate_contract("employee_patch_closure_result", payload)

    assert result["valid"] is True
    assert result["missing"] == []
    assert result["version"] == RETORT_CONTRACT_COMPATIBILITY_VERSION


def test_contract_validation_rejects_missing_required_field() -> None:
    payload = {
        "status": "ready",
        "project": "packages/retort_engine",
        "summary": {},
        "cases": [],
    }

    result = validate_contract("employee_patch_closure_result", payload)

    assert result["valid"] is False
    assert result["missing"] == ["evidence"]


def test_contract_compatibility_accepts_exact_required_surface() -> None:
    previous = RETORT_CONTRACT_SCHEMAS["quality_gate_bundle_result"]

    report = contract_compatibility_report("quality_gate_bundle_result", previous)

    assert report["compatible"] is True
    assert report["append_only"] is True
    assert report["producer_compatible"] is True
    assert report["breaking_change"] is False
    assert report["newly_required_fields"] == []
    assert report["removed_historical_fields"] == []


def test_contract_compatibility_flags_new_required_fields_as_breaking_for_old_producers() -> None:
    previous = ("status", "project", "summary")

    report = contract_compatibility_report("quality_gate_bundle_result", previous)

    assert report["compatible"] is False
    assert report["append_only"] is True
    assert report["producer_compatible"] is False
    assert report["breaking_change"] is True
    assert report["newly_required_fields"] == ["gates", "evidence"]
    assert report["removed_historical_fields"] == []


def test_contract_compatibility_flags_removed_historical_required_fields() -> None:
    previous = ("status", "project", "summary", "gates", "evidence", "legacy_receipt")

    report = contract_compatibility_report("quality_gate_bundle_result", previous)

    assert report["compatible"] is False
    assert report["append_only"] is False
    assert report["producer_compatible"] is True
    assert report["breaking_change"] is True
    assert report["newly_required_fields"] == []
    assert report["removed_historical_fields"] == ["legacy_receipt"]


def test_contract_compatibility_separates_append_only_from_payload_validation() -> None:
    previous = ("status", "project", "summary")
    payload = {
        "status": "ready",
        "project": "packages/retort_engine",
        "summary": {},
        "gates": [],
        "evidence": {},
    }

    compatibility = contract_compatibility_report("quality_gate_bundle_result", previous)
    validation = validate_contract("quality_gate_bundle_result", payload)

    assert compatibility["append_only"] is True
    assert compatibility["producer_compatible"] is False
    assert validation["valid"] is True
