from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.external_merge_landing import build_external_merge_landing
from retort_engine.service import RetortService


def test_external_merge_landing_runs_real_branch_merge_and_pytest(tmp_path: Path) -> None:
    cache_a = tmp_path / ".retort" / "cache" / "github" / "owner" / "agent-a"
    cache_b = tmp_path / ".retort" / "cache" / "github" / "owner" / "agent-b"
    cache_a.mkdir(parents=True)
    cache_b.mkdir(parents=True)
    (cache_a / "README.md").write_text("agent a", encoding="utf-8")
    (cache_b / "action.yml").write_text("agent b", encoding="utf-8")
    cases = [
        {"source": "owner/agent-a", "source_path": ".retort/cache/github/owner/agent-a", "family": "python_pr_agent", "absorbed_rule": "semantic_review"},
        {"source": "owner/agent-b", "source_path": ".retort/cache/github/owner/agent-b", "family": "typescript_pr_bot", "absorbed_rule": "diff_hunk_review"},
    ]
    output = tmp_path / "docs" / "retort_external_merge_landing.json"

    result = build_external_merge_landing(tmp_path, min_cases=2, output=output, cases=cases)

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] == 2
    assert result["summary"]["branch_diff_count"] == 2
    assert result["summary"]["merge_commit_count"] == 2
    assert result["summary"]["post_merge_test_passed_count"] == 2
    assert result["summary"]["all_branch_diff_merge_tests_passed"] is True
    assert all(case["branch_diff_verified"] is True for case in result["cases"])
    assert all(case["post_merge_tests_passed"] is True for case in result["cases"])
    assert output.is_file()
    assert validate_contract("external_merge_landing_result", result)["valid"] is True

    repo = Path(result["evidence"]["repo"])
    log = subprocess.run(["git", "log", "--oneline", "--merges"], cwd=repo, check=True, stdout=subprocess.PIPE, text=True).stdout
    assert "merge absorbed owner/agent-a rule" in log
    assert "merge absorbed owner/agent-b rule" in log


def test_external_merge_landing_blocks_missing_cache(tmp_path: Path) -> None:
    result = build_external_merge_landing(
        tmp_path,
        min_cases=1,
        cases=[{"source": "missing/repo", "source_path": ".retort/cache/github/missing/repo", "family": "python_pr_agent"}],
    )

    assert result["status"] == "blocked"
    assert result["summary"]["ready_case_count"] == 0
    assert result["cases"][0]["blocker"] == "cached_external_source_missing"


def test_service_exposes_external_merge_landing(tmp_path: Path) -> None:
    cache = tmp_path / ".retort" / "cache" / "github" / "owner" / "agent"
    cache.mkdir(parents=True)
    (cache / "README.md").write_text("agent", encoding="utf-8")

    result = RetortService().external_merge_landing(
        {
            "project": str(tmp_path),
            "min_cases": 1,
            "cases": [{"source": "owner/agent", "source_path": ".retort/cache/github/owner/agent", "family": "python_pr_agent"}],
        }
    )

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] == 1


def test_external_merge_landing_cli_outputs_contract(tmp_path: Path) -> None:
    cache = tmp_path / ".retort" / "cache" / "github" / "qodo-ai" / "pr-agent"
    cache.mkdir(parents=True)
    (cache / "README.md").write_text("agent", encoding="utf-8")
    second = tmp_path / ".retort" / "cache" / "github" / "mopemope" / "pr-ai-review-bot"
    second.mkdir(parents=True)
    (second / "action.yml").write_text("bot", encoding="utf-8")
    output = tmp_path / "docs" / "retort_external_merge_landing.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "external-merge-landing",
            "--project",
            str(tmp_path),
            "--min-cases",
            "2",
            "--output",
            str(output),
            "--json",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "ready"
    assert output.is_file()
    assert validate_contract("external_merge_landing_result", payload)["valid"] is True
