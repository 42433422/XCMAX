"""Daily scanner reports must not be forged or lost behind protected main."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = (
    "FHD/.github/workflows/security-metrics-collect.yml",
    ".github/workflows/fhd-security-metrics-collect.yml",
)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_daily_reports_are_persistent_and_scanner_gate_is_not_weakened(workflow):
    data = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))
    assert data["permissions"]["contents"] == "read"
    steps = data["jobs"]["collect"]["steps"]
    export = next(s for s in steps if s.get("name") == "Export gitleaks SARIF to metrics")
    assert 'test -s "metrics/gitleaks-${SCAN_DATE}.json"' in export["run"]
    assert "Missing or invalid gitleaks SARIF" in export["run"]
    assert "Gitleaks failed but reported no findings" in export["run"]
    assert '"runs":[{"results":[]}]' not in export["run"]
    upload = next(s for s in steps if s.get("uses") == "actions/upload-artifact@v4")
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 120
    assert "${{ steps.metrics-date.outputs.date }}" in upload["with"]["path"]
    assert "${{ github.run_id }}" in upload["with"]["name"]
    assert "FHD/metrics/gitleaks-" in upload["with"]["path"]
    assert "FHD/metrics/trivy-" in upload["with"]["path"]
    assert all("git push" not in s.get("run", "") for s in steps)
    trivy = next(s for s in steps if s.get("id") == "trivy")
    assert trivy["with"]["exit-code"] == "1"
    guard = next(s for s in steps if s.get("name", "").startswith("Fail after preserving evidence"))
    assert guard["if"] == "always() && steps.trivy.outcome != 'success'"
    summary = next(s for s in steps if s.get("name") == "Verify and summarize scanner evidence")
    assert all(x in summary["run"] for x in ("CRITICAL", "HIGH", "MEDIUM"))


@pytest.mark.parametrize(
    "exit_code,report,passes",
    [
        (0, {"runs": [{"results": []}]}, True),
        (1, {"runs": [{"results": [{"ruleId": "synthetic"}]}]}, True),
        (1, {"runs": [{"results": []}]}, False),
        (125, None, False),
        (0, {"runs": "bad"}, False),
    ],
)
def test_export_rejects_missing_and_forged_empty_scans(
    tmp_path: Path, exit_code: int, report: dict | None, passes: bool
):
    data = yaml.safe_load((ROOT / WORKFLOWS[0]).read_text(encoding="utf-8"))
    script = next(
        s["run"]
        for s in data["jobs"]["collect"]["steps"]
        if s.get("name") == "Export gitleaks SARIF to metrics"
    )
    docker = tmp_path / "docker"
    stub = "#!/bin/sh\n"
    if report is not None:
        payload = json.dumps(report, separators=(",", ":"))
        stub += "mkdir -p metrics\n"
        stub += "printf '%s\\n' '" + payload + '\' > "metrics/gitleaks-$(date -u +%Y-%m-%d).json"\n'
    stub += f"exit {exit_code}\n"
    docker.write_text(stub, encoding="utf-8")
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) == passes, result.stderr.decode()
