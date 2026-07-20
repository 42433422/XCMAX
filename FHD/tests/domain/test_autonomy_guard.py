from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.application.autonomy.approval_resume import (
    ApprovalStateError,
    complete_action,
    mark_approval_requested,
    reject_action,
    request_action,
    resume_action,
)
from app.application.autonomy.audit_log import (
    append_autonomy_audit,
    list_autonomy_audit,
    summarize_autonomy_audit,
)
from app.domain.autonomy.autonomy_guard import (
    AutonomyGuard,
    MediumRiskPolicy,
    ProhibitedActionError,
    RiskLevel,
    reload_autonomy_guard,
)
from app.domain.autonomy.risk_policy import RiskPolicyCatalog

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
REGISTRY = FHD_ROOT / "config" / "risk_actions.registry.json"
BOUNDARIES = FHD_ROOT / "config" / "autonomy_boundaries.yaml"

REQUIRED_ACTIVATION_EVIDENCE = {
    "apply_release_to_cvm": (
        FHD_ROOT / "scripts/deploy/fhd-auto-update.sh",
        'evaluate_risk(\n    "apply_release_to_cvm"',
    ),
    "rollback_release": (
        FHD_ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "rollback_release"',
    ),
    "freeze_manifest": (
        FHD_ROOT / "app/fastapi_routes/ops_autonomy.py",
        '"freeze_manifest": "freeze-manifest"',
    ),
    "restart_service": (
        FHD_ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "restart_service"',
    ),
    "self_heal_pr_merge": (
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/approval_dispatcher.py",
        'evaluate_risk(\n        "self_heal_pr_merge"',
    ),
    "mod_auto_publish": (
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/workbench_api.py",
        'evaluate_risk(\n        "mod_auto_publish"',
    ),
    "db_migration": (
        FHD_ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "db_migration"',
    ),
    "delete_user_data": (
        FHD_ROOT / "app/fastapi_routes/ops_autonomy.py",
        "result = evaluate_risk(",
    ),
}


@pytest.fixture(autouse=True)
def isolated_autonomy_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv(
        "XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval-ledger.jsonl")
    )
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    reload_autonomy_guard()
    yield
    reload_autonomy_guard()


def _registry_with_policy(tmp_path: Path, policy: str) -> Path:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    data["medium_risk_policy"] = policy
    path = tmp_path / f"risk-{policy}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_four_risk_levels_have_automatic_allow_and_hard_block_branches() -> None:
    audit: list[dict] = []
    guard = AutonomyGuard(audit_sink=audit.append)

    low = guard.evaluate("restart_service", action_id="low")
    medium = guard.evaluate("rollback_release", action_id="medium")
    high = guard.evaluate("apply_release_to_cvm", action_id="high")

    assert low.risk_level is RiskLevel.LOW and low.allowed
    assert medium.risk_level is RiskLevel.MEDIUM and medium.allowed
    assert medium.requires_confirmation is False
    assert high.risk_level is RiskLevel.HIGH and high.allowed
    assert high.requires_confirmation is False
    with pytest.raises(ProhibitedActionError):
        guard.evaluate("db_migration", action_id="blocked")
    assert {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.BLOCKED} == set(RiskLevel)
    assert any(row.get("decision") == "prohibited" for row in audit)


@pytest.mark.parametrize(
    ("policy", "first_allowed", "first_pending"),
    [
        ("auto_approve", True, False),
        ("require_human", False, True),
        ("cooldown_60min", True, False),
    ],
)
def test_medium_risk_policy_controls_observable_behavior(
    tmp_path: Path,
    policy: str,
    first_allowed: bool,
    first_pending: bool,
) -> None:
    guard = AutonomyGuard(registry_path=_registry_with_policy(tmp_path, policy))
    first = guard.evaluate("rollback_release", action_id=f"{policy}:1")
    assert first.allowed is first_allowed
    assert first.requires_confirmation is first_pending
    assert first.policy == policy
    if policy == "cooldown_60min":
        second = guard.evaluate("rollback_release", action_id=f"{policy}:2")
        assert not second.allowed
        assert second.requires_confirmation
        assert second.decision == "cooldown"


def test_medium_policy_env_override_and_change_are_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry_with_policy(tmp_path, "require_human")
    first = AutonomyGuard(registry_path=registry)
    assert first.medium_risk_policy is MediumRiskPolicy.REQUIRE_HUMAN
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "auto_approve")
    second = AutonomyGuard(registry_path=registry)
    assert second.medium_risk_policy is MediumRiskPolicy.AUTO_APPROVE
    changes = [row for row in list_autonomy_audit(limit=20) if row["action"] == "__configuration__"]
    assert changes[0]["decision"] == "config_changed"
    assert changes[0]["policy"] == "auto_approve"


def test_every_boundary_item_raises_prohibited_action() -> None:
    items = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))["prohibited_actions"]
    guard = AutonomyGuard(audit_sink=lambda row: row)
    assert items
    for item in items:
        with pytest.raises(ProhibitedActionError, match=item["action"]):
            guard.evaluate(
                item["action"],
                {"human_approved": True, "approved_by": "even-a-human-cannot-bypass"},
                action_id=f"boundary:{item['action']}",
            )


def test_default_boundaries_have_no_human_veto_items() -> None:
    items = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))["requires_veto"]
    guard = AutonomyGuard(audit_sink=lambda row: row)
    assert items == []
    assert guard.veto_boundaries_snapshot() == {}


def test_requires_veto_overrides_medium_auto_approve(tmp_path: Path) -> None:
    registry = _registry_with_policy(tmp_path, "auto_approve")
    boundaries = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))
    boundaries["requires_veto"].append(
        {"action": "freeze_manifest", "reason": "test medium veto floor"}
    )
    boundaries_path = tmp_path / "boundaries-with-medium-veto.yaml"
    boundaries_path.write_text(yaml.safe_dump(boundaries), encoding="utf-8")

    decision = AutonomyGuard(
        registry_path=registry,
        boundaries_path=boundaries_path,
        audit_sink=lambda row: row,
    ).evaluate("freeze_manifest", action_id="veto:medium")

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.decision == "require_human"
    assert "requires_veto boundary" in decision.reason


def test_autonomous_registry_is_exhaustive_and_has_rollback_paths() -> None:
    raw_text = REGISTRY.read_text(encoding="utf-8")
    duplicate_keys: list[str] = []

    def _reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                duplicate_keys.append(str(key))
            result[key] = value
        return result

    data = json.loads(raw_text, object_pairs_hook=_reject_duplicates)
    assert duplicate_keys == []
    actions = data["autonomous_actions"]
    required = {
        "apply_release_to_cvm",
        "rollback_release",
        "freeze_manifest",
        "restart_service",
        "self_heal_pr_merge",
        "mod_auto_publish",
        "db_migration",
        "delete_user_data",
    }
    assert required <= set(actions)
    for name, spec in actions.items():
        assert spec["rollback_path"], name
        assert spec["risk"] in {"LOW", "MEDIUM", "HIGH", "BLOCKED"}
        if spec["risk"] == "BLOCKED":
            assert spec["allow_auto_execute"] is False


@pytest.mark.parametrize(
    ("action", "expected_risk", "expected_decision"),
    [
        ("apply_release_to_cvm", RiskLevel.HIGH, "auto_approve"),
        ("rollback_release", RiskLevel.MEDIUM, "auto_approve"),
        ("freeze_manifest", RiskLevel.MEDIUM, "auto_approve"),
        ("restart_service", RiskLevel.LOW, "allow"),
        ("self_heal_pr_merge", RiskLevel.HIGH, "auto_approve"),
        ("mod_auto_publish", RiskLevel.HIGH, "auto_approve"),
    ],
)
def test_required_automatic_actions_are_evaluated_by_ssot(
    action: str,
    expected_risk: RiskLevel,
    expected_decision: str,
) -> None:
    decision = AutonomyGuard().evaluate(action, action_id=f"activation:{action}")

    assert decision.risk_level is expected_risk
    assert decision.decision == expected_decision


def test_registered_auto_action_does_not_forge_human_approval() -> None:
    decision = AutonomyGuard().evaluate(
        "employee_execute",
        {"allow_medium_risk": True},
        action_id="activation:employee_execute:legacy-context",
    )

    assert decision.allowed is True
    assert decision.decision == "auto_approve"
    assert decision.approver == ""
    assert decision.requires_confirmation is False


@pytest.mark.parametrize("action", ["db_migration", "delete_user_data"])
def test_required_blocked_actions_reach_ssot_and_can_never_execute(action: str) -> None:
    with pytest.raises(ProhibitedActionError, match=action):
        AutonomyGuard().evaluate(
            action,
            {"human_approved": True, "approved_by": "activation-contract"},
            action_id=f"activation:{action}",
        )


def test_required_autonomous_actions_have_executable_activation_evidence() -> None:
    """Prevent a registry-only action from masquerading as an active risk gate."""
    actions = json.loads(REGISTRY.read_text(encoding="utf-8"))["autonomous_actions"]
    assert set(REQUIRED_ACTIVATION_EVIDENCE) <= set(actions)

    for action, (path, marker) in REQUIRED_ACTIVATION_EVIDENCE.items():
        assert path.is_file(), f"{action}: missing activation entrypoint {path}"
        assert marker in path.read_text(encoding="utf-8"), (
            f"{action}: registry entry exists but no SSOT activation marker in {path}"
        )

    bridge = (FHD_ROOT / "scripts/deploy/lib/autonomy_gate.sh").read_text(encoding="utf-8")
    assert "from app.domain.autonomy.autonomy_guard import evaluate_risk" in bridge
    delegate = (
        REPO_ROOT
        / "成都修茈科技有限公司/MODstore_deploy/modstore_server/autonomy_guard_delegate.py"
    ).read_text(encoding="utf-8")
    assert "from app.domain.autonomy.autonomy_guard import evaluate_risk" in delegate


def test_policy_catalog_rejects_malformed_startup_configuration(tmp_path: Path) -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    boundaries = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))

    with pytest.raises(FileNotFoundError, match="risk registry not found"):
        RiskPolicyCatalog(
            registry_path=tmp_path / "missing-registry.json",
            boundaries_path=BOUNDARIES,
        )

    invalid_registries: list[object] = [
        [],
        {key: value for key, value in registry.items() if key != "autonomous_actions"},
    ]
    missing_action = json.loads(json.dumps(registry))
    missing_action["autonomous_actions"].pop("restart_service")
    invalid_registries.append(missing_action)
    missing_class = json.loads(json.dumps(registry))
    missing_class["action_classes"].pop("business_db.write")
    invalid_registries.append(missing_class)
    no_tools = json.loads(json.dumps(registry))
    no_tools["tools"] = {}
    invalid_registries.append(no_tools)
    malformed_action = json.loads(json.dumps(registry))
    malformed_action["autonomous_actions"]["restart_service"] = "LOW"
    invalid_registries.append(malformed_action)
    missing_rollback = json.loads(json.dumps(registry))
    missing_rollback["autonomous_actions"]["restart_service"]["rollback_path"] = ""
    invalid_registries.append(missing_rollback)
    auto_blocked = json.loads(json.dumps(registry))
    auto_blocked["autonomous_actions"]["db_migration"]["allow_auto_execute"] = True
    invalid_registries.append(auto_blocked)

    for index, invalid in enumerate(invalid_registries):
        registry_path = tmp_path / f"invalid-registry-{index}.json"
        registry_path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError):
            RiskPolicyCatalog(registry_path=registry_path, boundaries_path=BOUNDARIES)

    valid_registry_path = tmp_path / "valid-registry.json"
    valid_registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="autonomy boundaries not found"):
        RiskPolicyCatalog(
            registry_path=valid_registry_path,
            boundaries_path=tmp_path / "missing-boundaries.yaml",
        )

    invalid_boundaries: list[object] = [
        [],
        {},
        {"prohibited_actions": []},
        {"prohibited_actions": ["db_migration"]},
        {"prohibited_actions": [{"action": "db_migration"}]},
    ]
    malformed_veto = copy.deepcopy(boundaries)
    malformed_veto["requires_veto"] = ["apply_release_to_cvm"]
    invalid_boundaries.append(malformed_veto)
    overlapping = copy.deepcopy(boundaries)
    overlapping["requires_veto"].append({"action": "db_migration", "reason": "invalid overlap"})
    invalid_boundaries.append(overlapping)
    unregistered = copy.deepcopy(boundaries)
    unregistered["requires_veto"].append(
        {"action": "not_registered", "reason": "invalid unknown action"}
    )
    invalid_boundaries.append(unregistered)
    for index, invalid in enumerate(invalid_boundaries):
        boundaries_path = tmp_path / f"invalid-boundaries-{index}.yaml"
        boundaries_path.write_text(yaml.safe_dump(invalid), encoding="utf-8")
        with pytest.raises(ValueError):
            RiskPolicyCatalog(
                registry_path=valid_registry_path,
                boundaries_path=boundaries_path,
            )

    assert boundaries["prohibited_actions"]
    assert boundaries["requires_veto"] == []


def test_policy_catalog_helpers_cover_aliases_tools_and_employee_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "not-a-policy")
    catalog = RiskPolicyCatalog()
    assert catalog.medium_risk_policy is MediumRiskPolicy.REQUIRE_HUMAN
    assert catalog.canonical_action("rollback_version") == "rollback_release"
    assert catalog.canonical_action("custom_action") == "custom_action"

    registry_snapshot = catalog.registry_snapshot()
    registry_snapshot["medium_risk_policy"] = "mutated"
    assert catalog.registry["medium_risk_policy"] == "auto_approve"
    boundaries_snapshot = catalog.boundaries_snapshot()
    boundaries_snapshot.clear()
    assert catalog.boundaries
    veto_snapshot = catalog.veto_boundaries_snapshot()
    veto_snapshot.clear()
    assert catalog.veto_boundaries == {}
    assert catalog.veto_reason("apply_release_to_cvm") is None
    assert catalog.veto_reason("restart_service") is None
    assert "restart_service" in catalog.autonomous_action_names()
    assert catalog.autonomous_action_spec("missing") is None
    assert catalog.list_code_write_tools() == frozenset({"patch_file", "write_file"})

    customer_create = catalog.get_action_spec("customers", "create")
    assert customer_create and customer_create["requires_write_approval"] is True
    assert catalog.get_action_spec("missing", "create") is None
    catalog.registry["tools"]["broken"] = {"actions": {"execute": "invalid"}}
    catalog.registry["tools"]["not-an-object"] = "invalid"
    assert catalog.get_action_spec("broken", "execute") is None
    assert catalog.requires_write_approval("patch_file") is True
    assert catalog.requires_write_approval("customers", "query") is False
    assert catalog.requires_write_approval_for_spec({"requires_write_approval": True}) is True
    assert catalog.requires_write_approval_for_spec({"action_class": "business_db.write"}) is True
    assert catalog.requires_write_approval_for_spec({"action_class": "im.send"}) is False
    write_tools = catalog.list_write_tools()
    assert {"customers", "products", "patch_file", "write_file"} <= write_tools

    declared, declared_reason = catalog.assess_employee_risk(
        {"employee_config_v2": {"risk_level": "high"}}, ["agent"]
    )
    inferred_high, _ = catalog.assess_employee_risk({}, ["shell_exec"])
    inferred_medium, _ = catalog.assess_employee_risk({}, ["agent"])
    inferred_low, _ = catalog.assess_employee_risk({}, [])
    code_write, code_reason = catalog.assess_employee_risk(
        {"employee_config_v2": "invalid"}, [], {"tool": "write_file"}
    )
    assert declared is RiskLevel.HIGH and "manifest declared" in declared_reason
    assert inferred_high is RiskLevel.HIGH
    assert inferred_medium is RiskLevel.MEDIUM
    assert inferred_low is RiskLevel.LOW
    assert code_write is RiskLevel.HIGH and "forces high risk" in code_reason

    assert catalog.resolve_spec("restart_service", "", "")
    assert catalog.resolve_spec("custom", "customers", "create")
    assert catalog.resolve_spec("customers.create", "", "")
    assert catalog.resolve_spec("custom", "", "") is None
    assert catalog.rollback_path("restart_service") != "not_applicable"
    assert catalog.rollback_path("custom") == "not_applicable"


def test_append_only_table_rejects_update_and_delete(tmp_path: Path) -> None:
    row = append_autonomy_audit(
        {
            "action_id": "immutable",
            "action": "restart_service",
            "risk_level": "LOW",
            "decision": "allow",
            "outcome": "allowed",
        }
    )
    db_path = tmp_path / "audit.sqlite3"
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE autonomy_audit_log SET outcome='changed' WHERE id=?", (row["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM autonomy_audit_log WHERE id=?", (row["id"],))


def test_audit_summary_detects_any_blocked_action_execution_evidence() -> None:
    clean = summarize_autonomy_audit(days=1)
    assert clean["prohibited_miss_count"] == 0
    assert clean["has_prohibited_miss"] is False

    append_autonomy_audit(
        {
            "action_id": "blocked-bypass",
            "action": "db_migration",
            "risk_level": "BLOCKED",
            "decision": "executed",
            "outcome": "executed",
        }
    )
    leaked = summarize_autonomy_audit(days=1)
    assert leaked["prohibited_miss_count"] == 1
    assert leaked["has_prohibited_miss"] is True


def test_audit_summary_separates_synthetic_probes_and_counts_human_veto() -> None:
    append_autonomy_audit(
        {
            "action_id": "e2e-medium-probe",
            "action": "freeze_manifest",
            "risk_level": "MEDIUM",
            "decision": "require_human",
            "outcome": "not_executed",
            "source": "ops_autonomy.request",
        }
    )
    append_autonomy_audit(
        {
            "action_id": "operational-low",
            "action": "restart_service",
            "risk_level": "LOW",
            "decision": "allow",
            "outcome": "allowed",
            "source": "self_heal",
        }
    )
    append_autonomy_audit(
        {
            "action_id": "operational-high",
            "action": "apply_release_to_cvm",
            "risk_level": "HIGH",
            "decision": "approved",
            "approver": "operator",
            "outcome": "allowed",
            "source": "release",
        }
    )

    summary = summarize_autonomy_audit(days=1)

    assert summary["cohort"] == "operational"
    assert summary["total"] == 2
    assert summary["veto_count"] == 1
    assert summary["human_approval_count"] == 1
    assert summary["synthetic_probe_count"] == 1
    assert summary["veto_rate"] == 50.0


def test_pending_approval_resumes_and_rejection_never_retries(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    executed: list[dict] = []
    decision, pending = request_action(
        "rollback_release",
        action_id="resume-me",
        payload={"release": "v1"},
        source="test",
        executor=lambda payload: executed.append(payload) or {"ok": True},
    )
    assert decision.requires_confirmation and pending["state"] == "pending_approval"
    resumed = resume_action("resume-me", approver="octocat", approval_id="deployment-1")
    assert resumed["state"] == "executed"
    assert executed and executed[0]["release"] == "v1"
    assert executed[0]["_approval"]["approver"] == "octocat"

    _, rejected_pending = request_action(
        "rollback_release",
        action_id="reject-me",
        payload={},
        source="test",
        executor=lambda payload: {"ok": True},
    )
    assert rejected_pending["state"] == "pending_approval"
    rejected = reject_action("reject-me", approver="octocat", reason="unsafe")
    assert rejected["state"] == "rejected"
    _, duplicate = request_action(
        "rollback_release",
        action_id="reject-me",
        payload={},
        source="scheduler-retry",
        executor=lambda payload: pytest.fail("terminal action was re-registered"),
    )
    assert duplicate and duplicate["state"] == "rejected"
    with pytest.raises(ApprovalStateError, match="rejected"):
        resume_action("reject-me", approver="octocat")

    summary = summarize_autonomy_audit(days=1, include_synthetic=True)
    assert summary["total"] > 0
    assert summary["veto_count"] > 0


def test_deferred_workflow_only_marks_executed_after_real_outcome(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    decision, pending = request_action(
        "freeze_manifest",
        action_id="deferred-freeze",
        payload={"workflow_action": "freeze-manifest"},
        source="test",
        executor_name="github_deploy",
    )
    assert decision.requires_confirmation
    assert pending and pending["state"] == "pending_approval"
    requested = mark_approval_requested("deferred-freeze", approval_id="dispatcher-1")
    assert requested["state"] == "approval_requested"
    approved = resume_action(
        "deferred-freeze",
        approver="reviewer",
        approval_id="deployment-1",
        defer_execution=True,
    )
    assert approved["state"] == "approved"
    completed = complete_action(
        "deferred-freeze",
        success=True,
        approver="reviewer",
        approval_id="deployment-1",
        outcome={"marker": "created"},
    )
    assert completed["state"] == "executed"
    with pytest.raises(ApprovalStateError, match="already terminal"):
        complete_action("deferred-freeze", success=True, approver="reviewer")


def test_other_risk_modules_are_delegating_facades() -> None:
    paths = [
        FHD_ROOT / "app/application/employee_runtime/risk_gate.py",
        FHD_ROOT / "app/application/workflow/risk_gate.py",
        FHD_ROOT / "resources/config/risk_actions_loader.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "autonomy_guard" in text
        assert "_HIGH_RISK_HANDLERS" not in text
        assert "medium_self_approve" not in text


def test_autonomy_metrics_cli_works_when_executed_by_file_path() -> None:
    metrics = subprocess.run(
        [
            sys.executable,
            str(FHD_ROOT / "scripts/autonomy/autonomy_metrics.py"),
            "--days",
            "30",
        ],
        cwd=FHD_ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(metrics.stdout)
    assert report["status"] == "collecting"
    assert report["complete"] is False
