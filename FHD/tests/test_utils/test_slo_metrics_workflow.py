from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    "case,passed",
    [
        ("merged", True),
        ("open", False),
        ("older_open", False),
        ("closed_unmerged", False),
        ("wrong_repository", False),
        ("missing_merge_sha", False),
        ("stale_checkout", False),
        ("empty_history", False),
        ("api_failure", False),
        ("wrong_branch", False),
    ],
)
def test_daily_publication_guard_executes_against_real_main_history(tmp_path, case, passed):
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / ".github/workflows/slo-metrics-collect.yml"
        ).read_text()
    )
    steps = workflow["jobs"]["collect"]["steps"]
    guard = next(
        step
        for step in steps
        if step.get("name") == "Require prior metrics publication on main before collecting"
    )
    collect_step = next(step for step in steps if step.get("id") == "slo_collect")
    publish = next(
        step for step in steps if step.get("name") == "Open metrics PR and enable auto-merge"
    )
    assert steps.index(guard) < steps.index(collect_step) < steps.index(publish)
    assert not guard.get("continue-on-error")
    assert not guard.get("if") and not collect_step.get("if") and not publish.get("if")

    checkout = tmp_path / "checkout"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=checkout,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).strip()

    git("init", "-b", "main")
    git("commit", "--allow-empty", "-m", "prior main")
    prior_sha = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "merged metrics snapshot")
    merge_sha = git("rev-parse", "HEAD")
    git("clone", "--bare", str(checkout), str(tmp_path / "origin.git"))
    git("remote", "add", "origin", str(tmp_path / "origin.git"))
    if case == "stale_checkout":
        git("checkout", "--detach", prior_sha)

    record = {
        "number": 123,
        "state": "closed",
        "created_at": "2026-11-22T01:00:00Z",
        "merged_at": "2026-11-22T01:10:00Z",
        "merge_commit_sha": merge_sha,
        "head_ref": "automation/slo-metrics-456",
        "head_repo": "42433422/XCMAX",
        "base_ref": "main",
        "base_repo": "42433422/XCMAX",
    }
    records = [record]
    if case == "open":
        record.update(state="open", merged_at=None)
    elif case == "older_open":
        records.append(
            {
                **record,
                "number": 122,
                "created_at": "2026-11-21T01:00:00Z",
                "state": "open",
                "merged_at": None,
            }
        )
    elif case == "closed_unmerged":
        record["merged_at"] = None
    elif case == "wrong_repository":
        record["head_repo"] = "unknown/XCMAX"
    elif case == "missing_merge_sha":
        record["merge_commit_sha"] = None
    elif case == "empty_history":
        records = []

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'api' and '--paginate' in args and '--jq' in args\n"
        "assert 'state=all&base=main' in args[2]\n"
        "assert 'automation/slo-metrics-' in args[-1] and '@json' in args[-1]\n"
        "if os.environ.get('FIXTURE_API_FAILURE') == '1': sys.exit(77)\n"
        "sys.stdout.write(Path(os.environ['FIXTURE_PR_HISTORY']).read_text())\n"
    )
    gh.chmod(0o755)
    history = tmp_path / "response.jsonl"
    history.write_text("".join(json.dumps(item) + "\n" for item in records))
    result = subprocess.run(
        ["bash", "-c", guard["run"]],
        cwd=checkout,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GH_TOKEN": "fixture-token",
            "GITHUB_REPOSITORY": "42433422/XCMAX",
            "GITHUB_REF_NAME": "feature" if case == "wrong_branch" else "main",
            "RUNNER_TEMP": str(tmp_path),
            "FIXTURE_PR_HISTORY": str(history),
            "FIXTURE_API_FAILURE": "1" if case == "api_failure" else "0",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is passed, result.stdout + result.stderr
    if passed:
        assert f"Verified metrics PR #123 merged at {merge_sha}" in result.stdout
