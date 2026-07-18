"""覆盖率门槛、实测、发布三层契约测试。"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.dev import coverage_ratchet

FHD_ROOT = Path(__file__).resolve().parents[2]


def test_missing_backend_measurement_fails_when_required(tmp_path):
    missing = tmp_path / "coverage.json"

    assert (
        coverage_ratchet.main(["--check", "--coverage-json", str(missing), "--require-backend"])
        == 1
    )


def test_missing_frontend_measurement_fails_when_required(tmp_path):
    missing = tmp_path / "coverage-summary.json"

    assert (
        coverage_ratchet.main(["--check", "--frontend-summary", str(missing), "--require-frontend"])
        == 1
    )


def test_registry_and_workflow_enforce_three_layer_contract():
    registry = yaml.safe_load((FHD_ROOT / "config" / "ssot.yaml").read_text(encoding="utf-8"))
    coverage = next(domain for domain in registry["domains"] if domain["name"] == "coverage")
    workflow = (FHD_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")

    assert set(coverage["truth_layers"]) == {"threshold", "measurement", "publication"}
    assert "coverage_ratchet.py --check --require-backend" in workflow
    assert "coverage_ratchet.py --check --require-frontend" in workflow
