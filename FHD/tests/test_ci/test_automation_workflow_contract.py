"""Execute cross-workflow source guards, including delayed post-merge dispatches."""

import json
import os
import re
import shutil
import subprocess
import sys
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
    assert "delivery_request_id" in data["on"]["workflow_dispatch"]["inputs"]
    assert data["run-name"] == (
        "CI - Backend Python ${{ inputs.release_sha || github.sha }}"
        "${{ inputs.delivery_request_id && format(' [delivery:{0}]', inputs.delivery_request_id) || '' }}"
    )
    for job in data["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["ref"] == "${{ inputs.release_sha || github.sha }}"


@pytest.mark.parametrize(
    "path,job,name,sha_env",
    [
        (
            "成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml",
            "release-gate",
            "Validate dispatched main commit",
            "RELEASE_SHA",
        ),
        (
            "FHD/.github/workflows/ci-cd.yml",
            "docker-build-fhd-api",
            "Require exact main source before privileged build",
            "XCAGI_RELEASE_SHA",
        ),
        (
            "FHD/.github/workflows/mod-auto-publish.yml",
            "prepare",
            "Require exact main source before loading publication code",
            "SOURCE_SHA",
        ),
    ],
)
def test_dispatched_release_guard_rejects_unmerged_branch(tmp_path, path, job, name, sha_env):
    data = workflow(path)
    step = next(s for s in data["jobs"][job]["steps"] if s.get("name") == name)

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
            env={**os.environ, sha_env: sha},
            capture_output=True,
        ).returncode

    assert validate(base) == 0
    git("checkout", "-b", "candidate")
    git("commit", "--allow-empty", "-m", "candidate")
    assert validate(git("rev-parse", "HEAD")) != 0
    assert validate("main") != 0


def test_pr_jobs_do_not_inherit_repository_write_defaults():
    privileged = set()
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        data = workflow(str(path.relative_to(ROOT)))
        if not isinstance(data.get("on"), dict) or "pull_request" not in data["on"]:
            continue
        for name, job in data["jobs"].items():
            effective = job.get("permissions", data.get("permissions"))
            assert isinstance(effective, dict), (path.name, name, effective)
            assert effective.get("contents") != "write", (path.name, name)
            if "write" in effective.values() or re.search(
                r"\$\{\{[^}]*\bsecrets\.", json.dumps(job)
            ):
                privileged.add((path.name, name))
    # Exhaustive inventory: a new privileged PR-capable job needs a trust review.
    assert privileged == {
        ("codeql.yml", "analyze"),
        ("desktop-macos-smoke.yml", "macos-deliverable-build"),
        ("desktop-security-scan.yml", "upload-security-report"),
        ("fhd-ai-review.yml", "review"),
        ("fhd-ci-cd.yml", "docker-build-fhd-api"),
        ("fhd-ci-cd.yml", "cvm-push-release"),
        ("fhd-mod-auto-publish.yml", "prepare"),
        ("fhd-mod-auto-publish.yml", "package-and-publish"),
    }


def test_candidate_execution_and_publication_have_separate_credentials():
    ci = workflow(".github/workflows/fhd-ci-cd.yml")
    candidate = ci["jobs"]["docker-build-fhd-api-pr"]
    assert candidate["permissions"] == {"contents": "read"}
    assert "!(github.ref == 'refs/heads/main'" in candidate["if"]
    assert "secrets." not in json.dumps(candidate)
    build = next(s for s in candidate["steps"] if s.get("uses", "").startswith("docker/build-push"))
    assert build["with"]["push"] == "false"
    published = ci["jobs"]["docker-build-fhd-api"]
    assert "github.event_name != 'pull_request'" in published["if"]
    assert "github.ref == 'refs/heads/main'" in published["if"]

    desktop = workflow(".github/workflows/desktop-security-scan.yml")
    scanner = desktop["jobs"]["electronegativity-scan"]
    assert scanner.get("permissions", desktop["permissions"]) == {"contents": "read"}
    uploader = desktop["jobs"]["upload-security-report"]
    assert uploader["needs"] == "electronegativity-scan"
    assert "github.ref == 'refs/heads/main'" in uploader["if"]
    assert not any(
        "run" in step or "checkout@" in step.get("uses", "") for step in uploader["steps"]
    )


def test_privileged_review_and_scan_load_only_the_protected_controller():
    review_workflow = workflow(".github/workflows/fhd-ai-review.yml")
    assert review_workflow["on"]["pull_request"]["branches"] == ["main"]
    review = review_workflow["jobs"]["review"]
    assert "github.event.pull_request.base.ref == 'main'" in review["if"]
    checkouts = [
        s["with"] for s in review["steps"] if s.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1
    assert checkouts[0]["ref"] == "${{ github.event.pull_request.base.sha || github.sha }}"
    assert checkouts[0]["persist-credentials"] == "false"
    assert "github.ref == 'refs/heads/main'" in review["if"]
    # A candidate-controlled cache must not become executable reviewer dependencies.
    assert not any("cache" in s.get("with", {}) for s in review["steps"])

    scan = workflow(".github/workflows/codeql.yml")["jobs"]["analyze"]
    checkouts = {
        s["with"]["path"]: s["with"]
        for s in scan["steps"]
        if s.get("uses", "").startswith("actions/checkout@")
    }
    assert (
        checkouts["controller"]["ref"] == "${{ github.event.pull_request.base.sha || github.sha }}"
    )
    assert checkouts["candidate"]["ref"] == "${{ github.sha }}"
    init = next(
        s["with"]
        for s in scan["steps"]
        if s.get("uses", "").startswith("github/codeql-action/init@")
    )
    assert init["build-mode"] == "none"
    assert init["source-root"] == "candidate"
    assert init["config-file"].startswith("./controller/")


@pytest.mark.parametrize(
    "candidate,published,passed",
    [
        ("success", "skipped", True),
        ("skipped", "success", True),
        ("skipped", "skipped", False),
        ("failure", "skipped", False),
        ("cancelled", "skipped", False),
        ("skipped", "failure", False),
        ("skipped", "cancelled", False),
        ("success", "failure", False),
        ("success", "success", False),
        ("", "skipped", False),
    ],
)
def test_required_image_context_requires_real_success(tmp_path, candidate, published, passed):
    jobs = workflow(".github/workflows/fhd-ci-cd.yml")["jobs"]
    gate = jobs["docker-build-fhd-api-check"]
    assert gate["name"] == "docker-build-fhd-api"
    assert gate["if"] == (
        "${{ !cancelled() && github.event_name != 'schedule' "
        "&& needs.backend-test.outputs.skip != 'true' }}"
    )
    assert gate["permissions"] == {}
    assert jobs["docker-build-fhd-api"]["name"] != gate["name"]
    assert jobs["docker-build-fhd-api-pr"]["name"] != gate["name"]
    assert gate["steps"][0]["working-directory"] == "."
    result = subprocess.run(
        ["bash", "-c", gate["steps"][0]["run"]],
        cwd=tmp_path / gate["steps"][0]["working-directory"],
        env={**os.environ, "CANDIDATE_RESULT": candidate, "PUBLISH_RESULT": published},
        capture_output=True,
    )
    assert (result.returncode == 0) is passed


def test_poisoned_candidate_reviewer_and_imports_do_not_receive_review_identity(tmp_path):
    source = tmp_path / "source"
    files = ("scripts/ci/ai_review.py", "app/utils/operational_errors.py")
    for name in files:
        target = source / "FHD" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "FHD" / name, target)
    (source / "FHD/app/__init__.py").touch()

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=source, text=True, stderr=subprocess.DEVNULL
        ).strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Workflow isolation test")
    git("config", "user.email", "test@example.invalid")
    git("add", ".")
    git("commit", "-m", "protected reviewer")
    base = git("rev-parse", "HEAD")
    for name in files:
        (source / "FHD" / name).write_text(
            "from pathlib import Path\nPath('poison-executed').touch()\nraise RuntimeError('candidate reviewer executed')\n"
        )
    git("commit", "-am", "candidate attempts reviewer and import replacement")
    head = git("rev-parse", "HEAD")
    job = workflow(".github/workflows/fhd-ai-review.yml")["jobs"]["review"]
    checkout = next(
        s["with"] for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["ref"] == "${{ github.event.pull_request.base.sha || github.sha }}"
    git("worktree", "add", "--detach", str(tmp_path / "reviewer"), base)
    step = next(s for s in job["steps"] if s.get("name") == "Run ai-review")
    command = step["run"].strip().replace("${{ github.event.pull_request.head.sha }}", head)
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path / "reviewer" / step["working-directory"],
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "PYTHONPATH": ".",
            # Stop before the first HTTP request, after the reviewer imports.
            "PR_NUMBER": "",
            "GITHUB_EVENT_PATH": str(tmp_path / "no-event"),
            "GITHUB_TOKEN": "test-review-identity",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stderr
    assert "no PR number provided" in result.stdout
    assert not list(tmp_path.rglob("poison-executed"))


def test_poisoned_candidate_classifier_is_never_executed_by_codeql(tmp_path):
    controller = tmp_path / "controller"
    (controller / "scripts/dev").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "scripts/dev/change_classifier.py", controller / "scripts/dev/change_classifier.py"
    )

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=controller, text=True, stderr=subprocess.DEVNULL
        ).strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Workflow isolation test")
    git("config", "user.email", "test@example.invalid")
    git("add", ".")
    git("commit", "-m", "trusted controller")
    base = git("rev-parse", "HEAD")
    poison = "from pathlib import Path\nPath('poison-executed').write_text('candidate')\n"
    (controller / "scripts/dev/change_classifier.py").write_text(poison)
    git("commit", "-am", "untrusted candidate controller")
    head = git("rev-parse", "HEAD")
    git("worktree", "add", "--detach", str(tmp_path / "candidate"), head)
    git("checkout", "--detach", base)
    scan = workflow(".github/workflows/codeql.yml")["jobs"]["analyze"]
    step = next(s for s in scan["steps"] if s.get("id") == "paths")
    command = step["run"].replace(
        "${{ matrix.language == 'python' && 'codeql_python' || 'codeql_javascript' }}",
        "codeql_python",
    )
    command = command.replace("${{ github.event.pull_request.base.sha }}", base).replace(
        "${{ github.event.pull_request.head.sha }}", head
    )
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path / step["working-directory"],
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "run=true" in output.read_text()
    assert not list(tmp_path.rglob("poison-executed"))


def test_codeql_filter_uses_candidate_semantics_without_loading_its_script(tmp_path):
    trusted = tmp_path / "controller/.github/codeql"
    trusted.mkdir(parents=True)
    shutil.copyfile(
        ROOT / ".github/codeql/strip_elt_dir_fd_path_injection_fps.py",
        trusted / "strip_elt_dir_fd_path_injection_fps.py",
    )
    candidate = tmp_path / "candidate"
    poison = candidate / ".github/codeql/strip_elt_dir_fd_path_injection_fps.py"
    poison.parent.mkdir(parents=True)
    poison.write_text("raise RuntimeError('candidate filter executed')\n")
    source = "FHD/app/application/shipment_excel_elt_security.py"
    changed = candidate / source
    changed.parent.mkdir(parents=True)
    changed.write_text("# The candidate removed the reviewed ownership and traversal guards.\n")
    finding = {
        "ruleId": "py/path-injection",
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": source},
                    "region": {"startLine": 459},
                }
            }
        ],
    }
    report = tmp_path / "codeql-sarif-out/python.sarif"
    report.parent.mkdir()
    report.write_text(json.dumps({"runs": [{"results": [finding]}]}))
    step = next(
        s
        for s in workflow(".github/workflows/codeql.yml")["jobs"]["analyze"]["steps"]
        if s.get("name", "").startswith("Strip known-safe")
    )
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text())["runs"][0]["results"] == [finding]
