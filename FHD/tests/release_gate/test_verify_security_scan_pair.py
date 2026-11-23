"""Release clearance = one zero-finding full scan of the exact SHA (user rule 2026-10-19 01:31 CST).

The interval/two-scan requirement is gone; SHA match, zero critical/high, zero
unresolved secrets, freshness and timestamp validity are still enforced.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "security" / "verify_security_scan_pair.py"
)
GATE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "security" / "security_release_gate.py"
)
RELEASE_SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[3]
SCAN_WORKFLOW = ROOT / "FHD/.github/workflows/security-full-scan.yml"


def _required_scanners() -> list[str]:
    spec = importlib.util.spec_from_file_location("security_release_gate", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.REQUIRED_SCANNERS)


SCANNERS = _required_scanners()


def _fresh_start() -> datetime:
    """A recent instant whose following scanner stamps stay on one UTC date."""
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(now - timedelta(minutes=5), midnight + timedelta(seconds=1))


def _write_scan(
    directory: Path,
    start: datetime,
    *,
    sha: str = RELEASE_SHA,
    findings: list[dict] | None = None,
    step: timedelta = timedelta(seconds=1),
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, scanner in enumerate(SCANNERS):
        (directory / f"{scanner}.json").write_text(
            json.dumps(
                {
                    "available": True,
                    "scanned_at": (start + step * index).isoformat(),
                    "release_sha": sha,
                    "source_sha": sha,
                    "findings": findings if index == 0 and findings else [],
                }
            )
        )


def _run(current: Path, previous: Path | None = None) -> tuple[int, dict]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--current-dir",
        str(current),
        "--release-sha",
        RELEASE_SHA,
    ]
    if previous is not None:
        cmd += ["--previous-dir", str(previous)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_single_fresh_zero_finding_scan_passes(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(current, _fresh_start())

    code, result = _run(current)

    assert code == 0
    assert result["passed"] is True
    assert result["mode"] == "single"
    assert result["blockers"] == []


def test_same_run_passed_as_previous_and_current_passes(tmp_path: Path) -> None:
    """Deploy workflows download the same run id twice into separate folders."""
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    start = _fresh_start()
    _write_scan(previous, start)
    _write_scan(current, start)

    code, result = _run(current, previous)

    assert code == 0, result
    assert result["passed"] is True
    assert not any(b.startswith(("scan_pair_gap", "scans_are_not")) for b in result["blockers"])


def test_same_directory_counts_as_single_scan(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(current, _fresh_start())

    code, result = _run(current, current)

    assert code == 0
    assert result["mode"] == "single"


def test_high_finding_still_blocks(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(
        current,
        _fresh_start(),
        findings=[{"id": "CVE-X", "severity": "high", "status": "open"}],
    )

    code, result = _run(current)

    assert code == 1
    assert any("critical_or_high:CVE-X" in b for b in result["blockers"])


def test_unresolved_secret_still_blocks(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(
        current,
        _fresh_start(),
        findings=[{"id": "leak-1", "severity": "low", "secret": True, "status": "open"}],
    )

    code, result = _run(current)

    assert code == 1
    assert any("unresolved_secret:leak-1" in b for b in result["blockers"])


def test_sha_mismatch_still_blocks(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(current, _fresh_start(), sha="b" * 40)

    code, result = _run(current)

    assert code == 1
    assert any("release_sha_mismatch" in b for b in result["blockers"])


def test_stale_current_scan_still_blocks(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _write_scan(current, datetime.now(UTC).replace(microsecond=0) - timedelta(days=3))

    code, result = _run(current)

    assert code == 1
    assert any("report_stale" in b for b in result["blockers"])


def test_extra_previous_scan_for_other_sha_blocks(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    start = _fresh_start()
    _write_scan(previous, start, sha="c" * 40)
    _write_scan(current, start)

    code, result = _run(current, previous)

    assert code == 1
    assert any(
        b.startswith("previous:") and "release_sha_mismatch" in b for b in result["blockers"]
    )


def test_scanner_stamps_spanning_utc_days_block(tmp_path: Path) -> None:
    current = tmp_path / "current"
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # stamps straddle today's UTC midnight but stay fresh
    _write_scan(current, midnight - timedelta(seconds=2), step=timedelta(seconds=1))

    code, result = _run(current)

    assert code == 1
    assert any(b.startswith("scan_timestamp_invalid") for b in result["blockers"])


def test_cli_has_no_skip_switch() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    lowered = proc.stdout.lower()
    for word in ("skip", "bypass", "override", "force"):
        assert word not in lowered


def _source_case(tmp_path, monkeypatch, *, sha=RELEASE_SHA):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("verify_security_scan_pair", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    start = _fresh_start()
    directory = tmp_path / "current"
    _write_scan(directory, start, sha=sha)
    files = {p.name: p.read_bytes() for p in directory.iterdir()}
    repo = "owner/product"
    run = {
        "id": 23,
        "head_sha": sha,
        "run_attempt": 2,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "path": ".github/workflows/fhd-security-full-scan.yml",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": repo},
        "head_repository": {"full_name": repo},
        "run_started_at": (start - timedelta(minutes=1)).isoformat(),
        "updated_at": (start + timedelta(minutes=1)).isoformat(),
    }
    artifact = {
        "id": 24,
        "name": "xcagi-security-release-reports",
        "expired": False,
        "size_in_bytes": 1024,
        "digest": "sha256:" + "b" * 64,
        "workflow_run": {"id": 23, "head_sha": sha},
        "created_at": start.isoformat(),
    }

    def api(route):
        if "/artifacts?" in route:
            return {"total_count": 1, "artifacts": [artifact]}
        if "/compare/" in route:
            return {"status": "ahead"}
        return dict(run)

    return module, directory, repo, run, artifact, api, files


def test_original_manual_scan_bytes_are_bound_to_current_attempt(tmp_path, monkeypatch):
    mod, directory, repo, run, artifact, api, files = _source_case(tmp_path, monkeypatch)
    proof = mod.verify_source(
        directory, repo, "23", RELEASE_SHA, api=api, read_archive=lambda _: files
    )
    assert proof["run_id"] == 23 and proof["run_attempt"] == 2
    assert proof["files"]["codeql.json"] == hashlib.sha256(files["codeql.json"]).hexdigest()
    (directory / "codeql.json").write_text("{}")
    with pytest.raises(ValueError, match="differs from the original"):
        mod.verify_source(directory, repo, "23", RELEASE_SHA, api=api, read_archive=lambda _: files)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event", "schedule"),
        ("head_branch", "feature"),
        ("path", ".github/workflows/untrusted.yml"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_repository", {"full_name": "fork/product"}),
    ],
)
def test_wrong_scan_origin_cannot_satisfy_release(tmp_path, monkeypatch, field, value):
    mod, directory, repo, run, artifact, api, files = _source_case(tmp_path, monkeypatch)
    run[field] = value
    with pytest.raises(ValueError):
        mod.verify_source(directory, repo, "23", RELEASE_SHA, api=api, read_archive=lambda _: files)


def test_prior_attempt_artifact_cannot_certify_successful_rerun(tmp_path, monkeypatch):
    mod, directory, repo, run, artifact, api, files = _source_case(tmp_path, monkeypatch)
    artifact["created_at"] = (
        datetime.fromisoformat(run["run_started_at"]) - timedelta(seconds=1)
    ).isoformat()
    with pytest.raises(ValueError, match="artifact/attempt mismatch"):
        mod.verify_source(directory, repo, "23", RELEASE_SHA, api=api, read_archive=lambda _: files)


def test_new_controller_needs_original_source_and_main_ancestry(tmp_path, monkeypatch):
    mod, directory, repo, run, artifact, api, files = _source_case(tmp_path, monkeypatch)
    run["head_sha"] = artifact["workflow_run"]["head_sha"] = "c" * 40
    proof = mod.verify_source(
        directory, repo, "23", RELEASE_SHA, api=api, read_archive=lambda _: files
    )
    assert proof["source_sha"] == RELEASE_SHA and proof["controller_sha"] == "c" * 40
    with pytest.raises(ValueError, match="unconfirmed"):
        mod.verify_source(
            directory,
            repo,
            "23",
            RELEASE_SHA,
            api=lambda route: {"status": "diverged"} if "/compare/" in route else api(route),
            read_archive=lambda _: files,
        )


def test_publication_workflows_require_original_security_source():
    consumers = [
        "FHD/.github/workflows/release-orchestrator.yml",
        "FHD/.github/workflows/release-desktop.yml",
        "FHD/.github/workflows/ci-cd.yml",
        "FHD/.github/workflows/windows-macalign-hotfix.yml",
        "FHD/.github/workflows/fix-mac-update-feed.yml",
        ".github/workflows/fhd-deploy.yml",
        "成都修茈科技有限公司/MODstore_deploy/.github/workflows/prod-deploy.yml",
    ]
    for path in consumers:
        workflow = yaml.safe_load((ROOT / path).read_text())
        steps = [
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if "verify_security_scan_pair.py" in step.get("run", "")
        ]
        assert len(steps) == 1, path
        command = steps[0]["run"]
        assert "--repository" in command and "--current-run-id" in command, path
        assert steps[0]["env"]["GH_TOKEN"] == "${{ github.token }}", path
        if "--previous-dir" in command:
            assert "--previous-run-id" in command, path


SECURITY_CONSUMERS = [
    ("FHD/.github/workflows/ci-cd.yml", "cvm-push-release"),
    (".github/workflows/fhd-deploy.yml", "cvm-rolling"),
    ("FHD/.github/workflows/windows-macalign-hotfix.yml", "windows"),
    ("FHD/.github/workflows/release-desktop.yml", "release-preflight"),
]


def _controller_consumer(tmp_path, monkeypatch, path, job_name):
    """Run real validators from the declared sparse controller beside an older CLI."""
    workflow = yaml.safe_load((ROOT / path).read_text())
    job = workflow["jobs"][job_name]
    step = next(row for row in job["steps"] if "verify_security_scan_pair.py" in row.get("run", ""))
    checkout = next(
        row for row in job["steps"] if row.get("with", {}).get("path") == "release-controller"
    )
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert set(checkout["with"]["sparse-checkout"].splitlines()) == {
        "FHD/scripts/security",
        "scripts/ci",
    }
    assert checkout.get("if") == step.get("if")  # Other staging/restart paths are unchanged.
    if job_name == "release-preflight":
        assert "github.ref == 'refs/heads/main'" in job["if"]
    else:
        assert step["env"]["CONTROLLER_REF"] == "${{ github.ref }}"
        assert step["env"]["CONTROLLER_SHA"] == "${{ github.sha }}"
    product_checkout = next(
        row for row in job["steps"] if row.get("uses", "").startswith("actions/checkout@")
    )
    assert "inputs.release_sha" in product_checkout["with"]["ref"]
    assert "path" not in product_checkout["with"]

    product = tmp_path / "checkout"
    security = product / "FHD/scripts/security"
    security.mkdir(parents=True)
    # Retain the real parser but the pre-provenance option surface. No scanner is stubbed.
    new_options = ("--repository", "--current-run-id", "--previous-run-id")
    legacy = (
        "\n".join(
            line
            for line in SCRIPT.read_text().splitlines()
            if not any(f'parser.add_argument("{flag}"' in line for flag in new_options)
        )
        + "\n"
    )
    (security / SCRIPT.name).write_text(legacy)
    shutil.copyfile(GATE_SCRIPT, security / GATE_SCRIPT.name)

    def freeze_checkout(checkout):
        subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "commit",
                "-qm",
                "Frozen checkout fixture",
            ],
            check=True,
        )
        return subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()

    release_sha = freeze_checkout(product)
    controller = product / "release-controller"
    for source in (SCRIPT, GATE_SCRIPT, ROOT / "scripts/ci/verify_modstore_release_approval.py"):
        destination = controller / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    controller_sha = freeze_checkout(controller)
    _, reports, repo, run, artifact, _, files = _source_case(
        tmp_path / "source", monkeypatch, sha=release_sha
    )
    for label in ("current", "previous"):
        shutil.copytree(reports, tmp_path / "security-reports" / label)
        if job_name == "release-preflight":
            shutil.copytree(reports, product / "security-reports" / label)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    raw = stream.getvalue()
    (tmp_path / "source.zip").write_bytes(raw)
    artifact.update(size_in_bytes=len(raw), digest="sha256:" + hashlib.sha256(raw).hexdigest())
    (tmp_path / "api.json").write_text(json.dumps({"run": run, "artifact": artifact}))
    binary = tmp_path / "bin"
    binary.mkdir()
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, pathlib, sys
root = pathlib.Path(os.environ['RUNNER_TEMP'])
payload = json.loads((root / 'api.json').read_text())
route = sys.argv[-1]
if route.endswith('/zip'):
    sys.stdout.buffer.write((root / 'source.zip').read_bytes())
elif '/artifacts?' in route:
    print(json.dumps({'total_count': 1, 'artifacts': [payload['artifact']]}))
elif '/actions/runs/23' in route:
    print(json.dumps(payload['run']))
else:
    raise SystemExit('Unexpected GitHub API route')
"""
    )
    gh.chmod(0o755)
    script = step["run"]
    for expression, value in {
        "github.repository": repo,
        "inputs.release_sha": release_sha,
        "inputs.security_scan_run_id": "23",
        "inputs.previous_security_scan_run_id": "23",
        "runner.temp": str(tmp_path),
    }.items():
        script = script.replace("${{ " + expression + " }}", value)
    cwd = product / step.get(
        "working-directory",
        job.get("defaults", workflow.get("defaults", {}))
        .get("run", {})
        .get("working-directory", "."),
    )
    environment = {
        **os.environ,
        "PATH": os.pathsep.join(
            (str(binary), str(Path(sys.executable).parent), os.environ["PATH"])
        ),
        "RUNNER_TEMP": str(tmp_path),
        "XCAGI_RELEASE_SHA": release_sha,
        "XCAGI_BUILD_SHA": release_sha,
        "CONTROLLER_REF": "refs/heads/main",
        "CONTROLLER_SHA": controller_sha,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": controller_sha,
    }
    legacy_result = subprocess.run(
        [
            sys.executable,
            str(security / SCRIPT.name),
            "--current-dir",
            str(reports),
            "--release-sha",
            release_sha,
            "--repository",
            repo,
            "--current-run-id",
            "23",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert legacy_result.returncode == 2 and "unrecognized arguments" in legacy_result.stderr
    return script, cwd, environment, step.get("shell"), security / SCRIPT.name, legacy


@pytest.mark.parametrize("path,job", SECURITY_CONSUMERS)
def test_historical_product_checkout_uses_current_security_controller(
    tmp_path, monkeypatch, path, job
):
    script, cwd, environment, shell, legacy_path, legacy = _controller_consumer(
        tmp_path, monkeypatch, path, job
    )
    if shell == "pwsh":
        assert "$env:CONTROLLER_REF -ne 'refs/heads/main'" in script
        assert "git -C ../release-controller rev-parse HEAD" in script
        # Execute the exact Python argv on Linux; PowerShell guards are checked above.
        command = shlex.split("python " + script.split("python ", 1)[1].replace("`", ""))
        command[0] = sys.executable
    else:
        command = ["bash", "-c", script]
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["passed"] is True
    assert evidence["release_sha"] == environment["XCAGI_RELEASE_SHA"]
    assert evidence["sources"]["current"]["run_id"] == 23
    assert evidence["sources"]["current"]["run_attempt"] == 2
    assert legacy_path.read_text() == legacy


@pytest.mark.parametrize("path,job", SECURITY_CONSUMERS[:2])
@pytest.mark.parametrize(
    "field,value", [("CONTROLLER_REF", "refs/heads/feature"), ("CONTROLLER_SHA", "f" * 40)]
)
def test_security_consumer_rejects_untrusted_or_changed_controller(
    tmp_path, monkeypatch, path, job, field, value
):
    script, cwd, environment, *_ = _controller_consumer(tmp_path, monkeypatch, path, job)
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env={**environment, field: value},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not result.stdout  # The report producer was never entered.


@pytest.mark.parametrize(
    "field,value",
    [
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_SHA", "f" * 40),
        ("XCAGI_BUILD_SHA", "e" * 40),
    ],
)
def test_formal_security_preflight_binds_both_checkouts(tmp_path, monkeypatch, field, value):
    script, cwd, environment, *_ = _controller_consumer(
        tmp_path, monkeypatch, "FHD/.github/workflows/release-desktop.yml", "release-preflight"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env={**environment, field: value},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not result.stdout


def _run_scan_gate(tmp_path: Path, *, event: str = "workflow_dispatch") -> tuple[int, dict]:
    """Run the actual workflow command with real validators and synthetic reports."""
    checkout = tmp_path / "checkout"
    (checkout / "FHD/scripts").mkdir(parents=True, exist_ok=True)
    security = checkout / "FHD/scripts/security"
    if not security.exists():
        security.symlink_to(SCRIPT.parent, target_is_directory=True)
    config = checkout / "FHD/config"
    config.mkdir(exist_ok=True)
    (config / "security_baseline.json").write_text(
        json.dumps(
            {
                "schema": "security-baseline/v1",
                "entries": [
                    {
                        "scanner": "codeql",
                        "id": "historical-high",
                        "reason": "Synthetic historical risk for trend-only regression",
                        "owner": "fixture-owner",
                        "expires": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    steps = yaml.safe_load(SCAN_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["scan-and-gate"][
        "steps"
    ]
    gate = next(step for step in steps if step.get("id") == "release-gate")
    command = gate["run"].replace("${{ steps.scan-source.outputs.sha }}", RELEASE_SHA)
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=checkout,
        env={
            **os.environ,
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_EVENT_NAME": event,
            "RUNNER_TEMP": str(tmp_path),
            "RELEASE_SHA": RELEASE_SHA,
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode, json.loads(result.stdout)


@pytest.mark.parametrize(
    "case",
    [
        "clear",
        "baselined_high",
        "cross_day",
        "source_mismatch",
        "release_mismatch",
        "unavailable",
        "missing",
        "secret",
        "stale",
    ],
)
def test_manual_scan_and_deployment_make_identical_decisions(tmp_path: Path, case: str) -> None:
    reports = tmp_path / "security-reports"
    now = datetime.now(UTC)
    _write_scan(reports, now, step=timedelta(0))
    codeql = reports / "codeql.json"
    payload = json.loads(codeql.read_text(encoding="utf-8"))
    if case in {"baselined_high", "secret"}:
        payload["findings"] = [
            {
                "id": "historical-high",
                "severity": "high",
                "status": "open",
                "secret": case == "secret",
            }
        ]
    elif case == "cross_day":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        payload["scanned_at"] = (midnight - timedelta(seconds=1)).isoformat()
    elif case in {"source_mismatch", "release_mismatch"}:
        payload["source_sha" if case == "source_mismatch" else "release_sha"] = "b" * 40
    elif case == "unavailable":
        payload["available"] = False
    elif case == "stale":
        payload["scanned_at"] = (now - timedelta(days=2)).isoformat()
    codeql.write_text(json.dumps(payload), encoding="utf-8")
    if case == "missing":
        codeql.unlink()

    scan_code, scan = _run_scan_gate(tmp_path)
    deploy_code, deploy = _run(reports)

    assert scan_code == deploy_code == (0 if case == "clear" else 1)
    assert scan["passed"] == deploy["passed"]
    assert scan["blockers"] == deploy["blockers"]
    if case == "baselined_high":
        trend_code, trend = _run_scan_gate(tmp_path, event="schedule")
        assert trend_code == 0
        assert trend["suppressed"] == {"codeql": ["historical-high"]}
