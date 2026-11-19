"""Execute cross-workflow source guards, including delayed post-merge dispatches."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def workflow(path):
    return yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize(
    "source",
    [
        "成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml",
        ".github/workflows/modstore-ci-backend-python.yml",
    ],
)
def test_post_merge_ci_checkout_and_title_share_the_explicit_target(source):
    data = workflow(source)
    assert "release_sha" in data["on"]["workflow_dispatch"]["inputs"]
    assert data["run-name"] == "CI - Backend Python ${{ inputs.release_sha || github.sha }}"
    for job in data["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["ref"] == "${{ inputs.release_sha || github.sha }}"


def test_delayed_old_release_ci_cannot_validate_a_new_main_controller(tmp_path):
    data = workflow("FHD/.github/workflows/evolution-orchestrator.yml")
    step = next(s for s in data["jobs"]["scan-and-propose"]["steps"] if s.get("id") == "scan_scope")
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=ROOT,
        env={
            **os.environ,
            "EVENT_NAME": "workflow_run",
            "WORKFLOW_HEAD_SHA": "b" * 40,
            "WORKFLOW_RUN_TITLE": "CI/CD " + "a" * 40,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == "should_scan=false"


def test_dispatched_release_guard_rejects_unmerged_branch(tmp_path):
    data = workflow("成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml")
    step = next(
        s
        for s in data["jobs"]["release-gate"]["steps"]
        if s.get("name") == "Validate dispatched main commit"
    )

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Workflow contract test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "main")
    base = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", base)

    def validate(sha):
        return subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=tmp_path,
            env={**os.environ, "RELEASE_SHA": sha},
            capture_output=True,
        ).returncode

    assert validate(base) == 0
    git("checkout", "-b", "candidate")
    git("commit", "--allow-empty", "-m", "candidate")
    assert validate(git("rev-parse", "HEAD")) != 0
    assert validate("main") != 0
