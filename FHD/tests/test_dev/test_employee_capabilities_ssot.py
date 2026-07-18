"""Employee capability resolution SSOT tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.employee.capability import parse_capabilities
from scripts.dev import employee_capabilities_ssot as capability_ssot

FHD_ROOT = Path(__file__).resolve().parents[2]


def test_generated_capability_outputs_are_current():
    assert capability_ssot.main(["--check"]) == 0


def test_effective_registry_keeps_employee_ssot_identity_spaces_separate():
    registry = json.loads(
        (FHD_ROOT / "metrics" / "employee-capability-registry.generated.json").read_text(
            encoding="utf-8"
        )
    )
    manifests = list((FHD_ROOT / "mods" / "_employees").glob("*/manifest.json"))
    roster = json.loads((FHD_ROOT / "config" / "duty_roster.json").read_text(encoding="utf-8"))
    planned_ids = {employee_id for area in roster["areas"].values() for employee_id in area["ids"]}

    assert registry["summary"]["employee_pack_manifest_count"] == len(manifests)
    assert len(registry["employee_packs"]) == len(manifests)
    assert registry["summary"]["admin_planned_employee_pack_count"] == len(planned_ids)
    assert registry["summary"]["enterprise_workflow_employee_count"] == len(
        roster["enterprise_employees"]
    )
    assert {row["employee_id"] for row in registry["enterprise_workflow_employees"]} == set(
        roster["enterprise_employees"]
    )
    assert planned_ids.isdisjoint(roster["enterprise_employees"])


def test_unrostered_support_packs_are_not_counted_as_planned_employees():
    registry = json.loads(
        (FHD_ROOT / "metrics" / "employee-capability-registry.generated.json").read_text(
            encoding="utf-8"
        )
    )
    packs = {row["employee_id"]: row for row in registry["employee_packs"]}

    assert packs["artifact-generator"]["identity_scope"] == "admin_planned_employee"
    assert packs["artifact-generator"]["admin_roster"]["planned"] is True
    assert packs["excel-generate-employee"]["identity_scope"] == "unrostered_employee_pack"
    assert packs["excel-generate-employee"]["admin_roster"] == {
        "planned": False,
        "areas": [],
        "departments": [],
    }


def test_registry_fails_when_planned_employee_pack_manifest_is_missing(monkeypatch):
    contract = capability_ssot.load_contract()
    roster_path = FHD_ROOT / "config" / "duty_roster.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster["areas"]["platform-core"]["ids"].append("missing-planned-employee")
    monkeypatch.setattr(capability_ssot, "_load_json_object", lambda *_args, **_kwargs: roster)

    with pytest.raises(ValueError, match="missing-planned-employee"):
        capability_ssot.build_effective_registry(contract)


def test_registry_fails_when_admin_and_enterprise_identity_spaces_overlap(monkeypatch):
    contract = capability_ssot.load_contract()
    roster_path = FHD_ROOT / "config" / "duty_roster.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster["enterprise_employees"]["artifact-generator"] = {
        "label": "invalid overlap",
        "enterprise_layer": "execution",
        "listing": "unlisted",
        "source": "test",
        "mod_id": "test",
    }
    monkeypatch.setattr(capability_ssot, "_load_json_object", lambda *_args, **_kwargs: roster)

    with pytest.raises(ValueError, match="identity spaces overlap"):
        capability_ssot.build_effective_registry(contract)


def test_runtime_uses_contract_ordered_union_and_first_description():
    manifest = {
        "employee": {
            "capabilities": [{"label": "Data Sync", "description": "capability description"}]
        },
        "employee_config_v2": {
            "cognition": {
                "skills": [
                    {"name": "data sync", "brief": "later description"},
                    {"name": "skill-extra", "brief": "extra"},
                ]
            }
        },
    }

    capabilities = parse_capabilities(manifest)

    assert [(cap.label, cap.description) for cap in capabilities] == [
        ("Data Sync", "capability description"),
        ("skill-extra", "extra"),
    ]
