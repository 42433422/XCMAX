"""Execute the required aggregate gates against success, skip, and failure states."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(
    scope="module",
    params=[
        (path, name)
        for path in ("FHD/.github/workflows/ci-cd.yml", ".github/workflows/fhd-ci-cd.yml")
        for name in ("backend-test", "frontend-test")
    ],
)
def gate(request):
    path, name = request.param
    jobs = yaml.safe_load((ROOT / path).read_text())["jobs"]
    job = jobs[name]
    assert job["if"] == "${{ !cancelled() }}"
    return job["steps"][0]["run"]


def run_gate(gate, **changes):
    env = {
        **os.environ,
        "GUARD": "success",
        "SSOT": "success",
        "CLASSIFY": "success",
        "VALID": "true",
        "SOURCE_SHA": "a" * 40,
        "EXPECTED_SOURCE_SHA": "a" * 40,
        "QUALITY": "success",
        "SHARDS": "success",
        "AGENT_TRANSACTIONS": "success",
        "SHOULD_RUN": "true",
        "SKIP": "false",
        **changes,
    }
    return subprocess.run(["bash", "-c", gate], env=env, capture_output=True).returncode


def test_gate_accepts_complete_execution_or_explicit_irrelevance(gate):
    assert run_gate(gate) == 0
    assert run_gate(gate, SHOULD_RUN="false", SKIP="true", SHARDS="skipped") == 0


@pytest.mark.parametrize(
    "path", ["FHD/.github/workflows/ci-cd.yml", ".github/workflows/fhd-ci-cd.yml"]
)
@pytest.mark.parametrize("state", ["success", "failure", "cancelled", "skipped", "", "unknown"])
@pytest.mark.parametrize("irrelevant", [False, True])
def test_backend_gate_requires_joint_transaction_evidence(path, state, irrelevant):
    jobs = yaml.safe_load((ROOT / path).read_text())["jobs"]
    job = jobs["backend-test"]
    assert "agent-postgres-transactions" in job["needs"]
    prerequisite = job["steps"][0]
    assert (
        prerequisite["env"]["AGENT_TRANSACTIONS"]
        == "${{ needs.agent-postgres-transactions.result }}"
    )
    changes = {"AGENT_TRANSACTIONS": state}
    if irrelevant:
        changes.update(SHOULD_RUN="false", SKIP="true", SHARDS="skipped")
    assert (run_gate(prerequisite["run"], **changes) == 0) == (state == "success")


@pytest.mark.parametrize(
    "changes",
    [
        {"CLASSIFY": "failure"},
        {"CLASSIFY": "cancelled"},
        {"CLASSIFY": "skipped"},
        {"VALID": ""},
        {"VALID": "false"},
        {"SOURCE_SHA": "b" * 40},
        {"SOURCE_SHA": "", "EXPECTED_SOURCE_SHA": ""},
        {"QUALITY": "failure"},
        {"QUALITY": "cancelled"},
        {"QUALITY": "skipped"},
        {"SHARDS": "failure"},
        {"SHARDS": "cancelled"},
        {"SHARDS": "skipped"},
        {"SKIP": ""},
        {"SKIP": "unknown"},
        {"SKIP": "true"},
        {"SHOULD_RUN": "", "SKIP": "true", "SHARDS": "skipped"},
        {"SHOULD_RUN": "unknown", "SKIP": "true", "SHARDS": "skipped"},
        {"SHOULD_RUN": "true", "SKIP": "true", "SHARDS": "skipped"},
        {"SHOULD_RUN": "false", "SKIP": "false"},
        {"SKIP": "true", "SHARDS": "skipped", "QUALITY": "failure"},
    ],
)
def test_gate_rejects_incomplete_or_inconsistent_evidence(gate, changes):
    assert run_gate(gate, **changes) != 0


def test_parallel_work_keeps_cheap_guards_and_publish_dependencies():
    jobs = yaml.safe_load((ROOT / ".github/workflows/fhd-ci-cd.yml").read_text())["jobs"]
    # A superseded PR must release its concurrency slot; step artifact uploads remain unconditional.
    assert not any("always()" in job.get("if", "") for job in jobs.values())
    prerequisites = {"classify", "guard-temp-scripts"}
    for name in (
        "backend-quality",
        "backend-test-shard",
        "frontend-quality",
        "frontend-test-shard",
        "frontend-e2e",
        "pack-verify",
    ):
        assert set(jobs[name]["needs"]) == prerequisites
    assert set(jobs["container-scan"]["needs"]) == {"classify", "pack-verify"}
    assert {
        "backend-test",
        "frontend-test",
        "frontend-e2e",
        "security-scan",
        "container-scan",
    } <= set(jobs["docker-build-fhd-api"]["needs"])
    for name in ("backend-test", "frontend-test"):
        assert {"guard-temp-scripts", "ssot-drift-gate"} <= set(jobs[name]["needs"])
        assert not jobs[name].get("continue-on-error", False)
        prerequisite = jobs[name]["steps"][0]
        assert prerequisite["env"]["GUARD"] == "${{ needs.guard-temp-scripts.result }}"
        assert prerequisite["env"]["SSOT"] == "${{ needs.ssot-drift-gate.result }}"
        assert prerequisite["working-directory"] == "."
        assert (
            prerequisite["env"]["EXPECTED_SOURCE_SHA"] == "${{ inputs.release_sha || github.sha }}"
        )


@pytest.mark.parametrize("guard", ["GUARD", "SSOT"])
@pytest.mark.parametrize("state", ["failure", "cancelled", "skipped", "", "unknown"])
@pytest.mark.parametrize("irrelevant", [False, True])
def test_parallel_guard_must_pass_even_when_suite_is_irrelevant(gate, guard, state, irrelevant):
    changes = {guard: state}
    if irrelevant:
        changes.update(SHOULD_RUN="false", SKIP="true", SHARDS="skipped")
    assert run_gate(gate, **changes) != 0


@pytest.mark.parametrize(
    "path",
    ["FHD/.github/workflows/browser-runtime.yml", ".github/workflows/fhd-browser-runtime.yml"],
)
@pytest.mark.parametrize(
    "problem", [None, "missing-agent", "missing-computer", "skipped", "failure"]
)
def test_browser_gate_requires_both_real_adapters(tmp_path, path, problem):
    jobs = yaml.safe_load((ROOT / path).read_text())["jobs"]
    step = next(
        step
        for step in jobs["browser-runtime-e2e"]["steps"]
        if step.get("name") == "Reject missing, skipped or failing browser evidence"
    )
    names = [
        "test_form_receipt_upload_and_durable_download",
        "test_context_isolation_between_runs",
        "test_screenshot_masks_embedded_frame_rectangle[agent]",
        "test_screenshot_masks_embedded_frame_rectangle[computer]",
        "test_browser_executes_under_default_tool_worker_resource_limits",
    ]
    if problem and problem.startswith("missing-"):
        names.remove(f"test_screenshot_masks_embedded_frame_rectangle[{problem[8:]}]")
    suite = ET.Element("testsuite")
    for name in names:
        case = ET.SubElement(suite, "testcase", name=name)
        if name.endswith("[computer]") and problem in {"skipped", "failure"}:
            ET.SubElement(case, problem)
    directory = tmp_path / "browser-runtime"
    directory.mkdir()
    ET.ElementTree(suite).write(directory / "results.xml")
    result = subprocess.run(
        [sys.executable, "-c", step["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
    )
    assert (result.returncode == 0) == (problem is None), result.stderr.decode()
