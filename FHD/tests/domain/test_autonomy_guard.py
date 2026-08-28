# mypy: disable-error-code="func-returns-value, index, operator"
from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.application.autonomy.approval_center import (
    approval_center_snapshot,
    list_pending_actions,
)
from app.application.autonomy.approval_resume import (
    ApprovalStateError,
    complete_action,
    get_action_state,
    mark_approval_requested,
    reject_action,
    request_action,
    resume_action,
)
from app.application.autonomy.audit_log import (
    append_autonomy_audit,
    autonomy_daily_digest_html,
    list_autonomy_audit,
    summarize_autonomy_audit,
)
from app.domain.autonomy.autonomy_guard import (
    AutonomyGuard,
    MediumRiskPolicy,
    ProhibitedActionError,
    RiskLevel,
    get_autonomy_guard,
    reload_autonomy_guard,
)
from app.domain.autonomy.operating_metrics import (
    autonomy_boundary_review_status,
    evaluate_autonomy_window,
    record_autonomy_metrics_snapshots,
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
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/"
        "workbench_api_part04_part01_part02.py",
        '"mod_auto_publish",',
    ),
    "db_migration": (
        FHD_ROOT / "scripts/deploy/fhd-apply-release.sh",
        'autonomy_evaluate_action "db_migration"',
    ),
    "delete_user_data": (
        FHD_ROOT / "app/fastapi_routes/ops_autonomy.py",
        "result = evaluate_risk(",
    ),
    "autonomy_metrics_snapshot": (
        REPO_ROOT / "成都修茈科技有限公司/MODstore_deploy/modstore_server/autonomy_metrics_job.py",
        '"autonomy_metrics_snapshot",',
    ),
}


@pytest.fixture(autouse=True)
def isolated_autonomy_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
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


def test_four_risk_levels_enforce_human_approval_and_hard_block_branches() -> None:
    audit: list[dict] = []
    guard = AutonomyGuard(audit_sink=audit.append)

    low = guard.evaluate("restart_service", action_id="low")
    medium = guard.evaluate("rollback_release", action_id="medium")
    high = guard.evaluate("apply_release_to_cvm", action_id="high")

    assert low.risk_level is RiskLevel.LOW and low.allowed
    assert medium.risk_level is RiskLevel.MEDIUM and medium.allowed
    assert medium.requires_confirmation is False
    assert high.risk_level is RiskLevel.HIGH and not high.allowed
    assert high.requires_confirmation is True
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


def test_requires_veto_accepts_attributed_human_evidence(tmp_path: Path) -> None:
    boundaries = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))
    boundaries["requires_veto"].append(
        {"action": "freeze_manifest", "reason": "coverage veto boundary"}
    )
    boundaries_path = tmp_path / "boundaries-with-approved-veto.yaml"
    boundaries_path.write_text(yaml.safe_dump(boundaries), encoding="utf-8")

    decision = AutonomyGuard(
        boundaries_path=boundaries_path,
        audit_sink=lambda row: row,
    ).evaluate(
        "freeze_manifest",
        {"human_approved": True, "approved_by": "operator"},
        action_id="veto:approved",
    )

    assert decision.allowed is True
    assert decision.decision == "approved"
    assert decision.approver == "operator"


def test_unregistered_action_fails_closed_without_explicit_risk() -> None:
    decision = AutonomyGuard(audit_sink=lambda row: row).evaluate(
        "not_registered",
        action_id="unregistered:blocked",
    )

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert decision.requires_confirmation is False


def test_registered_blocked_action_stays_blocked_without_boundary_alias(tmp_path: Path) -> None:
    boundaries = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))
    boundaries["prohibited_actions"] = [
        item for item in boundaries["prohibited_actions"] if item["action"] != "db_migration"
    ]
    boundaries_path = tmp_path / "boundaries-without-db-alias.yaml"
    boundaries_path.write_text(yaml.safe_dump(boundaries), encoding="utf-8")

    decision = AutonomyGuard(
        boundaries_path=boundaries_path,
        audit_sink=lambda row: row,
    ).evaluate("db_migration", action_id="blocked:registry")

    assert decision.risk_level is RiskLevel.BLOCKED
    assert decision.allowed is False
    assert decision.decision == "blocked"


def test_action_normalization_covers_tool_and_object_inputs() -> None:
    guard = AutonomyGuard(audit_sink=lambda row: row)
    tool_decision = guard.evaluate(
        {"tool_id": "customers", "operation": "query"},
        action_id="tool:customers.query",
    )
    object_decision = guard.evaluate(
        SimpleNamespace(
            type="restart_service",
            risk="LOW",
            idempotency_key="object:restart",
            params={"probe": True},
        )
    )

    assert tool_decision.allowed is True
    assert tool_decision.risk_level is RiskLevel.LOW
    assert object_decision.allowed is True
    assert object_decision.action_id == "object:restart"


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
        ("apply_release_to_cvm", RiskLevel.HIGH, "require_human"),
        ("rollback_release", RiskLevel.MEDIUM, "auto_approve"),
        ("freeze_manifest", RiskLevel.MEDIUM, "auto_approve"),
        ("restart_service", RiskLevel.LOW, "allow"),
        ("self_heal_pr_merge", RiskLevel.HIGH, "require_human"),
        ("mod_auto_publish", RiskLevel.HIGH, "require_human"),
        ("code_write", RiskLevel.HIGH, "require_human"),
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


def test_registered_action_risk_can_only_escalate() -> None:
    decision = AutonomyGuard().evaluate(
        {"action": "employee_execute", "risk_level": "HIGH"},
        action_id="activation:employee_execute:high",
    )

    assert decision.risk_level is RiskLevel.HIGH
    assert decision.allowed is True
    assert decision.decision == "auto_approve"


def test_global_guard_refreshes_when_env_policy_changes(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    pending = get_autonomy_guard().evaluate("rollback_release", action_id="env-refresh:pending")
    assert pending.requires_confirmation is True

    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "auto_approve")
    automatic = get_autonomy_guard().evaluate("rollback_release", action_id="env-refresh:auto")
    assert automatic.allowed is True
    assert automatic.decision == "auto_approve"
    assert automatic.requires_confirmation is False


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


def test_operating_window_requires_quarterly_boundary_review(tmp_path: Path, monkeypatch) -> None:
    boundaries = tmp_path / "boundaries.yaml"
    boundary_data = yaml.safe_load(BOUNDARIES.read_text(encoding="utf-8"))
    boundary_data.update(
        {
            "boundary_revision": 4,
            "last_reviewed_at": "2026-01-01",
            "review_cadence_days": 90,
        }
    )
    boundaries.write_text(yaml.safe_dump(boundary_data), encoding="utf-8")
    monkeypatch.setenv("XCAGI_AUTONOMY_BOUNDARIES_PATH", str(boundaries))
    summary = {
        "observed_days": 90.0,
        "veto_rate": 3.0,
        "total": 100,
        "has_prohibited_miss": False,
    }

    due = evaluate_autonomy_window(
        90,
        summary=summary,
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert due["status"] == "needs_review"
    assert due["recommendation"] == "review_boundaries"

    high_veto = evaluate_autonomy_window(
        90,
        summary={**summary, "veto_rate": 11.0},
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert high_veto["status"] == "needs_tuning"
    assert high_veto["recommendation"] == "review_medium_risk_boundaries"

    boundary_data.update(
        {
            "boundary_revision": 5,
            "last_reviewed_at": "2026-07-20",
        }
    )
    boundaries.write_text(yaml.safe_dump(boundary_data), encoding="utf-8")
    current = evaluate_autonomy_window(
        90,
        summary=summary,
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert current["status"] == "passed"
    assert current["boundary_review"]["boundary_revision"] == 5


def test_daily_metrics_snapshots_are_append_only_and_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(metrics_path))
    append_autonomy_audit(
        {
            "action_id": "daily-operational-action",
            "action": "restart_service",
            "risk_level": "LOW",
            "decision": "allow",
            "outcome": "allowed",
            "source": "scheduler",
        }
    )
    now = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)

    first = record_autonomy_metrics_snapshots(now=now)
    second = record_autonomy_metrics_snapshots(now=now)

    assert [item["window_days"] for item in first] == [30, 90]
    assert all(item["recorded"] for item in first)
    assert all(not item["recorded"] for item in second)
    rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"collecting"}
    assert {row["snapshot_date"] for row in rows} == {"2026-07-20"}


def test_daily_digest_renders_operating_windows() -> None:
    append_autonomy_audit(
        {
            "action_id": "digest-operational-action",
            "action": "restart_service",
            "risk_level": "LOW",
            "decision": "allow",
            "outcome": "allowed",
            "source": "daily_digest",
        }
    )

    html = autonomy_daily_digest_html()

    assert "30天 · collecting" in html
    assert "90天 · collecting" in html
    boundary = autonomy_boundary_review_status()
    assert f"revision {boundary['boundary_revision']}" in html


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
    assert complete_action("deferred-freeze", success=True, approver="reviewer") == completed
    with pytest.raises(ApprovalStateError, match="already terminal"):
        complete_action("deferred-freeze", success=False, approver="reviewer")


def test_executed_release_reconciles_obsolete_approval_backlog(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    request_action(
        "apply_release_to_cvm",
        action_id="release:" + "1" * 40,
        executor_name="github_deploy",
    )
    request_action(
        "apply_release_to_cvm",
        action_id="release:" + "2" * 40,
        executor_name="github_deploy",
    )
    approved_id = "release:" + "2" * 40
    resume_action(
        approved_id,
        approver="reviewer",
        approval_id="run-old",
        defer_execution=True,
    )
    # A scheduler retry must not resurrect an approved deferred action.
    _, duplicate = request_action(
        "apply_release_to_cvm",
        action_id=approved_id,
        executor_name="github_deploy",
    )
    assert duplicate and duplicate["state"] == "approved"

    current_id = "release:" + "3" * 40
    request_action(
        "apply_release_to_cvm",
        action_id=current_id,
        executor_name="github_deploy",
    )
    resume_action(
        current_id,
        approver="reviewer",
        approval_id="run-current",
        defer_execution=True,
    )
    completed = complete_action(
        current_id,
        success=True,
        approver="reviewer",
        approval_id="run-current",
        outcome={"deployment_outcome": "executed"},
    )

    assert completed["state"] == "executed"
    assert completed["superseded_count"] == 2
    assert list_pending_actions() == []
    assert get_action_state("release:" + "1" * 40)["state"] == "superseded"
    superseded_approved = get_action_state(approved_id)
    assert superseded_approved["state"] == "superseded"
    assert superseded_approved["superseded_by"] == current_id
    snapshot = approval_center_snapshot()
    assert snapshot["summary"]["states"] == {"superseded": 2, "executed": 1}
    assert snapshot["summary"]["waiting"] == 0


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


# --------------------------------------------------------------------------- #
# 补充：覆盖 _audit_sink 边界、_normalize_action 边界、_cooldown_active 各路径、
# delegate 方法、module-level 函数。目标：提升变异测试 kill rate。
# --------------------------------------------------------------------------- #


def test_audit_sink_returning_non_dict_falls_back_to_original_record() -> None:
    """audit_sink 返回非 dict 时，_audit 应回退到原始 record（line 56 分支）。"""
    sink_calls: list[dict] = []

    def sink(record: dict) -> str:  # 返回非 dict
        sink_calls.append(record)
        return "ok"

    guard = AutonomyGuard(audit_sink=sink)
    decision = guard.evaluate("restart_service", action_id="sink-non-dict")

    assert decision.allowed is True
    assert sink_calls, "audit_sink should have been invoked"
    assert any(row.get("event_type") == "decision" for row in sink_calls)


def test_audit_sink_returning_dict_is_used_as_audit_result() -> None:
    """audit_sink 返回 dict 时，_audit 应使用返回值（line 56 真分支）。"""

    def sink(record: dict) -> dict:
        return {**record, "captured": True}

    guard = AutonomyGuard(audit_sink=sink)
    result = guard._audit({"action_id": "x", "event_type": "decision"})
    assert result.get("captured") is True
    assert result.get("action_id") == "x"


def test_audit_sink_none_path_writes_to_real_audit_log() -> None:
    """audit_sink=None 时，_audit 应委托给 append_autonomy_audit（line 57-59）。"""
    from app.domain.autonomy.audit_log import list_autonomy_audit

    guard = AutonomyGuard()  # audit_sink=None
    guard._audit(
        {
            "action_id": "sink-none-test",
            "action": "test_action",
            "risk_level": "LOW",
            "decision": "allow",
            "outcome": "allowed",
        }
    )
    rows = list_autonomy_audit(limit=10, action_id="sink-none-test")
    assert rows
    assert rows[0]["action_id"] == "sink-none-test"


def test_cooldown_active_returns_false_when_audit_sink_is_set() -> None:
    """audit_sink 非 None 时，_cooldown_active 直接返回 False（line 361-362）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    assert guard._cooldown_active("rollback_release") is False


def test_cooldown_active_returns_false_when_timestamp_invalid() -> None:
    """latest_action_event 返回的 timestamp 无效时，_cooldown_active 返回 False（line 372-373）。"""
    from app.domain.autonomy.audit_log import append_autonomy_audit

    append_autonomy_audit(
        {
            "action_id": "bad-ts",
            "action": "rollback_release",
            "risk_level": "MEDIUM",
            "decision": "allow",
            "outcome": "allowed",
            "timestamp": "not-an-iso-timestamp",
        }
    )
    guard = AutonomyGuard()  # audit_sink=None → 走 latest_action_event 路径
    assert guard._cooldown_active("rollback_release") is False


def test_cooldown_active_returns_false_when_no_previous_event() -> None:
    """latest_action_event 返回 None 时，_cooldown_active 返回 False（line 366-367）。"""
    guard = AutonomyGuard()
    assert guard._cooldown_active("never_seen_action_xyz") is False


def test_cooldown_active_returns_false_when_timestamp_naive_but_valid() -> None:
    """timestamp 无 tzinfo 但有效时，应补 UTC 后继续判断（line 371）。"""
    from app.domain.autonomy.audit_log import append_autonomy_audit

    # 写入一条 naive timestamp（无 tzinfo）的记录，时间设为很久以前 → cooldown 不活跃
    append_autonomy_audit(
        {
            "action_id": "naive-ts",
            "action": "rollback_release",
            "risk_level": "MEDIUM",
            "decision": "allow",
            "outcome": "allowed",
            "timestamp": "2020-01-01T00:00:00",  # naive，无 tzinfo
        }
    )
    guard = AutonomyGuard()  # audit_sink=None
    # 时间很久以前，cooldown 窗口已过 → False
    assert guard._cooldown_active("rollback_release") is False


def test_normalize_action_dict_with_risk_key_instead_of_risk_level() -> None:
    """dict 输入用 'risk' 键（而非 'risk_level'）时应正确解析（line 341 fallback）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    name, explicit, tool_id, operation, _metadata = guard._normalize_action(
        {"action": "restart_service", "risk": "LOW"}
    )
    assert name == "restart_service"
    assert explicit is RiskLevel.LOW
    assert tool_id == ""
    assert operation == ""


def test_normalize_action_dict_with_tool_action_instead_of_operation() -> None:
    """dict 输入用 'tool_action' 键（而非 'operation'）时应正确解析（line 338 fallback）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    name, _explicit, tool_id, operation, _metadata = guard._normalize_action(
        {"tool_id": "customers", "tool_action": "query"}
    )
    assert name == "customers.query"
    assert tool_id == "customers"
    assert operation == "query"


def test_normalize_action_dict_missing_action_name_and_tool_id_returns_unknown() -> None:
    """dict 缺 action/name/tool_id 时应返回 'unknown'（line 343）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    name, _explicit, _tool_id, _operation, _metadata = guard._normalize_action({"risk": "LOW"})
    assert name == "unknown"


def test_normalize_action_object_without_type_falls_back_to_action_attribute() -> None:
    """object 无 type 属性时，应回退到 .action 属性（line 345）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    obj = SimpleNamespace(action="restart_service", risk="LOW", idempotency_key="obj-1")
    name, explicit, _tool_id, _operation, metadata = guard._normalize_action(obj)
    assert name == "restart_service"
    assert explicit is RiskLevel.LOW
    assert metadata["idempotency_key"] == "obj-1"
    assert metadata["params"] == {}


def test_normalize_action_object_with_none_params_uses_empty_dict() -> None:
    """object 的 params 为 None 时，metadata['params'] 应为 {}（line 351）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    obj = SimpleNamespace(type="restart_service", params=None, idempotency_key=None)
    _name, _explicit, _tool_id, _operation, metadata = guard._normalize_action(obj)
    assert metadata["params"] == {}
    assert metadata["idempotency_key"] == ""


def test_evaluate_resolves_action_id_from_metadata_action_id() -> None:
    """metadata 中带 action_id 时应被用作 resolved_action_id（line 150）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate({"action": "restart_service", "action_id": "meta-action-id"})
    assert decision.action_id == "meta-action-id"


def test_evaluate_resolves_action_id_from_metadata_idempotency_key() -> None:
    """metadata 中带 idempotency_key（无 action_id）时应被用作 resolved_action_id（line 151）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate({"action": "restart_service", "idempotency_key": "meta-idem-key"})
    assert decision.action_id == "meta-idem-key"


def test_evaluate_unregistered_action_with_explicit_low_risk_fails_open() -> None:
    """spec=None 但 explicit_level=LOW 时，应继续评估（line 174-186 不触发 blocked）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate({"action": "custom_unregistered", "risk_level": "LOW"})
    assert decision.risk_level is RiskLevel.LOW
    assert decision.allowed is True
    assert decision.decision == "allow"


def test_evaluate_unregistered_action_with_explicit_blocked_risk_blocks() -> None:
    """spec=None 但 explicit_level=BLOCKED 时，应进入 BLOCKED 分支（line 238-250）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate({"action": "custom_unregistered", "risk_level": "BLOCKED"})
    assert decision.risk_level is RiskLevel.BLOCKED
    assert decision.allowed is False
    assert decision.decision == "blocked"


def test_evaluate_explicit_level_lower_than_spec_risk_does_not_escalate() -> None:
    """explicit_level < spec risk 时，risk 保持 spec 值（line 191-199 不升级）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate({"action": "apply_release_to_cvm", "risk_level": "LOW"})
    assert decision.risk_level is RiskLevel.HIGH


def test_evaluate_low_risk_with_allow_auto_false_requires_human(tmp_path: Path) -> None:
    """LOW risk 但 spec.allow_auto_execute=False 时应要求人工审批。"""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    modified = json.loads(json.dumps(registry))
    modified["autonomous_actions"]["restart_service"]["allow_auto_execute"] = False
    tmp_registry = tmp_path / "test-registry-low-no-auto.json"
    tmp_registry.write_text(json.dumps(modified), encoding="utf-8")
    guard = AutonomyGuard(registry_path=tmp_registry, audit_sink=lambda r: r)
    decision = guard.evaluate("restart_service", action_id="low-no-auto")
    assert decision.risk_level is RiskLevel.LOW
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.decision == "require_human"


def test_evaluate_high_risk_without_auto_approval_requires_human(tmp_path: Path) -> None:
    """HIGH risk 且 allow_auto=False 时应进入 require_human。"""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    modified = json.loads(json.dumps(registry))
    modified["autonomous_actions"]["apply_release_to_cvm"]["allow_auto_execute"] = False
    tmp_registry = tmp_path / "test-registry-high-no-auto.json"
    tmp_registry.write_text(json.dumps(modified), encoding="utf-8")
    guard = AutonomyGuard(registry_path=tmp_registry, audit_sink=lambda r: r)
    decision = guard.evaluate("apply_release_to_cvm", action_id="high-no-auto")
    assert decision.risk_level is RiskLevel.HIGH
    assert decision.allowed is False
    assert decision.decision == "require_human"


def test_aggregate_decisions_delegate_combines_node_decisions() -> None:
    """AutonomyGuard.aggregate_decisions 应委托到 aggregate_risk_decisions。"""
    from app.domain.autonomy.risk_types import RiskDecision

    guard = AutonomyGuard(audit_sink=lambda r: r)
    nodes = [
        ("node-a", RiskDecision(requires_confirmation=False, reason="ok", allowed=True)),
        ("node-b", RiskDecision(requires_confirmation=True, reason="blocked", allowed=False)),
    ]
    result = guard.aggregate_decisions(nodes, action="composite", action_id="agg-1")
    assert result.action == "composite"
    assert result.action_id == "agg-1"
    assert result.requires_confirmation is True
    assert "node-b" in result.blocking_nodes


def test_assess_employee_risk_delegate_returns_tuple() -> None:
    """AutonomyGuard.assess_employee_risk 应委托到 RiskPolicyCatalog。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    level, reason = guard.assess_employee_risk({}, ["agent"])
    assert level is RiskLevel.MEDIUM
    assert "handlers inferred" in reason


def test_requires_write_approval_and_write_tools_delegates() -> None:
    """覆盖 requires_write_approval / requires_write_approval_for_spec / list_write_tools / list_code_write_tools。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    assert guard.requires_write_approval("patch_file") is True
    assert guard.requires_write_approval("customers", "query") is False
    assert guard.requires_write_approval_for_spec({"requires_write_approval": True}) is True
    assert guard.requires_write_approval_for_spec({"action_class": "im.send"}) is False
    write_tools = guard.list_write_tools()
    assert {"patch_file", "write_file", "customers"} <= write_tools
    assert guard.list_code_write_tools() == frozenset({"patch_file", "write_file"})


def test_get_action_spec_delegate_returns_spec_or_none() -> None:
    """覆盖 get_action_spec 委托（含 None 路径）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    spec = guard.get_action_spec("customers", "create")
    assert spec is not None
    assert spec.get("requires_write_approval") is True
    assert guard.get_action_spec("missing", "execute") is None


def test_registry_and_boundaries_snapshots_return_copies() -> None:
    """覆盖 registry_snapshot / boundaries_snapshot / veto_boundaries_snapshot / autonomous_action_names。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    snap = guard.registry_snapshot()
    snap["mutated"] = True
    assert "mutated" not in guard._policy.registry
    b_snap = guard.boundaries_snapshot()
    b_snap.clear()
    assert guard._policy.boundaries
    v_snap = guard.veto_boundaries_snapshot()
    assert v_snap == {}
    names = guard.autonomous_action_names()
    assert "restart_service" in names
    assert isinstance(names, frozenset)


def test_evaluate_risk_module_level_function_uses_global_guard() -> None:
    """evaluate_risk 应使用 get_autonomy_guard() 返回的实例。"""
    from app.domain.autonomy.autonomy_guard import evaluate_risk

    decision = evaluate_risk("restart_service", action_id="module-level")
    assert decision.risk_level is RiskLevel.LOW
    assert decision.allowed is True


def test_reload_autonomy_guard_returns_fresh_instance() -> None:
    """reload_autonomy_guard 应返回新的 AutonomyGuard 实例。"""
    from app.domain.autonomy import autonomy_guard as ag_module

    first = ag_module.get_autonomy_guard()
    reloaded = ag_module.reload_autonomy_guard()
    assert first is not reloaded
    assert ag_module._GUARD is reloaded


def test_record_config_state_with_audit_sink_emits_config_loaded() -> None:
    """audit_sink 非 None 时，_record_config_state 应走 config_loaded 路径（previous=None）。"""
    events: list[dict] = []
    guard = AutonomyGuard(audit_sink=events.append)
    config_events = [e for e in events if e.get("event_type") == "config"]
    assert len(config_events) == 1
    assert config_events[0]["decision"] == "config_loaded"
    assert config_events[0]["policy"] == guard.medium_risk_policy.value


def test_record_config_state_skips_audit_when_policy_unchanged() -> None:
    """audit_sink=None 时，若上次配置相同，_record_config_state 应跳过审计（line 69-70）。"""
    from app.domain.autonomy.audit_log import append_autonomy_audit, list_autonomy_audit

    append_autonomy_audit(
        {
            "action_id": "config-prev",
            "action": "__configuration__",
            "risk_level": "LOW",
            "decision": "config_loaded",
            "outcome": "medium_risk_policy_active",
            "event_type": "config",
            "policy": "auto_approve",
            "metadata": {},
        }
    )
    AutonomyGuard()  # audit_sink=None → 走 latest_action_event 路径；policy 相同不应新增
    config_rows = list_autonomy_audit(limit=50, action_id="config-prev")
    assert len(config_rows) == 1  # 只有预置的那条


def test_medium_risk_policy_require_human_falls_through_to_human_approval(
    tmp_path: Path,
) -> None:
    """MEDIUM + REQUIRE_HUMAN 时，automatic_reason 为空，应走 approval_evidence 路径。"""
    registry = _registry_with_policy(tmp_path, "require_human")
    guard = AutonomyGuard(registry_path=registry, audit_sink=lambda r: r)
    decision = guard.evaluate("rollback_release", action_id="req-human-no-approve")
    assert decision.risk_level is RiskLevel.MEDIUM
    assert decision.allowed is False
    assert decision.decision == "require_human"
    assert "medium_risk_policy=require_human" in decision.reason


def test_medium_risk_policy_require_human_with_legacy_medium_approval_allows(
    tmp_path: Path,
) -> None:
    """MEDIUM + REQUIRE_HUMAN + allow_medium_risk=True 时，应走 approval_evidence 通过。"""
    registry = _registry_with_policy(tmp_path, "require_human")
    guard = AutonomyGuard(registry_path=registry, audit_sink=lambda r: r)
    decision = guard.evaluate(
        "rollback_release",
        {"allow_medium_risk": True, "approved_by": "operator"},
        action_id="req-human-approved",
    )
    assert decision.allowed is True
    assert decision.decision == "approved"
    assert decision.approver == "operator"


def test_evaluate_prohibited_action_audits_with_rollback_path() -> None:
    """prohibited action 的审计事件应包含 risk_level=BLOCKED 和 outcome=exception_raised。"""
    events: list[dict] = []
    guard = AutonomyGuard(audit_sink=events.append)
    with pytest.raises(ProhibitedActionError):
        guard.evaluate("db_migration", action_id="prohibited-audit")
    prohibited_events = [e for e in events if e.get("decision") == "prohibited"]
    assert len(prohibited_events) == 1
    assert prohibited_events[0]["risk_level"] == "BLOCKED"
    assert prohibited_events[0]["outcome"] == "exception_raised"


def test_evaluate_strips_action_string_whitespace() -> None:
    """string 输入带空白时，_normalize_action 应 strip（line 333）。"""
    guard = AutonomyGuard(audit_sink=lambda r: r)
    decision = guard.evaluate("  restart_service  ", action_id="strip-test")
    assert decision.action == "restart_service"
    assert decision.allowed is True
