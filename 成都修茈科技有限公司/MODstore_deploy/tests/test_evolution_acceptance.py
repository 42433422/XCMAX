"""Evolution E2E and acceptance scenarios share one isolated setup.

Both original full-loop proposal identities retain signal, issue, package,
catalog and ledger assertions; the audit CLI also checks both identities.
Actual retry exhaustion, CLI escalation and high-risk rejection stay separate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_FHD_SCRIPTS_DEV = Path(__file__).resolve().parents[3] / "FHD" / "scripts" / "dev"
if str(_FHD_SCRIPTS_DEV) not in sys.path:
    sys.path.insert(0, str(_FHD_SCRIPTS_DEV))

from retry_with_adjusted_prompt import run_with_retries  # noqa: E402

from modstore_server.auto_approve_policy import evaluate_employee_pack  # noqa: E402
from modstore_server.build_employee_pack import (  # noqa: E402
    PACK_FILES_PREFIX,
    build_pack_from_commit,
)
from modstore_server.employee_autonomy_service import propose_employee_pack  # noqa: E402
from modstore_server.evolution_ledger import append_event, list_events  # noqa: E402
from modstore_server.evolution_signal_collector import aggregate_signals  # noqa: E402
from modstore_server.gap_to_issue import open_issue_for_proposal  # noqa: E402


@pytest.fixture
def proposal_id():
    return "acceptance-test-uuid-001"


@pytest.fixture
def proposal(proposal_id):
    return {
        "proposal_id": proposal_id,
        "department": "engineering",
        "employee_pack": {
            "name": "intent-failure-triage-clerk",
            "responsibility": "scan failed intent cases and cluster failure patterns",
            "prompt_template": "You are an intent failure triage clerk...",
            "skills": ["intent-benchmark", "failure-clustering"],
            "tools": ["read_file", "write_pr_comment"],
            "acceptance_criteria": ["recall >= 0.7 on test set"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


@pytest.fixture
def proposed_issue(tmp_path, monkeypatch, proposal, proposal_id):
    reports = {
        "legacy": {"legacy_ratio": 0.10, "total_files": 100, "legacy_files": 10},
        "intent": {"accuracy": 0.72, "test_cases": 200, "failures": 56},
        "slo": {"availability": 0.992, "error_rate": 0.005},
    }
    for name, report in reports.items():
        path = tmp_path / f"{name}_report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        monkeypatch.setenv(f"MODSTORE_{name.upper()}_REPORT_PATH", str(path))
    signals = aggregate_signals()
    assert signals["signals_to_propose"] >= 1
    assert signals["intent_benchmark"]["below_threshold"] is True
    assert signals["intent_benchmark"]["signal_score"] > 0
    assert signals["legacy_usage"]["signal_score"] == 0
    assert signals["slo_metrics"]["signal_score"] == 0
    with patch("modstore_server.employee_autonomy_service._call_llm", return_value=proposal):
        generated = propose_employee_pack(signals)
    assert generated is not None
    assert generated["proposal_id"] == proposal_id
    assert generated["triggered_by"] == "intent_benchmark"
    assert generated["signal_score"] > 0
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    issue_url = "https://github.com/owner/repo/issues/42"
    # Scope the gh mock so native audit/escalation subprocesses still execute.
    with patch(
        "modstore_server.gap_to_issue.subprocess.run",
        return_value=MagicMock(returncode=0, stdout=issue_url + "\n"),
    ):
        assert open_issue_for_proposal(generated) == issue_url
    events = list_events(event_type="issue_opened")
    assert len(events) == 1
    assert events[0]["issue_url"] == issue_url
    assert events[0]["llm_proposal"]["proposal_id"] == proposal_id
    return generated


@pytest.fixture
def pack_files(tmp_path, monkeypatch):
    def create(name="intent-clerk", **overrides):
        source = tmp_path / PACK_FILES_PREFIX / f"{name}@1.0.0"
        source.mkdir(parents=True)
        manifest = {
            "name": name,
            "version": "1.0.0",
            "department": "engineering",
            "prompt_template": "You are an intent clerk...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
            **overrides,
        }
        (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (source / "prompt.txt").write_text(manifest["prompt_template"], encoding="utf-8")
        catalog = tmp_path / "packages.json"
        catalog.write_text(json.dumps({"schema": 1, "packages": []}), encoding="utf-8")
        monkeypatch.setenv("MODSTORE_CATALOG_PACKAGES_PATH", str(catalog))
        monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(source.parent))
        return SimpleNamespace(source=source, catalog=catalog, pack_id=source.name)

    return create


@pytest.fixture
def evolution_cli(tmp_path):
    empty_bin = tmp_path / "no-external-executables"
    empty_bin.mkdir()

    def run(script, *args):
        # No real gh or credential-bearing callback environment reaches the child.
        return subprocess.run(
            [sys.executable, str(_FHD_SCRIPTS_DEV / script), *args],
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "PATH": str(empty_bin),
                "PYTHONDONTWRITEBYTECODE": "1",
                "GITHUB_REPO": "owner/repo",
                "MODSTORE_EVOLUTION_LEDGER_PATH": os.environ["MODSTORE_EVOLUTION_LEDGER_PATH"],
            },
        )

    return run


@pytest.mark.parametrize("proposal_id", ["e2e-test-uuid-001", "acceptance-test-uuid-001"])
def test_full_loop_lists_pack_and_remains_auditable(
    tmp_path, proposed_issue, pack_files, evolution_cli
):
    pack = pack_files()
    diff_files = [path.relative_to(tmp_path).as_posix() for path in pack.source.iterdir()]
    with (
        patch(
            "modstore_server.build_employee_pack._get_commit_diff_files", return_value=diff_files
        ),
        patch(
            "modstore_server.build_employee_pack.evaluate_employee_pack",
            return_value=("low", "auto-approved"),
        ),
    ):
        result = build_pack_from_commit(commit_sha="abc123", repo_root=tmp_path)
    assert result["approved"] is True
    assert result["pack_id"] == pack.pack_id
    assert result["risk_level"] == "low"
    catalog = json.loads(pack.catalog.read_text(encoding="utf-8"))
    assert len(catalog["packages"]) == 1
    assert catalog["packages"][0]["id"] == "intent-clerk"
    events = list_events()
    assert len(events) >= 2
    assert events[-1]["event_type"] == "pack_built"
    assert events[-1]["pack_id"] == pack.pack_id
    assert events[-1]["final_status"] == "pack_listed"
    audited = evolution_cli("audit_evolution.py", "--event", "pack_built")
    assert audited.returncode == 0, audited.stderr
    assert pack.pack_id in audited.stdout
    assert "pack_listed" in audited.stdout


def test_retries_3_times_then_escalates(proposed_issue):
    def always_fail_action(_prompt):
        return {"ok": False, "error": "synthetic failure for e2e"}

    def always_fail_checker(result):
        return True, result.get("error") or "unknown"

    result = run_with_retries(
        base_prompt="base prompt for implement",
        action=always_fail_action,
        failure_checker=always_fail_checker,
        proposal=proposed_issue,
    )
    assert result["success"] is False
    assert result["attempts"] == 3
    assert result["final_status"] == "needs_human"
    events = list_events()
    assert len(list_events(event_type="implement_failed")) == 4
    assert events[-1]["event_type"] == "implement_failed"
    assert events[-1]["final_status"] == "needs_human"
    assert events[-1]["retry_count"] == 3


def test_acceptance_needs_human_after_3_retries(tmp_path, proposal, evolution_cli):
    proposal["triggered_by"] = "intent_benchmark"
    for attempt in range(1, 4):
        append_event(
            {
                "event_type": "implement_failed",
                "triggered_by": "intent_benchmark",
                "proposal_id": proposal["proposal_id"],
                "retry_count": attempt,
                "failure_reason": f"synthetic failure #{attempt}",
                "final_status": "implement_failed",
            }
        )
    assert len(list_events(event_type="implement_failed")) == 3
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
    reasons = [f"retry #{attempt} failed: synthetic failure #{attempt}" for attempt in range(1, 4)]
    result = evolution_cli(
        "escalate_to_human.py",
        "--issue-number",
        "42",
        "--proposal",
        str(proposal_path),
        "--failure-reasons",
        json.dumps(reasons),
    )
    assert result.returncode == 0, result.stderr
    escalated = list_events(event_type="escalated_to_human")
    assert len(escalated) == 1
    assert escalated[0]["final_status"] == "needs_human"
    assert escalated[0]["issue_number"] == 42
    assert escalated[0]["triggered_by"] == "intent_benchmark"
    events = list_events()
    assert events[-1]["event_type"] == "escalated_to_human"
    assert events[-1]["final_status"] == "needs_human"


def test_acceptance_high_risk_file_blocks_listing(pack_files):
    pack = pack_files(
        "evil-pack",
        prompt_template="You are...",
        skills=["some-skill"],
        acceptance_criteria=["criterion-1"],
    )
    (pack.source / "evil.env").write_text("SECRET_KEY=leaked", encoding="utf-8")
    risk_level, reason = evaluate_employee_pack(pack.pack_id)
    assert risk_level == "high"
    assert "evil.env" in reason.lower() or "high-risk" in reason.lower(), reason
