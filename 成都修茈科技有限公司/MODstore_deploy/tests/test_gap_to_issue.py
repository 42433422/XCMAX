"""Proposal rendering, GitHub handoff and deduplication contracts."""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from modstore_server.gap_to_issue import (
    DuplicateProposalError,
    build_issue_body,
    dedupe_signal,
    open_issue_for_proposal,
)


@pytest.fixture
def proposal():
    return {
        "proposal_id": "test-uuid-001",
        "triggered_by": "intent_benchmark",
        "signal_score": 0.08,
        "department": "engineering",
        "employee_pack": {
            "name": "intent-failure-triage-clerk",
            "responsibility": "scan failed intent cases",
            "prompt_template": "You are...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def test_build_issue_body_contains_proposal_json(proposal):
    body = build_issue_body(proposal)
    assert "```json" in body
    assert "intent-failure-triage-clerk" in body
    parsed = json.loads(body.split("```json\n")[1].split("\n```")[0])
    assert parsed["proposal_id"] == "test-uuid-001"


@pytest.mark.parametrize("issue_number", [42, 99])
def test_open_issue_calls_gh_and_writes_ledger(tmp_path, monkeypatch, proposal, issue_number):
    issue_url = f"https://github.com/x/y/issues/{issue_number}"
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=issue_url + "\n"))
    monkeypatch.setattr("modstore_server.gap_to_issue.subprocess.run", mock_run)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    assert open_issue_for_proposal(proposal) == issue_url
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0][:3] == ["gh", "issue", "create"]
    lines = (tmp_path / "evolution_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "issue_opened"
    assert event["issue_url"] == issue_url
    assert event["llm_proposal"]["proposal_id"] == "test-uuid-001"


@pytest.mark.parametrize("age_minutes", [0, 60])
def test_dedupe_signal_respects_window(tmp_path, proposal, age_minutes):
    timestamp = (datetime.now(UTC) - timedelta(minutes=age_minutes)).isoformat()
    (tmp_path / "evolution_decisions.jsonl").write_text(
        json.dumps(
            {
                "event_id": "x",
                "event_type": "issue_opened",
                "timestamp": timestamp,
                "llm_proposal": {"proposal_id": "test-uuid-001"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DuplicateProposalError) if age_minutes == 0 else nullcontext():
        dedupe_signal(proposal)


def test_open_issue_for_proposal_gh_failure_raises(monkeypatch, proposal):
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        lambda *a, **k: MagicMock(returncode=1, stderr="auth error"),
    )
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    with pytest.raises(RuntimeError, match="gh issue create failed"):
        open_issue_for_proposal(proposal)
