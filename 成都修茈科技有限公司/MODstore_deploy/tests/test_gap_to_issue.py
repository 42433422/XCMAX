# 成都修茈科技有限公司/MODstore_deploy/tests/test_gap_to_issue.py
"""gap_to_issue 单元测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from modstore_server.gap_to_issue import (
    DuplicateProposalError,
    build_issue_body,
    dedupe_signal,
    open_issue_for_proposal,
)


def _make_proposal() -> dict:
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


def test_build_issue_body_contains_proposal_json():
    proposal = _make_proposal()
    body = build_issue_body(proposal)
    assert "```json" in body
    assert "intent-failure-triage-clerk" in body
    parsed = json.loads(body.split("```json\n")[1].split("\n```")[0])
    assert parsed["proposal_id"] == "test-uuid-001"


def test_open_issue_for_proposal_calls_gh(monkeypatch):
    """正常流程：调 gh issue create。"""
    proposal = _make_proposal()
    mock_run = MagicMock(
        return_value=MagicMock(returncode=0, stdout="https://github.com/x/y/issues/42\n")
    )
    monkeypatch.setattr("modstore_server.gap_to_issue.subprocess.run", mock_run)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    issue_url = open_issue_for_proposal(proposal)
    assert issue_url == "https://github.com/x/y/issues/42"
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "gh" in cmd
    assert "issue" in cmd
    assert "create" in cmd


def test_open_issue_for_proposal_writes_ledger(monkeypatch, tmp_path):
    """开 issue 后写 ledger event。"""
    proposal = _make_proposal()
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="https://github.com/x/y/issues/99\n"),
    )
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    open_issue_for_proposal(proposal)
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "issue_opened"
    assert evt["issue_url"] == "https://github.com/x/y/issues/99"
    assert evt["llm_proposal"]["proposal_id"] == "test-uuid-001"


def test_dedupe_signal_rejects_recent_duplicate(monkeypatch, tmp_path):
    """5 分钟内同 proposal_id 不重复开 issue。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).isoformat()
    ledger_path.write_text(
        json.dumps(
            {
                "event_id": "x",
                "event_type": "issue_opened",
                "timestamp": recent,
                "llm_proposal": {"proposal_id": "test-uuid-001"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    proposal = _make_proposal()
    with pytest.raises(DuplicateProposalError):
        dedupe_signal(proposal)


def test_dedupe_signal_allows_old_proposal(monkeypatch, tmp_path):
    """5 分钟前的同 proposal_id 允许重开。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ledger_path.write_text(
        json.dumps(
            {
                "event_id": "x",
                "event_type": "issue_opened",
                "timestamp": old,
                "llm_proposal": {"proposal_id": "test-uuid-001"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    proposal = _make_proposal()
    dedupe_signal(proposal)  # 不抛异常即通过


def test_open_issue_for_proposal_gh_failure_raises(monkeypatch):
    proposal = _make_proposal()
    monkeypatch.setattr(
        "modstore_server.gap_to_issue.subprocess.run",
        lambda *a, **k: MagicMock(returncode=1, stderr="auth error"),
    )
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    with pytest.raises(RuntimeError, match="gh issue create failed"):
        open_issue_for_proposal(proposal)
