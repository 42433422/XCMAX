from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from modstore_server import approval_dispatcher, daily_digest
from modstore_server import self_maintenance_loop_runner as loop_runner
from modstore_server.daily_vibe_line_execute_job import run_daily_vibe_line_execute_job


@pytest.fixture(autouse=True)
def isolated_autonomy(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    reload_autonomy_guard()


def test_daily_vibe_cron_auto_approves_before_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "modstore_server.automation_primary.skip_daily_automation_result",
        lambda **kwargs: {
            "ok": True,
            "skipped": True,
            "reason": "test-after-auto-gate",
        },
    )
    result = run_daily_vibe_line_execute_job(record_id=42)
    assert result["ok"] is True
    assert result["reason"] == "test-after-auto-gate"

    from app.application.autonomy.audit_log import list_autonomy_audit

    rows = [row for row in list_autonomy_audit(limit=20) if row["action"] == "daily_vibe_dispatch"]
    assert rows and rows[0]["decision"] == "auto_approve"


def test_delegate_accepts_deployed_fhd_runtime_root(tmp_path, monkeypatch) -> None:
    runtime_fhd = tmp_path / "fhd-runtime"
    guard_path = runtime_fhd / "app" / "domain" / "autonomy" / "autonomy_guard.py"
    guard_path.parent.mkdir(parents=True)
    guard_path.write_text("# runtime guard probe\n", encoding="utf-8")
    monkeypatch.setenv("XCAGI_FHD_RUNTIME_ROOT", str(runtime_fhd))
    monkeypatch.delenv("XCMAX_MONOREPO_ROOT", raising=False)

    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()

    assert str(runtime_fhd) in sys.path
    sys.path.remove(str(runtime_fhd))


def test_delegate_falls_back_to_git_repo_fhd_when_runtime_mirror_lags(
    tmp_path, monkeypatch
) -> None:
    """Daily env points XCAGI_FHD_ROOT at a stale mirror missing autonomy/."""
    stale_runtime = tmp_path / "stale-runtime-fhd"
    (stale_runtime / "app" / "domain").mkdir(parents=True)
    source_fhd = tmp_path / "source-checkout" / "FHD"
    guard_path = source_fhd / "app" / "domain" / "autonomy" / "autonomy_guard.py"
    guard_path.parent.mkdir(parents=True)
    guard_path.write_text("# source guard probe\n", encoding="utf-8")

    monkeypatch.delenv("XCAGI_FHD_RUNTIME_ROOT", raising=False)
    monkeypatch.setenv("XCAGI_FHD_ROOT", str(stale_runtime))
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path / "stale-monorepo"))
    monkeypatch.setenv("MODSTORE_GIT_REPO_ROOT", str(tmp_path / "source-checkout"))

    from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path

    ensure_fhd_on_path()

    assert str(source_fhd) in sys.path
    sys.path.remove(str(source_fhd))


def test_delegate_repairs_an_existing_app_namespace() -> None:
    modstore_root = Path(__file__).resolve().parents[1]
    fhd_root = Path(__file__).resolve().parents[3] / "FHD"
    script = """
import sys
import types
app = types.ModuleType("app")
app.__path__ = []
domain = types.ModuleType("app.domain")
domain.__path__ = []
sys.modules["app"] = app
sys.modules["app.domain"] = domain
from modstore_server.autonomy_guard_delegate import ensure_fhd_on_path
ensure_fhd_on_path()
from app.domain.autonomy.autonomy_guard import AutonomyGuard
assert AutonomyGuard
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(modstore_root),
        "XCAGI_FHD_RUNTIME_ROOT": str(fhd_root),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_employee_executor_fails_closed_when_risk_middleware_errors(
    monkeypatch,
) -> None:
    from modstore_server import employee_executor, employee_risk_middleware

    def broken_gate(*_args, **_kwargs):
        raise ModuleNotFoundError("risk SSOT unavailable")

    monkeypatch.setattr(employee_risk_middleware, "gate_action_or_block", broken_gate)
    decision = employee_executor._evaluate_employee_risk_gate("worker", {}, ["agent"], {})

    assert decision["ok"] is False
    assert decision["blocked"] is True
    assert decision["pending_approval"] is False
    assert decision["risk_level"] == "blocked"
    assert decision["decision"] == "blocked"


def test_legacy_manual_policy_rejected_action_is_not_requeued(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    reload_autonomy_guard()
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


def test_autonomy_metrics_snapshot_is_low_risk_and_idempotent() -> None:
    from modstore_server.autonomy_metrics_job import run_autonomy_metrics_snapshot

    first = run_autonomy_metrics_snapshot()
    second = run_autonomy_metrics_snapshot()

    assert first["ok"] is True and first["skipped"] is False
    assert [item["window_days"] for item in first["snapshots"]] == [30, 90]
    assert all(item["recorded"] for item in first["snapshots"])
    assert all(not item["recorded"] for item in second["snapshots"])
    assert first["risk_decision"]["risk_level"] == "low"
    assert first["risk_decision"]["decision"] == "allow"
    assert first["risk_decision"]["approver"] is None


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
    monkeypatch.setattr(loop_runner, "_run_cmd_excerpt", fake_command, raising=False)
    monkeypatch.setattr(
        "modstore_server.self_maintenance_subprocess.run_cmd_excerpt",
        fake_command,
    )
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
    assert result["reason"] == "autonomy_guard_blocked"
    assert commands == []
    assert not any(command[:2] == ["git", "merge"] for command in commands)


def test_high_risk_pr_merge_auto_approves_and_is_audited(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "modstore_server.integrations.ops_action_handlers.repo_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    approved = approval_dispatcher._maybe_merge_pr("auto/security-fix")
    assert approved["ok"] is True
    assert approved["risk_decision"]["decision"] == "auto_approve"
    assert approved["risk_decision"]["approver"] is None
