"""Protect PR deduplication without dropping main, tag, or scheduled evidence."""

import ast
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from tests.test_dev.test_publish_ci_workflows import publisher

ROOT = Path(__file__).resolve().parents[3]
DUPLICATE_SOURCES = (
    "FHD/.github/workflows/ci-mobile-flutter.yml",
    "FHD/.github/workflows/ci-mobile-android-smoke.yml",
    "成都修茈科技有限公司/MODstore_deploy/.github/workflows/market-e2e.yml",
    ".github/workflows/retort-engine.yml",
)
PR_LANES = DUPLICATE_SOURCES + (
    ".github/workflows/gitleaks.yml",
    ".github/workflows/fhd-alembic-ssot.yml",
    ".github/workflows/dr-resilience-ci.yml",
    ".github/workflows/guard-guards.yml",
    ".github/workflows/media-assets.yml",
    ".github/workflows/e2e.yml",
    "FHD/.github/workflows/release-gate-ci.yml",
    "FHD/.github/workflows/slo-promql-tests.yml",
    "FHD/.github/workflows/changelog-gate.yml",
    "FHD/.github/workflows/mac-control-contract.yml",
    "成都修茈科技有限公司/.github/workflows/ci-runtime-artifacts-guard.yml",
)


def workflow(source, published=True):
    path = ROOT / source
    render = None
    if source.startswith("FHD/"):
        render = publisher._render_fhd
    elif source.startswith("成都修茈科技有限公司/MODstore_deploy/"):
        render = publisher._render_mod
    elif source.startswith("成都修茈科技有限公司/"):
        render = publisher._render_corp
    name, text = render(path) if published and render else (path.name, path.read_text())
    return name, yaml.load(text, Loader=yaml.BaseLoader)


@pytest.mark.parametrize("source", DUPLICATE_SOURCES)
@pytest.mark.parametrize("published", [False, True])
def test_feature_push_is_removed_while_pr_main_and_tag_evidence_remain(source, published):
    _, doc = workflow(source, published)
    events = doc["on"]
    assert set(events["push"]["branches"]) == {"main", "develop", "master"}
    assert events["push"]["tags"] == ["**"]
    assert not events["pull_request"].get("branches")
    assert events["pull_request"]["paths"] == events["push"]["paths"]


@pytest.mark.parametrize("source", DUPLICATE_SOURCES)
def test_ci_source_and_published_workflow_changes_both_run_the_component(source):
    name, doc = workflow(source)
    paths = doc["on"]["pull_request"]["paths"]
    assert source in paths
    assert f".github/workflows/{name}" in paths
    if source != ".github/workflows/retort-engine.yml":
        assert "scripts/dev/publish_ci_workflows_to_root.py" in paths


@pytest.mark.parametrize("source", PR_LANES)
@pytest.mark.parametrize("published", [False, True])
def test_only_superseded_runs_of_the_same_pr_are_cancelled(source, published):
    _, doc = workflow(source, published)
    assert "pull_request" in doc["on"]
    assert doc["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}",
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }


@pytest.mark.parametrize("published", [False, True])
def test_ai_review_keeps_pr_and_manual_run_groups_separate(published):
    _, doc = workflow("FHD/.github/workflows/ai-review.yml", published)
    assert set(doc["on"]) == {"pull_request", "workflow_dispatch"}
    assert doc["concurrency"] == {
        "group": (
            "ai-review-${{ github.event_name == 'pull_request' && "
            "format('pr-{0}', github.event.pull_request.number) || "
            "format('run-{0}', github.run_id) }}"
        ),
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
    assert doc["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_global_secret_gate_and_scheduled_mobile_acceptance_remain():
    _, secrets = workflow(".github/workflows/gitleaks.yml")
    assert "paths" not in secrets["on"]["pull_request"]
    assert "gitleaks" in secrets["jobs"]
    _, android = workflow(DUPLICATE_SOURCES[1])
    assert android["on"]["schedule"]
    assert "workflow_dispatch" in android["on"]
    assert "FHD/scripts/ci/android_smoke.sh" in android["on"]["pull_request"]["paths"]
    _, flutter = workflow(DUPLICATE_SOURCES[0])
    assert "workflow_dispatch" in flutter["on"]
    _, retort = workflow(DUPLICATE_SOURCES[3])
    assert "FHD/packages/xcagi_langgraph_*/**" in retort["on"]["pull_request"]["paths"]


def test_real_browser_gate_covers_its_reusable_workflow_and_python_inputs():
    _, doc = workflow(".github/workflows/e2e.yml")
    events = doc["on"]
    assert events["push"]["paths"] == events["pull_request"]["paths"]
    assert {
        ".github/workflows/e2e.yml",
        ".github/workflows/e2e-playwright-reusable.yml",
        "FHD/scripts/dev/e2e-full.sh",
        "FHD/scripts/dev/e2e_supervise.py",
        "FHD/scripts/dev/check_requirements_lock.py",
        "FHD/requirements-server-api.txt",
        "FHD/ops/deploy/requirements*.txt",
        "FHD/uv.lock",
        "FHD/pyproject.toml",
        "FHD/packages/xcagi_langgraph_*/**",
    } <= set(events["pull_request"]["paths"])
    assert events["schedule"] and "workflow_dispatch" in events


def test_runtime_contract_keeps_native_and_scheduled_coverage():
    _, doc = workflow("FHD/.github/workflows/mac-control-contract.yml")
    steps = doc["jobs"]["classify"]["steps"]
    assert steps[0]["with"]["fetch-depth"] == "1"
    assert steps[1]["env"] == {
        "PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "PR_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    assert doc["jobs"]["runtime-contract"]["if"] == "needs.classify.outputs.run != 'false'"
    assert set(doc["jobs"]["runtime-contract"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-22.04",
        "ubuntu-26.04",
        "windows-2022",
        "macos-15",
    }
    assert doc["on"]["schedule"]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing_report",
        "missing_case",
        "missing_native_report",
        "missing_native_case",
        "test_production_freezes_original_source_and_oracle_before_delivery[None]",
        "test_production_freezes_original_source_and_oracle_before_delivery[delete]",
        "test_production_freezes_original_source_and_oracle_before_delivery[replace]",
        "test_production_freezes_original_source_and_oracle_before_delivery[input]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[ready]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[missing_reference]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[changed_reference]",
        "skipped",
        "failure",
        "error",
    ],
)
def test_native_business_replay_requires_executed_original_scenarios(tmp_path, fault):
    _, doc = workflow("FHD/.github/workflows/mac-control-contract.yml")
    steps = doc["jobs"]["runtime-contract"]["steps"]
    run = next(
        step
        for step in steps
        if step.get("name") == "Verify original business replay inside the native sandbox"
    )
    guard = next(
        step
        for step in steps
        if step.get("name") == "Reject missing or skipped native business replay evidence"
    )
    assert run["if"] == "matrix.os == 'ubuntu-22.04'"
    assert "tests/test_workflow_training_replay.py" in run["run"]
    assert "tests/test_workflow_training_replay_capture.py" in run["run"]
    assert "tests/test_workflow_business_promptfoo.py" in run["run"]
    assert "always()" in guard["if"]
    required = [
        "test_real_native_employee_and_independent_file_check[csv]",
        "test_real_native_employee_and_independent_file_check[excel]",
        "test_successful_native_run_with_wrong_cells_fails_business_assertion",
        "test_native_replay_cannot_read_host_oracle_write_outside_or_use_network[seal]",
        "test_native_replay_cannot_read_host_oracle_write_outside_or_use_network[cli]",
        "test_native_replay_without_sandbox_cannot_be_verified",
        "test_production_freezes_original_source_and_oracle_before_delivery[None]",
        "test_production_freezes_original_source_and_oracle_before_delivery[delete]",
        "test_production_freezes_original_source_and_oracle_before_delivery[replace]",
        "test_production_freezes_original_source_and_oracle_before_delivery[input]",
        "test_running_delivery_reuses_its_original_optional_training_snapshot[delete]",
        "test_running_delivery_reuses_its_original_optional_training_snapshot[replace]",
        "test_running_delivery_reuses_its_original_optional_training_snapshot[disable_policy]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[ready]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[missing_reference]",
        "test_frozen_training_snapshot_still_rejects_changed_business_input[changed_reference]",
        "test_missing_training_snapshot_cannot_be_recaptured_during_delivery",
        "test_delivery_recheck_does_not_add_a_late_training_snapshot",
        "test_actual_promptfoo_excel_results_revalidate_and_seal_independent_holdout[direct]",
        "test_actual_promptfoo_excel_results_revalidate_and_seal_independent_holdout[deferred]",
        "test_timeout_reaps_worker_descendants",
        "real promptfoo uses the approved model through the official SRT proxy",
        "real promptfoo uses the approved model inside native SRT",
    ]
    # Parse the original test without importing or executing its native fixtures.
    source = ROOT / (
        "成都修茈科技有限公司/MODstore_deploy/tests/test_workflow_training_replay_capture.py"
    )
    parameters = {
        "test_production_freezes_original_source_and_oracle_before_delivery": "reference_change",
        "test_frozen_training_snapshot_still_rejects_changed_business_input": "capture_state",
    }
    for test_name, parameter in parameters.items():
        original = next(
            node
            for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.FunctionDef) and node.name == test_name
        )
        marker = next(
            node
            for node in original.decorator_list
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "pytest.mark.parametrize"
        )
        assert ast.literal_eval(marker.args[0]) == parameter
        assert {f"{test_name}[{state}]" for state in ast.literal_eval(marker.args[1])} == {
            name for name in required if name.startswith(test_name + "[")
        }
    suites = {
        name: ET.Element("testsuite")
        for name in ("native-business-replay.xml", "native-trainer.xml")
    }
    for index, name in enumerate(required):
        if (
            fault == "missing_case"
            and index == 0
            or fault == "missing_native_case"
            and index == len(required) - 1
            or fault == name
        ):
            continue
        report = (
            "native-trainer.xml"
            if name.startswith("real promptfoo ")
            else "native-business-replay.xml"
        )
        case = ET.SubElement(suites[report], "testcase", name=name)
        if fault in {"skipped", "failure", "error"}:
            ET.SubElement(case, fault)
    if fault != "missing_report":
        ET.ElementTree(suites["native-business-replay.xml"]).write(
            tmp_path / "native-business-replay.xml"
        )
    if fault != "missing_native_report":
        ET.ElementTree(suites["native-trainer.xml"]).write(tmp_path / "native-trainer.xml")
    result = subprocess.run(
        [sys.executable, "-c", guard["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (fault is None), result.stdout + result.stderr


def test_modstore_full_suite_keeps_native_replays_on_a_supported_host():
    _, doc = workflow(
        "成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml"
    )
    job = doc["jobs"]["modstore-backend-test"]
    assert job["runs-on"] == "ubuntu-22.04"
    install = next(
        step
        for step in job["steps"]
        if step.get("name") == "Install the pinned experiment evaluator"
    )
    assert "bubblewrap socat ripgrep" in install["run"]
    assert "PROMPTFOO_SANDBOX_ENTRY=" in install["run"]
    tests = next(
        step for step in job["steps"] if step.get("name", "").startswith("Run tests with coverage")
    )
    assert "python -m pytest tests/ -v" in tests["run"]
    assert "--ignore" not in tests["run"] and " -m " not in tests["run"].replace(
        "python -m ", "python "
    )


@pytest.mark.parametrize(
    "changed_path,fetchable,expected",
    [
        ("docs/runtime.md", True, "false"),
        ("FHD/scripts/autonomy/runtime_tools/worker.mjs", True, "true"),
        ("docs/runtime.md", False, "true"),
    ],
)
def test_runtime_selection_fetches_exact_revisions_from_a_shallow_checkout(
    tmp_path, changed_path, fetchable, expected
):
    origin = tmp_path / "origin"
    origin.mkdir()

    def git(*args, cwd=origin):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "CI fixture")
    git("config", "user.email", "ci@example.invalid")
    classifier = origin / "scripts/dev/change_classifier.py"
    classifier.parent.mkdir(parents=True)
    classifier.write_text((ROOT / "scripts/dev/change_classifier.py").read_text())
    (origin / "FHD").mkdir()
    (origin / "FHD/README.md").write_text("fixture\n")
    changed = origin / changed_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("before\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    changed.write_text("after\n")
    git("add", ".")
    git("commit", "-qm", "head")
    head = git("rev-parse", "HEAD")
    checkout = tmp_path / "checkout"
    git("clone", "-q", "--depth=1", origin.as_uri(), str(checkout))
    missing_base = subprocess.run(
        ["git", "cat-file", "-e", base], cwd=checkout, capture_output=True
    )
    assert missing_base.returncode != 0
    _, doc = workflow("FHD/.github/workflows/mac-control-contract.yml")
    output = tmp_path / "outputs"
    result = subprocess.run(
        ["bash", "-eu", "-c", doc["jobs"]["classify"]["steps"][1]["run"]],
        cwd=checkout / "FHD",
        env={
            **os.environ,
            "PR_BASE_SHA": base if fetchable else "a" * 40,
            "PR_HEAD_SHA": head,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"run={expected}" in output.read_text().splitlines()
