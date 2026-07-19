from __future__ import annotations

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

FHD_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = FHD_ROOT / "config" / "risk_actions.registry.json"
BOUNDARIES = FHD_ROOT / "config" / "autonomy_boundaries.yaml"


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


def test_four_risk_levels_have_allow_approval_and_hard_block_branches() -> None:
    audit: list[dict] = []
    guard = AutonomyGuard(audit_sink=audit.append)

    low = guard.evaluate("restart_service", action_id="low")
    medium = guard.evaluate("rollback_release", action_id="medium")
    high = guard.evaluate("apply_release_to_cvm", action_id="high")

    assert low.risk_level is RiskLevel.LOW and low.allowed
    assert medium.risk_level is RiskLevel.MEDIUM and medium.requires_confirmation
    assert high.risk_level is RiskLevel.HIGH and high.requires_confirmation
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


def test_pending_approval_resumes_and_rejection_never_retries() -> None:
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

    summary = summarize_autonomy_audit(days=1)
    assert summary["total"] > 0
    assert summary["veto_count"] > 0


def test_deferred_workflow_only_marks_executed_after_real_outcome() -> None:
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
