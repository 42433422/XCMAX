from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from modstore_server.duty_burn_in_handlers import bind_reviewed_burn_in_handlers
from modstore_server.employee_executor import (
    _action_direct_python,
    _deterministic_direct_input_ready,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EMPLOYEE_ROOT = REPO_ROOT / "FHD" / "mods" / "_employees"
ADDITIONAL_DIRECT_WORKERS = {
    "artifact-generator": "artifact_generator",
    "dbops-engineer": "dbops_engineer",
    "github-pr-gatekeeper": "github_pr_gatekeeper",
    "hex-quality-assessor": "hex_quality_assessor",
    "host-checker": "host_checker",
    "intake-dispatcher": "intake_dispatcher",
    "intent-analyst": "intent_analyst",
    "java-payment-bridge-officer": "java_payment_bridge_officer",
    "legacy-archive-curator": "legacy_archive_curator",
    "llm-ops-engineer": "llm_ops_engineer",
    "log-monitor-incident": "log_monitor_incident",
    "market-frontend-dev": "market_frontend_dev",
    "marketing-site-builder": "marketing_site_builder",
    "miniapp-builder": "miniapp_builder",
    "mobile-android-release-officer": "mobile_android_release_officer",
    "mobile-ios-release-officer": "mobile_ios_release_officer",
    "mods-and-eskill-curator": "mods_and_eskill_curator",
    "modstore-backend-api": "modstore_backend_api",
    "nginx-config-engineer": "nginx_config_engineer",
    "pack-registrar": "pack_registrar",
    "payment-billing-reconciler": "payment_billing_reconciler",
    "push-update-context-officer": "push_update_context_officer",
    "security-secrets-guard": "security_secrets_guard",
    "site-content-editor": "site_content_editor",
    "user-customer-service-officer": "user_customer_service_officer",
}
DIRECT_WORKER_VERSIONS = {employee_id: "1.1.0" for employee_id in ADDITIONAL_DIRECT_WORKERS}
DIRECT_WORKER_VERSIONS["log-monitor-incident"] = "1.3.0"
DIRECT_WORKER_VERSIONS["llm-ops-engineer"] = "1.6.0"


def _load_worker(employee_id: str, module_name: str):
    path = EMPLOYEE_ROOT / employee_id / "backend" / "employees" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(employee_id: str) -> dict:
    return json.loads((EMPLOYEE_ROOT / employee_id / "manifest.json").read_text(encoding="utf-8"))


def test_interview_contract_produces_structured_read_only_gap_report() -> None:
    worker = _load_worker("employee-interview-assistant", "employee_interview_assistant")
    result = worker.run(
        {
            "action": "draft_interview",
            "target_employee_id": "new-role",
            "role_context": {
                "mission": "核对员工包契约",
                "capabilities": ["manifest-audit"],
                "dependencies": ["employee-pack-curator"],
                "risk_level": "low",
                "handlers": ["direct_python"],
            },
        },
        {"workspace_root": "/tmp/workspace"},
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["coverage_pct"] == 100.0
    assert result["missing_fields"] == []
    assert result["read_only"] is True
    assert result["side_effects"] == []


def test_interview_contract_blocks_sensitive_fields() -> None:
    worker = _load_worker("employee-interview-assistant", "employee_interview_assistant")
    result = worker.run(
        {
            "target_employee_id": "unsafe-role",
            "role_context": {"mission": "test"},
            "api_key": "must-not-be-accepted",
        },
        {},
    )
    assert result["ok"] is False
    assert result["error_code"] == "sensitive_input_blocked"
    assert "must-not-be-accepted" not in json.dumps(result, ensure_ascii=False)


def test_curator_contract_audits_manifest_and_registry_without_mutation() -> None:
    worker = _load_worker("employee-pack-curator", "employee_pack_curator")
    manifest = {
        "id": "sample-employee",
        "name": "Sample",
        "version": "1.2.3",
        "artifact": "employee_pack",
        "employee": {"id": "sample-employee", "label": "Sample"},
        "employee_config_v2": {
            "cognition": {
                "agent": {
                    "system_prompt": (
                        "Review only the supplied manifest and report deterministic evidence; "
                        "never mutate files, publish packages, or invent runtime results."
                    )
                }
            },
            "actions": {"handlers": ["agent"]},
        },
    }
    result = worker.run(
        {
            "action": "audit_manifest",
            "manifest": manifest,
            "registry_record": {"id": "sample-employee", "version": "1.2.3"},
        },
        {},
    )

    assert result["ok"] is True
    assert result["status"] == "approved"
    assert result["issues"] == []
    assert result["registry_consistent"] is True
    assert result["ready_for_packaging"] is True
    assert result["side_effects"] == []


def test_curator_contract_rejects_identity_and_registry_drift() -> None:
    worker = _load_worker("employee-pack-curator", "employee_pack_curator")
    result = worker.run(
        {
            "manifest": {
                "id": "sample",
                "version": "not-semver",
                "artifact": "mod",
                "employee": {"id": "other"},
                "employee_config_v2": {"actions": {"handlers": ["unknown"]}},
            },
            "registry_record": {"id": "drift", "version": "1.0.0"},
        },
        {},
    )
    codes = {issue["code"] for issue in result["issues"]}
    assert result["status"] == "rejected"
    assert {
        "invalid_semver",
        "invalid_artifact",
        "employee_id_mismatch",
        "unsupported_handlers",
        "registry_mismatch",
    }.issubset(codes)


def test_daily_orchestrator_prioritizes_without_dispatch() -> None:
    worker = _load_worker("daily-orchestrator", "daily_orchestrator")
    result = worker.run(
        {
            "work_items": [
                {"id": "later", "priority": "p2", "blocked_by": ["first"]},
                {"id": "first", "priority": "p0", "blocked_by": []},
            ]
        },
        {},
    )
    assert result["status"] == "approved"
    assert [item["id"] for item in result["queue"]] == ["first", "later"]
    assert result["read_only"] is True
    assert result["side_effects"] == []


def test_partner_onboarding_audits_isolation_and_permissions() -> None:
    worker = _load_worker(
        "ecosystem-partner-onboard-officer",
        "ecosystem_partner_onboard_officer",
    )
    result = worker.run(
        {
            "partner_profile": {
                "partner_id": "partner-1",
                "partner_name": "Partner One",
                "tenant_id": "tenant-1",
                "tenant_isolated": True,
                "sso_mode": "oidc",
                "permissions": ["catalog.read"],
                "first_goal": "核对 catalog",
            }
        },
        {},
    )
    assert result["status"] == "approved"
    assert result["ready_for_onboarding"] is True
    blocked = worker.run(
        {
            "partner_profile": {
                "partner_id": "partner-2",
                "tenant_id": "tenant-2",
                "permissions": ["admin"],
            }
        },
        {},
    )
    codes = {item["code"] for item in blocked["issues"]}
    assert {"tenant_isolation_unproven", "overbroad_permission"}.issubset(codes)


def test_script_binder_validates_declared_skill_and_safe_path() -> None:
    worker = _load_worker("script-binder", "script_binder")
    result = worker.run(
        {
            "manifest": {
                "id": "pack-1",
                "employee": {"capabilities": [{"label": "skill-a"}]},
            },
            "workflow": {
                "employee_pack_id": "pack-1",
                "skills": [{"id": "skill-a", "script_path": "scripts/a.py"}],
            },
        },
        {},
    )
    assert result["status"] == "approved"
    assert result["ready_for_binding"] is True
    unsafe = worker.run(
        {
            "manifest": {
                "id": "pack-1",
                "employee": {"capabilities": [{"label": "skill-a"}]},
            },
            "workflow": {
                "employee_pack_id": "pack-1",
                "skills": [{"id": "skill-a", "script_path": "../escape.py"}],
            },
        },
        {},
    )
    assert "unsafe_script_path" in {item["code"] for item in unsafe["issues"]}


def test_workflow_automator_validates_dag_without_creating_canvas() -> None:
    worker = _load_worker("workflow-automator", "workflow_automator")
    valid = worker.run(
        {
            "workflow": {
                "id": "flow-1",
                "nodes": [
                    {"id": "a", "skill_id": "inspect"},
                    {"id": "b", "skill_id": "verify"},
                ],
                "edges": [{"from": "a", "to": "b"}],
            }
        },
        {},
    )
    assert valid["status"] == "approved"
    assert valid["topological_order"] == ["a", "b"]
    cyclic = worker.run(
        {
            "workflow": {
                "id": "flow-2",
                "nodes": [
                    {"id": "a", "skill_id": "inspect"},
                    {"id": "b", "skill_id": "verify"},
                ],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
            }
        },
        {},
    )
    assert "cycle_detected" in {item["code"] for item in cyclic["issues"]}


def test_additional_direct_workers_accept_their_reviewed_read_only_fixtures() -> None:
    for employee_id, module_name in ADDITIONAL_DIRECT_WORKERS.items():
        manifest = _manifest(employee_id)
        direct = manifest["employee_config_v2"]["actions"]["direct_python"]
        worker = _load_worker(employee_id, module_name)
        result = worker.run(direct["burn_in_fixture"], {})
        assert result["ok"] is True, employee_id
        assert result["status"] == "approved", (employee_id, result)
        assert result["evidence"], employee_id
        assert result["read_only"] is True, employee_id
        assert result["side_effects"] == [], employee_id


def test_llm_ops_direct_contract_blocks_secret_values_without_echoing_them() -> None:
    worker = _load_worker("llm-ops-engineer", "llm_ops_engineer")
    secret = "sk-live-must-never-be-returned"
    result = worker.run(
        {
            "llm_ops_snapshot": {
                "providers": [{"provider": "unsafe", "api_key": secret}],
                "secrets_redacted": False,
            }
        },
        {},
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["issues"] == [
        {
            "code": "sensitive_value_blocked",
            "detail": "snapshot contains a credential-like key or value",
        }
    ]
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_llm_ops_burn_in_binding_does_not_replace_normal_handlers() -> None:
    manifest = _manifest("llm-ops-engineer")
    config = manifest["employee_config_v2"]
    actions = config["actions"]
    normal_handlers = ["agent", "specialized", "llm_md", "echo"]

    bound = bind_reviewed_burn_in_handlers(
        config,
        {
            "eligible": True,
            "burn_in_handlers_explicit": True,
            "capability_handlers": ["direct_python"],
        },
    )

    assert actions["handlers"] == normal_handlers
    assert actions["burn_in_handlers"] == ["direct_python"]
    assert bound["actions"]["handlers"] == ["direct_python"]
    assert bound["actions"]["direct_python"] == actions["direct_python"]


def test_read_only_burn_in_executes_reviewed_sources_not_stale_catalog(
    monkeypatch,
) -> None:
    def stale_catalog_must_not_run(*_args, **_kwargs):
        raise AssertionError("read-only burn-in must not execute a stale catalog ZIP")

    monkeypatch.setattr(
        "modstore_server.employee_executor.load_employee_pack_resolved",
        stale_catalog_must_not_run,
    )
    monkeypatch.setattr(
        "modstore_server.employee_executor._employee_pack_extract_root",
        stale_catalog_must_not_run,
    )
    for employee_id in (
        "host-checker",
        "intent-analyst",
        "market-frontend-dev",
        "marketing-site-builder",
        "security-secrets-guard",
    ):
        manifest = _manifest(employee_id)
        direct = manifest["employee_config_v2"]["actions"]["direct_python"]
        result = _action_direct_python(
            {"direct_python": direct},
            {
                "input": {
                    **direct["burn_in_fixture"],
                    "burn_in": True,
                    "burn_in_read_only": True,
                }
            },
            "fixture-only reviewed duty audit",
            employee_id,
        )

        assert result["ok"] is True, (employee_id, result)
        assert result["output"]["status"] == "approved", (employee_id, result)
        assert result["output"]["read_only"] is True, employee_id
        assert result["output"]["side_effects"] == [], employee_id


def test_security_guard_rejects_sensitive_fields_inside_declared_summary() -> None:
    worker = _load_worker("security-secrets-guard", "security_secrets_guard")
    result = worker.run(
        {
            "finding_summary": {
                "redacted": False,
                "secret_value": "must-never-be-returned",
            },
            "platform_envelope": {"credential_status": "managed-by-platform"},
        },
        {},
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "must-never-be-returned" not in json.dumps(result, ensure_ascii=False)


def test_manifests_declare_complete_deterministic_direct_contracts() -> None:
    for employee_id in (
        "daily-orchestrator",
        "ecosystem-partner-onboard-officer",
        "employee-interview-assistant",
        "employee-pack-curator",
        "script-binder",
        "workflow-automator",
        *ADDITIONAL_DIRECT_WORKERS,
    ):
        manifest = _manifest(employee_id)
        actions = manifest["employee_config_v2"]["actions"]
        direct = actions["direct_python"]
        assert manifest["version"] == DIRECT_WORKER_VERSIONS.get(employee_id, "1.1.0")
        if employee_id == "llm-ops-engineer":
            assert actions["handlers"] == ["agent", "specialized", "llm_md", "echo"]
            assert actions["burn_in_handlers"] == ["direct_python"]
        else:
            assert actions["handlers"] == ["direct_python"]
        assert direct["implementation"] == "employee_module"
        assert direct["execution_mode"] == "deterministic"
        assert direct["read_only"] is True
        assert direct["input_schema"]["required"]
        assert direct["output_schema"]["required"]
        assert direct["burn_in_fixture"]
        assert _deterministic_direct_input_ready(
            actions,
            direct["burn_in_fixture"],
        )
