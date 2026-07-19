from __future__ import annotations

from types import SimpleNamespace

import pytest

from modstore_server import approval_dispatcher, daily_digest
from modstore_server import self_maintenance_loop_runner as loop_runner
from modstore_server.daily_vibe_line_execute_job import run_daily_vibe_line_execute_job


@pytest.fixture(autouse=True)
def isolated_autonomy(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    reload_autonomy_guard()


def test_daily_vibe_cron_enters_pending_before_dispatch() -> None:
    result = run_daily_vibe_line_execute_job(record_id=42)
    assert result["ok"] is False
    assert result["reason"] == "autonomy_guard_pending_approval"
    assert result["pending_approval"]["state"] == "pending_approval"
    assert result["risk_decision"]["risk_level"] == "medium"


def test_daily_vibe_rejected_action_is_not_requeued() -> None:
    first = run_daily_vibe_line_execute_job(record_id=42)
    from app.application.autonomy.approval_resume import reject_action

    action_id = first["pending_approval"]["action_id"]
    reject_action(action_id, approver="reviewer", reason="test veto")
    second = run_daily_vibe_line_execute_job(record_id=42)
    assert second["reason"] == "autonomy_guard_rejected_or_terminal"
    assert second["pending_approval"]["state"] == "rejected"


def test_daily_digest_cron_passes_through_low_risk_guard(monkeypatch) -> None:
    monkeypatch.setattr(
        "modstore_server.automation_primary.skip_daily_automation_result",
        lambda **kwargs: {"ok": True, "skipped": True, "reason": "test-after-guard"},
    )
    result = daily_digest.run_daily_digest_email()
    assert result["reason"] == "test-after-guard"


def test_loop_never_reaches_git_merge_when_domain_guard_denies(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/autonomy-test.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(loop_runner, "_changed_files_for_branch", lambda **kwargs: ["safe.py"])
    monkeypatch.setattr(
        loop_runner,
        "_diff_numstat_for_branch",
        lambda **kwargs: {"files": 1, "additions": 1, "deletions": 0},
    )
    commands: list[list[str]] = []

    def fake_command(command, **kwargs):
        commands.append(command)
        return "diff"

    monkeypatch.setattr(loop_runner, "_run_cmd", fake_command)
    monkeypatch.setattr(
        loop_runner,
        "_validate_kb_json_changes_for_auto_merge",
        lambda **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        loop_runner,
        "_assess_branch_auto_merge_policy",
        lambda *args, **kwargs: {"ok": True, "merge_tier": "L1"},
    )
    monkeypatch.setattr(loop_runner, "_load_loop_memory", lambda: {})
    monkeypatch.setattr(
        "modstore_server.autonomy_guard_delegate.evaluate_risk",
        lambda *args, **kwargs: SimpleNamespace(
            allowed=False,
            requires_confirmation=True,
            to_dict=lambda: {"decision": "require_human"},
        ),
    )

    result = loop_runner._auto_merge_low_risk_branch(
        run_id="risk-gate-test",
        task_id="task-1",
        branch="autonomy/test",
        steps=[],
    )
    assert result["reason"] == "autonomy_guard_pending_approval"
    assert not any(command[:2] == ["git", "merge"] for command in commands)


def test_high_risk_pr_merge_requires_and_records_human_approval(monkeypatch, tmp_path) -> None:
    blocked = approval_dispatcher._maybe_merge_pr("auto/security-fix")
    assert blocked["ok"] is False
    assert blocked["risk_decision"]["decision"] == "require_human"

    monkeypatch.setattr(
        "modstore_server.integrations.ops_action_handlers.repo_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    approved = approval_dispatcher._maybe_merge_pr(
        "auto/security-fix",
        human_approved_by="ops-approval-token:42",
    )
    assert approved["ok"] is True
    assert approved["risk_decision"]["decision"] == "approved"
    assert approved["risk_decision"]["approver"] == "ops-approval-token:42"
