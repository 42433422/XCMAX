# FHD/scripts/dev/tests/test_pr_pipeline_helpers.py
"""PR 流水线辅助脚本单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from escalate_to_human import escalate
from open_pr_for_employee_pack import create_branch_commit_pr
from read_issue_proposal import extract_proposal_from_issue_body
from wait_for_pr_merge import is_pr_merged


def _make_issue_body() -> str:
    proposal = {
        "proposal_id": "abc-123",
        "department": "engineering",
        "employee_pack": {"name": "x", "prompt_template": "y", "skills": [], "tools": [], "acceptance_criteria": []},
        "estimated_files": 2,
        "estimated_tokens": 10000,
    }
    return f"""# Title

```json
{json.dumps(proposal, indent=2)}
```

Rest of body.
"""


def test_extract_proposal_finds_json_block():
    body = _make_issue_body()
    proposal = extract_proposal_from_issue_body(body)
    assert proposal["proposal_id"] == "abc-123"
    assert proposal["department"] == "engineering"


def test_extract_proposal_handles_no_json_block():
    body = "no json here"
    with pytest.raises(ValueError, match="no JSON"):
        extract_proposal_from_issue_body(body)


def test_extract_proposal_handles_invalid_json():
    body = "```json\n{not valid json\n```"
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_proposal_from_issue_body(body)


def test_create_branch_commit_pr_calls_git_in_order(monkeypatch, tmp_path):
    """分支创建 → commit → push → 开 PR。"""
    runs = []
    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="https://github.com/x/y/pull/1\n", stderr="")
    monkeypatch.setattr("open_pr_for_employee_pack.subprocess.run", fake_run)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "prompt.txt").write_text("test", encoding="utf-8")

    pr_url = create_branch_commit_pr(
        files_dir=files_dir,
        branch_name="ai-implement/abc-123",
        proposal={"proposal_id": "abc-123", "employee_pack": {"name": "x"}},
    )
    assert pr_url == "https://github.com/x/y/pull/1"
    # 验证调用顺序
    assert runs[0][:2] == ["git", "checkout"]
    assert runs[1][:2] == ["git", "add"]
    assert runs[2][:2] == ["git", "commit"]
    assert runs[3][:2] == ["git", "push"]
    assert runs[4][0] == "gh"


def test_is_pr_merged_returns_true_when_merged(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="MERGED\n", stderr="")
    )
    assert is_pr_merged(pr_number=1) is True


def test_is_pr_merged_returns_false_when_open(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="OPEN\n", stderr="")
    )
    assert is_pr_merged(pr_number=1) is False


def test_is_pr_merged_returns_false_on_error(monkeypatch):
    monkeypatch.setattr(
        "wait_for_pr_merge.subprocess.run",
        lambda *a, **k: MagicMock(returncode=1, stdout="", stderr="error")
    )
    assert is_pr_merged(pr_number=1) is False


def test_escalate_comments_on_issue_and_adds_label(monkeypatch, tmp_path):
    """转人工：在 issue comment + 打 needs-human 标签 + 写 ledger。"""
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    runs = []
    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("escalate_to_human.subprocess.run", fake_run)

    escalate(
        issue_number=42,
        proposal={"proposal_id": "abc-123"},
        failure_reasons=["gate 1 failed", "gate 2 failed", "gate 3 failed"],
    )

    # 验证调用了 issue comment + label add
    assert any("comment" in cmd for cmd in runs)
    assert any("label" in cmd for cmd in runs)
    # 验证 ledger 写入
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "escalated_to_human"
    assert evt["final_status"] == "needs_human"
