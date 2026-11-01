"""The single frontend execution retains every previous gate and report."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_dev.test_publish_ci_workflows import publisher

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "FHD/.github/workflows/ci-cd.yml"
HYGIENE = ROOT / "FHD/scripts/ci/check_repo_hygiene.sh"


@pytest.fixture(params=[False, True])
def pipeline(request):
    content = publisher._render_fhd(SOURCE)[1] if request.param else SOURCE.read_text()
    return yaml.safe_load(content)["jobs"]


@pytest.mark.parametrize("name", ["vitest", "frontend-smoke"])
@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "", "unknown"])
def test_compatibility_contexts_follow_the_verified_gate(pipeline, name, result):
    job = pipeline[name]
    assert job["needs"] == "frontend-test"
    assert job["if"] == "always()"
    assert job.get("name", name) == (
        "Vitest (173 文件 · jsdom)" if name == "vitest" else "frontend-smoke"
    )
    assert not job.get("continue-on-error", False)
    step = job["steps"][0]
    assert step["working-directory"] == "."
    assert step["env"]["FRONTEND_RESULT"] == "${{ needs.frontend-test.result }}"
    outcome = subprocess.run(
        ["bash", "-c", step["run"]],
        env={**os.environ, "FRONTEND_RESULT": result},
        capture_output=True,
    )
    assert (outcome.returncode == 0) == (result == "success")
    assert not any("npm" in item.get("run", "") for item in job["steps"])


def test_shared_quality_and_reports_preserve_unique_standalone_guards(pipeline):
    quality = pipeline["frontend-quality"]["steps"]
    assert any(step.get("run") == 'npx eslint src/ "tests/**/*.test.{js,ts}"' for step in quality)
    assert any(
        "count_frontend_coverage_stubs.py --check" in step.get("run", "") for step in quality
    )
    reports = [
        step
        for step in pipeline["frontend-test"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    junit = next(
        step for step in reports if step["with"]["name"] == "vitest-junit-${{ github.run_id }}"
    )
    assert junit["if"].startswith("always()")
    assert junit["with"]["path"] == "FHD/frontend/test-results/junit.xml"
    shard_upload = pipeline["frontend-test-shard"]["steps"][-1]
    assert shard_upload["if"] == "always()"
    assert shard_upload["with"]["path"] == "FHD/frontend/shard-evidence/"


def test_suite_and_mock_run_once_while_real_e2e_and_hygiene_remain(pipeline):
    assert not (ROOT / ".github/workflows/frontend-unit.yml").exists()
    smoke = yaml.safe_load((ROOT / "FHD/.github/workflows/test.yml").read_text())["jobs"]
    assert "frontend-smoke" not in smoke
    hygiene_step = next(step for step in smoke["repo-hygiene"]["steps"] if "run" in step)
    assert hygiene_step["run"] == "bash scripts/ci/check_repo_hygiene.sh"
    assert pipeline["frontend-smoke"]["steps"][-1]["run"] == hygiene_step["run"]
    owner = [
        step for step in pipeline["frontend-e2e"]["steps"] if "test:e2e:p0" in step.get("run", "")
    ]
    assert len(owner) == 1 and owner[0]["env"]["E2E_VITE_MOCK_API"] == "1"
    live = yaml.safe_load((ROOT / ".github/workflows/e2e-playwright-reusable.yml").read_text())[
        "jobs"
    ]["playwright"]
    assert live["name"] == "Playwright P0"
    assert not any("test:e2e:p0" in step.get("run", "") for step in live["steps"])
    actual = next(
        step for step in live["steps"] if step.get("run") == "bash ../scripts/dev/e2e-full.sh"
    )
    assert actual["env"]["E2E_FULL_STACK"] == "1"
    assert "if" not in actual and not actual.get("continue-on-error", False)
    assert "npm run build:strict" in (ROOT / "FHD/scripts/dev/e2e-full.sh").read_text()


@pytest.mark.parametrize(
    "filename",
    [
        "app/.env",
        "app/secret.yaml",
        "frontend/node_modules/pkg/index.js",
        "app/vector_data/cache.sqlite",
    ],
)
def test_shared_hygiene_still_rejects_tracked_private_or_generated_files(tmp_path, filename):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / filename
    path.parent.mkdir(parents=True)
    path.write_text("test fixture")
    subprocess.run(["git", "add", "--", filename], cwd=tmp_path, check=True)
    result = subprocess.run(["bash", str(HYGIENE)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0 and filename in result.stdout


def test_shared_hygiene_accepts_example_config_but_not_unknown_git_state(tmp_path):
    unknown = subprocess.run(["bash", str(HYGIENE)], cwd=tmp_path, capture_output=True)
    assert unknown.returncode != 0
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for filename in (
        ".env.example",
        "frontend/.env.generic",
        "frontend/.env.minimal",
        "app/main.py",
    ):
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test fixture")
        subprocess.run(["git", "add", "--", filename], cwd=tmp_path, check=True)
    assert subprocess.run(["bash", str(HYGIENE)], cwd=tmp_path, capture_output=True).returncode == 0
