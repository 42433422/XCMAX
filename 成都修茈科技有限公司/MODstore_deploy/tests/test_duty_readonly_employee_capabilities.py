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
    "ecosystem-delivery-reporter": "ecosystem_delivery_reporter",
    "ecosystem-investor-portal-officer": "ecosystem_investor_portal_officer",
    "ecosystem-joint-catalog-officer": "ecosystem_joint_catalog_officer",
    "ecosystem-revenue-share-reconciler": "ecosystem_revenue_share_reconciler",
    "employee-planner": "employee_planner",
    "employee-pack-quality-interviewer": "employee_pack_quality_interviewer",
    "enterprise-adoption-officer": "enterprise_adoption_officer",
    "quality-validator": "quality_validator",
    "sandbox-tester": "sandbox_tester",
    "test-qa-runner": "test_qa_runner",
    "top-architect": "top_architect",
}


def _manifest(employee_id: str) -> dict:
    return json.loads((EMPLOYEE_ROOT / employee_id / "manifest.json").read_text(encoding="utf-8"))


def _module(employee_id: str) -> ModuleType:
    module_name = EMPLOYEES.get(employee_id) or employee_id.replace("-", "_")
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
    assert direct["burn_in_policy"]["reviewed"] is True
    assert direct["burn_in_policy"]["scope"] == "fixture_only"
    assert direct["burn_in_policy"]["external_effects"] is False

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
    assert eligibility["reason"] == (
        "eligible_medium_read_only_direct_python"
        if employee_id == "top-architect"
        else "eligible_read_only_direct_python"
    )


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


def test_delivery_receipt_missing_receipt_is_rejected_not_handler_failed() -> None:
    """事故/任务完成派发常不带 receipt：应只读驳回，勿 ok=False 刷红大厅。"""
    output = _module("delivery-receipt-officer").run(
        {"task": "[employee.task.done] ecosystem-joint-catalog-officer employee.task.done"},
        {},
    )
    assert output["ok"] is True
    assert output["status"] == "rejected"
    assert output["blockers"] == ["missing_receipt"]
    assert output["read_only"] is True
    assert output["side_effects"] == []


def test_knowledge_curator_rejects_unverified_fact() -> None:
    output = _module("doc-knowledge-curator").run(
        {"facts": [{"statement": "claim", "source": "probe://1", "verified": False}]},
        {},
    )
    assert output["status"] == "rejected"
    assert output["accepted_entries"] == []
    assert output["rejected_entries"][0]["reasons"] == ["not_verified"]


@pytest.mark.parametrize(
    ("employee_id", "payload"),
    [
        ("doc-knowledge-curator", {"facts": []}),
        ("ecosystem-delivery-reporter", {"deliveries": []}),
        ("ecosystem-revenue-share-reconciler", {"entries": []}),
        ("enterprise-adoption-officer", {"tenants": []}),
    ],
)
def test_authoritative_empty_input_is_no_effect_not_handler_failure(
    employee_id: str, payload: dict
) -> None:
    output = _module(employee_id).run(payload, {})

    assert output["ok"] is True
    assert output["status"] == "no_data"
    assert output["no_effect"] is True
    assert output["read_only"] is True
    assert output["side_effects"] == []


def test_empty_payment_ledger_is_no_effect_not_reconciled() -> None:
    manifest = json.loads(
        (EMPLOYEE_ROOT / "payment-billing-reconciler" / "manifest.json").read_text()
    )
    path = (
        EMPLOYEE_ROOT
        / "payment-billing-reconciler"
        / "backend"
        / "employees"
        / "payment_billing_reconciler.py"
    )
    spec = importlib.util.spec_from_file_location("test_payment_billing_reconciler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = module.run({"ledger": {"orders": [], "payments": [], "refunds": []}}, {})

    assert output["ok"] is True
    assert output["status"] == "no_data"
    assert output["reconciled"] is False
    required = manifest["employee_config_v2"]["actions"]["direct_python"]["output_schema"][
        "required"
    ]
    assert set(required).issubset(output)


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


def test_delivery_report_requires_next_step_for_breached_sla() -> None:
    output = _module("ecosystem-delivery-reporter").run(
        {
            "deliveries": [
                {
                    "partner_id": "partner-1",
                    "delivery_receipt_id": "receipt-1",
                    "owner": "owner-1",
                    "sla_status": "breached",
                }
            ]
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["blockers"] == [{"index": 0, "reasons": ["next_step"]}]


def test_revenue_share_reconciler_reports_difference_without_payment_side_effect() -> None:
    output = _module("ecosystem-revenue-share-reconciler").run(
        {
            "entries": [
                {
                    "partner_id": "partner-1",
                    "gross_cents": 10000,
                    "share_bps": 1000,
                    "recorded_share_cents": 900,
                }
            ]
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["differences"][0]["delta_cents"] == -100
    assert output["side_effects"] == []


def test_quality_interviewer_rejects_hollow_handlers() -> None:
    output = _module("employee-pack-quality-interviewer").run(
        {
            "capability": {
                "input_contract": {"required": ["artifact"]},
                "handlers": ["echo", "llm_md"],
                "acceptance": ["receipt"],
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["gaps"] == ["executable_handler_missing"]


def test_top_architect_reports_forbidden_dependency_direction() -> None:
    output = _module("top-architect").run(
        {
            "architecture": {
                "modules": [
                    {"name": "domain", "layer": "domain"},
                    {"name": "api", "layer": "interface"},
                ],
                "dependencies": [{"source": "domain", "target": "api"}],
                "allowed_dependencies": {"domain": [], "interface": ["domain"]},
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["violations"][0]["reason"] == "forbidden_layer_dependency:domain->interface"


def test_investor_snapshot_rejects_private_customer_fields() -> None:
    output = _module("ecosystem-investor-portal-officer").run(
        {
            "milestones": [
                {
                    "id": "delivery",
                    "status": "on_track",
                    "progress_pct": 80,
                    "customer_id": "private-customer",
                }
            ],
            "risks": [],
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["public_snapshot"] == {}
    assert output["redacted_fields"] == ["input.milestones[0].customer_id"]


def test_joint_catalog_reports_version_drift() -> None:
    output = _module("ecosystem-joint-catalog-officer").run(
        {
            "primary_catalog": [{"id": "pack", "version": "2.0", "status": "listed"}],
            "partner_catalog": [{"id": "pack", "version": "1.0", "status": "listed"}],
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["consistent"] is False
    assert output["differences"] == [
        {
            "id": "pack",
            "kind": "version_mismatch",
            "primary": "2.0",
            "partner": "1.0",
        }
    ]


def test_employee_planner_rejects_unassigned_capability() -> None:
    output = _module("employee-planner").run(
        {
            "requirements": [{"id": "ship", "capabilities": ["release"], "depends_on": []}],
            "employees": [{"id": "qa", "capabilities": ["qa"], "available": True}],
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["plan"] == []
    assert output["blockers"] == [
        {
            "kind": "capability_unassigned",
            "requirement_id": "ship",
            "capabilities": ["release"],
        }
    ]


def test_enterprise_adoption_aggregates_without_exposing_tenant_rows() -> None:
    output = _module("enterprise-adoption-officer").run(
        {
            "tenants": [
                {
                    "tenant_id": "tenant-a",
                    "activated": True,
                    "active_days_30": 9,
                    "adopted_features": ["goals"],
                    "blocked_reasons": ["training"],
                    "value_milestones": ["delivery"],
                },
                {
                    "tenant_id": "tenant-b",
                    "activated": False,
                    "active_days_30": 0,
                    "adopted_features": [],
                    "blocked_reasons": ["training"],
                    "value_milestones": [],
                },
            ]
        },
        {},
    )
    assert output["status"] == "approved"
    assert output["funnel"] == {
        "observed": 2,
        "activated": 1,
        "active_30d": 1,
        "feature_adopted": 1,
        "value_milestone_reached": 1,
        "activation_rate": 0.5,
        "adoption_rate": 0.5,
        "value_rate": 0.5,
    }
    assert output["blockers"] == [{"reason": "training", "tenant_count": 2}]
    assert "tenants" not in output


def test_qa_runner_never_releases_failed_tests() -> None:
    output = _module("test-qa-runner").run(
        {
            "qa_run": {
                "command": "pytest -q",
                "exit_code": 1,
                "total": 2,
                "passed": 1,
                "failed": 1,
                "artifact_sha256": "a" * 64,
            }
        },
        {},
    )
    assert output["status"] == "rejected"
    assert output["release_allowed"] is False
    assert output["blockers"] == ["tests_failed", "exit_code_nonzero"]
