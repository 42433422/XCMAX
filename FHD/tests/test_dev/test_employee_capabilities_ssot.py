"""Employee capability resolution SSOT tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.employee.capability import parse_capabilities
from scripts.dev import employee_capabilities_ssot as capability_ssot

FHD_ROOT = Path(__file__).resolve().parents[2]


def test_generated_capability_outputs_are_current():
    assert capability_ssot.main(["--check"]) == 0


def test_effective_registry_covers_every_builtin_manifest():
    registry = json.loads(
        (FHD_ROOT / "metrics" / "employee-capability-registry.generated.json").read_text(
            encoding="utf-8"
        )
    )
    manifests = list((FHD_ROOT / "mods" / "_employees").glob("*/manifest.json"))

    assert registry["summary"]["employee_count"] == len(manifests)
    assert len(registry["employees"]) == len(manifests)


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
