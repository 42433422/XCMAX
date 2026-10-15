from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/mod_publish_plan.py"
SPEC = importlib.util.spec_from_file_location("mod_publish_plan", SCRIPT)
assert SPEC and SPEC.loader
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


def git(root, *args):
    return plan.run(root, "git", *args)


def write_mod(root, source, version="1.0.0"):
    directory = root / source
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps({"id": directory.name, "version": version}))
    (directory / "backend").mkdir(exist_ok=True)
    (directory / "backend/worker.py").write_text("original\n")


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Mod publication test")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    for source in (
        "FHD/mods/_employees/employee-one",
        "FHD/mods/host-one",
        "FHD/XCAGI/mods/industry-one",
    ):
        write_mod(tmp_path, source)
    git(tmp_path, "add", "FHD")
    git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


@pytest.mark.parametrize(
    "path,expected",
    [
        ("FHD/mods/_employees/worker/backend/nested/task.py", "FHD/mods/_employees/worker"),
        ("FHD/mods/bridge/frontend/pages/index.vue", "FHD/mods/bridge"),
        ("FHD/XCAGI/mods/industry/backend/routes.py", "FHD/XCAGI/mods/industry"),
        ("FHD/mods/_employees/manifest.json", None),
        ("FHD/mods/../../secrets/file", None),
        ("unrelated/FHD/mods/test/source", None),
    ],
)
def test_changed_path_uses_package_root_not_parent_of_leaf(path, expected):
    assert plan.source_root(path) == expected


def test_exact_main_ancestor_and_all_source_roots(repository):
    root = repository
    for source in (
        "FHD/mods/_employees/employee-one",
        "FHD/mods/host-one",
        "FHD/XCAGI/mods/industry-one",
    ):
        write_mod(root, source, "1.0.1")
    git(root, "add", "FHD")
    git(root, "commit", "-qm", "versioned fixes")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "commit", "--allow-empty", "-qm", "unrelated metrics")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "checkout", "--detach", sha)
    rows = plan.discover(root, sha)
    assert {row["id"] for row in rows} == {"employee-one", "host-one", "industry-one"}
    assert all(row["version"] == "1.0.1" for row in rows)
    with pytest.raises(ValueError, match="HEAD"):
        plan.discover(root, "a" * 40)


def test_source_only_change_requires_version_bump(repository):
    source = repository / "FHD/XCAGI/mods/industry-one/backend/worker.py"
    source.write_text("fixed source\n")
    git(repository, "add", "FHD")
    git(repository, "commit", "-qm", "missing version bump")
    sha = git(repository, "rev-parse", "HEAD")
    git(repository, "update-ref", "refs/remotes/origin/main", sha)
    with pytest.raises(ValueError, match="strictly higher manifest.version"):
        plan.discover(repository, sha)


def test_branch_only_source_rejected(repository):
    git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repository, "commit", "--allow-empty", "-qm", "unmerged private branch")
    with pytest.raises(subprocess.CalledProcessError):
        plan.discover(repository, git(repository, "rev-parse", "HEAD"))


def test_changed_mirror_cannot_publish_over_stale_canonical(repository):
    write_mod(repository, "FHD/XCAGI/mods/host-one")
    git(repository, "add", "FHD")
    git(repository, "commit", "-qm", "baseline mirror")
    write_mod(repository, "FHD/XCAGI/mods/host-one", "1.0.1")
    git(repository, "add", "FHD")
    git(repository, "commit", "-qm", "mirror only fix")
    sha = git(repository, "rev-parse", "HEAD")
    git(repository, "update-ref", "refs/remotes/origin/main", sha)
    with pytest.raises(ValueError, match="canonical source disagree"):
        plan.discover(repository, sha)


def test_required_checks_use_exact_sha_latest_attempt_and_expected_app():
    sha = "a" * 40
    protection = {"checks": [{"context": "test", "app_id": 1}]}
    good = {
        "id": 10,
        "name": "test",
        "head_sha": sha,
        "app": {"id": 1},
        "status": "completed",
        "conclusion": "success",
    }
    plan.verify_required_checks(protection, [{"check_runs": [good]}], [], sha)
    for bad in (
        {**good, "head_sha": "b" * 40},
        {**good, "app": {"id": 2}},
        {**good, "id": 11, "conclusion": "failure"},
        {**good, "id": 11, "status": "in_progress"},
    ):
        rows = [good, bad] if bad["id"] == 11 else [bad]
        with pytest.raises(ValueError, match="not successful"):
            plan.verify_required_checks(protection, [{"check_runs": rows}], [], sha)
    with pytest.raises(ValueError, match="no readable"):
        plan.verify_required_checks({}, [], [], sha)


def test_workflow_binds_main_source_and_does_not_cancel_other_mods(tmp_path):
    root = SCRIPT.parents[2]
    text = (root / ".github/workflows/mod-auto-publish.yml").read_text()
    workflow = yaml.safe_load(text)
    event = workflow.get("on", workflow.get(True))
    assert event["pull_request"]["branches"] == ["main"]
    assert set(event["pull_request"]["paths"]) == {"FHD/mods/**", "FHD/XCAGI/mods/**"}
    assert event["workflow_dispatch"]["inputs"]["source_sha"]["required"]
    assert "cancel-in-progress: true" not in text
    for job in workflow["jobs"].values():
        checkout = next(row for row in job["steps"] if row.get("uses") == "actions/checkout@v4")
        assert checkout["with"]["ref"] == "${{ env.SOURCE_SHA }}"
    assert '--src "$MOD_SOURCE"' in text
    assert "--wait-seconds 1800" in text
    steps = workflow["jobs"]["package-and-publish"]["steps"]
    guard = next(
        row for row in steps if row.get("name") == "Require signing configuration before building"
    )
    failed = subprocess.run(
        ["bash", "-c", guard["run"]],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode != 0
    assert "refusing unsigned publication" in failed.stdout
    assert list(tmp_path.iterdir()) == []
    assert '--sign --private-key "$key_path"' in text
    assert "build-runtime-mod-frontend.mjs" in text
