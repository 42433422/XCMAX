from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from modstore_server.duty_workforce_burnin import assess_burn_in_eligibility
from modstore_server.duty_workforce_contracts import workforce_contract_map

REPO_ROOT = Path(__file__).resolve().parents[3]
EMPLOYEE_ROOT = REPO_ROOT / "FHD" / "mods" / "_employees"
EMPLOYEES = {
    "code-validator": "code_validator",
    "delivery-receipt-officer": "delivery_receipt_officer",
    "doc-knowledge-curator": "doc_knowledge_curator",
    "quality-validator": "quality_validator",
    "sandbox-tester": "sandbox_tester",
}


def _manifest(employee_id: str) -> dict:
    return json.loads(
        (EMPLOYEE_ROOT / employee_id / "manifest.json").read_text(encoding="utf-8")
    )


def _module(employee_id: str) -> ModuleType:
    module_name = EMPLOYEES[employee_id]
    path = EMPLOYEE_ROOT / employee_id / "backend" / "employees" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("employee_id", sorted(EMPLOYEES))
def test_reviewed_fixture_executes_real_read_only_capability(employee_id: str) -> None:
    manifest = _manifest(employee_id)
    actions = manifest["employee_config_v2"]["actions"]
    direct = actions["direct_python"]

    assert actions["handlers"] == ["direct_python"]
    assert direct["implementation"] == "employee_module"
    assert direct["execution_mode"] == "deterministic"
    assert direct["read_only"] is True
    assert direct["burn_in_policy"] == {
        "reviewed": True,
        "scope": "fixture_only",
        "external_effects": False,
    }

    output = _module(employee_id).run(direct["burn_in_fixture"], {})
    assert output["ok"] is True
    assert output["status"] == "approved"
    assert len(output["summary"]) >= 10
    assert output["evidence"]
    assert output["read_only"] is True
    assert output["side_effects"] == []
    assert set(direct["output_schema"]["required"]).issubset(output)

    contract = workforce_contract_map()[employee_id]
    eligibility = assess_burn_in_eligibility(employee_id, contract, manifest)
    assert eligibility["eligible"] is True
    assert eligibility["reason"] == "eligible_read_only_direct_python"


def test_code_validator_blocks_dangerous_source_without_executing_it() -> None:
    output = _module("code-validator").run(
        {
            "language": "python",
            "source": "import subprocess\nsubprocess.run(['echo', 'x'])\n",
        },
        {},
    )
    assert output["status"] == "rejected"
    assert {item["code"] for item in output["issues"]} == {
        "blocked_import",
        "blocked_call",
    }
    assert output["side_effects"] == []


def test_delivery_receipt_requires_customer_value_evidence() -> None:
    output = _module("delivery-receipt-officer").run(
        {
            "receipt": {
                "goal_id": "goal-1",
                "artifact_id": "artifact-1",
                "customer_id": "customer-1",
                "acceptance": [{"passed": True}],
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["blockers"] == ["value_evidence_missing"]


def test_knowledge_curator_rejects_unverified_fact() -> None:
    output = _module("doc-knowledge-curator").run(
        {"facts": [{"statement": "claim", "source": "probe://1", "verified": False}]},
        {},
    )
    assert output["status"] == "rejected"
    assert output["accepted_entries"] == []
    assert output["rejected_entries"][0]["reasons"] == ["not_verified"]


def test_quality_validator_requires_matching_employee_module() -> None:
    output = _module("quality-validator").run(
        {
            "pack": {
                "manifest": {
                    "id": "missing-module",
                    "employee_config_v2": {"actions": {"handlers": ["direct_python"]}},
                },
                "files": ["manifest.json"],
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["issues"] == [
        {
            "code": "employee_module_missing",
            "path": "backend/employees/missing_module.py",
        }
    ]


def test_sandbox_receipt_rejects_network_attempt() -> None:
    output = _module("sandbox-tester").run(
        {
            "test_run": {
                "sandboxed": True,
                "exit_code": 0,
                "network_attempts": 1,
                "filesystem_escape_attempts": 0,
                "reproducible": True,
                "tests": [{"status": "passed"}],
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["blockers"] == ["no_network_attempts"]
