from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from tests.release_gate.test_desktop_soak_evidence import raw_report, write_bundle


def _module():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "release" / "build_closure_reports.py"
    )
    spec = importlib.util.spec_from_file_location("build_closure_reports", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_four_reports_are_redacted_hashed_and_fail_closed(tmp_path: Path) -> None:
    mod = _module()
    sha = "a" * 40
    release_id = f"xcagi-1.0.0.1-{sha}"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    convergence = _write(
        inputs / "convergence.json",
        {
            "converged": True,
            "release_sha": sha,
            "release_id": release_id,
            "sources": [{"name": "device-secret", "status": "matched"}],
            "blockers": [],
            "active_purchased_accounts": 3,
            "reported_installations": 6,
        },
    )
    security = _write(
        inputs / "security.json",
        {"passed": True, "release_sha": sha, "blockers": []},
    )
    slo = _write(
        inputs / "slo.json",
        {
            "passed": True,
            "release_id": release_id,
            "continuous_days": 90,
            "day_0": "2026-09-05",
            "day_n": "2026-12-03",
            "chain_tip": "b" * 64,
            "blockers": [],
        },
    )
    rollback = _write(
        inputs / "rollback.json",
        {
            "passed": True,
            "verification_scope": "measured_native_acceptance",
            "release_sha": sha,
            "server_rto_minutes": 20,
            "server_rpo_minutes": 3,
            "blockers": [],
        },
    )
    customer = _write(
        inputs / "customer.json",
        {
            "schema": "customer_value_evidence.v1",
            "value_ledger_ready": True,
            "three_customer_loop_verified": True,
            "complete_customer_count": 3,
            "release_sha": sha,
            "verification_scope": "native_customer_release",
            "release_binding_source": "original_workflow_and_published_desktop",
            "customers": [
                {
                    "customer_alias": f"customer-{index:012x}",
                    "enterprise_name": "must-not-leak",
                    "order_no": "must-not-leak",
                    "device_id": "must-not-leak",
                    "stages": dict.fromkeys(mod.STAGES, True),
                    "ordered": True,
                    "complete": True,
                    "gaps": [],
                }
                for index in range(3)
            ],
        },
    )
    output = tmp_path / "reports"
    soak_dir, provenance = write_bundle(inputs / "desktop_soak")

    manifest = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
        product_version="1.0.0.1",
        now=datetime(2026, 12, 3, tzinfo=UTC),
        desktop_soak_dir=soak_dir,
        provenance_path=provenance,
    )

    assert manifest["passed"] is True
    assert [row["file"] for row in manifest["reports"]] == list(mod.REPORT_FILENAMES)
    rendered = "\n".join(path.read_text() for path in output.glob("*.json"))
    assert "must-not-leak" not in rendered
    assert "device-secret" not in rendered
    for row in manifest["reports"]:
        report = output / row["file"]
        assert hashlib.sha256(report.read_bytes()).hexdigest() == row["sha256"]
        assert (output / f"{row['file']}.sha256").is_file()

    # Previous production/rollback inputs alone cannot qualify desktop stability.
    missing_soak = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
        product_version="1.0.0.1",
    )
    assert missing_soak["passed"] is False
    reliability = json.loads((output / "production-reliability-report.json").read_text())
    assert reliability["summary"]["desktop_soak_blockers"]

    original = json.loads(customer.read_text())
    for mutation in (
        {"verification_scope": "aggregate"},
        {"release_binding_source": "submitted_sha"},
        {"customers": original["customers"][:1]},
        {"customers": [original["customers"][0]] * 3},
    ):
        _write(customer, {**original, **mutation})
        refused = mod.build_reports(
            convergence_path=convergence,
            security_path=security,
            slo_path=slo,
            rollback_path=rollback,
            customer_path=customer,
            output_dir=output,
            release_sha=sha,
            product_version="1.0.0.1",
        )
        assert refused["passed"] is False
        report = json.loads((output / "customer-value-report.json").read_text())
        assert report["summary"]["blockers"]
    _write(customer, original)

    _write(security, {"passed": False, "release_sha": sha, "blockers": ["high"]})
    failed = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
        product_version="1.0.0.1",
    )
    assert failed["passed"] is False

    # A legacy PASS with no measurement scope cannot certify reliability.
    payload = json.loads(rollback.read_text())
    del payload["verification_scope"]
    _write(rollback, payload)
    failed = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
        product_version="1.0.0.1",
    )
    reliability = json.loads((output / "production-reliability-report.json").read_text())
    assert reliability["passed"] is False
    assert reliability["summary"]["upgrade_rollback_scope"] == "unverified"


def _actions_fixture(mod, *, member="release-convergence.json"):
    """Use real ZIP bytes while replacing only the external GitHub transport."""
    repo, controller = "42433422/XCMAX", "b" * 40
    records, run_ids, archives = {}, {}, {}
    for number, (label, (workflow, name)) in enumerate(mod.SOURCE_WORKFLOWS.items(), 1):
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as archive:
            archive.writestr(member, json.dumps({"release_sha": "a" * 40}))
            if label == "desktop_soak":
                for platform in ("windows", "macos"):
                    archive.writestr(f"{platform}.json", json.dumps(raw_report(platform)))
        raw = blob.getvalue()
        run = {
            "id": number,
            "run_attempt": 2,
            "head_sha": controller,
            "repository": {"full_name": repo},
            "head_repository": {"full_name": repo},
            "path": ".github/workflows/" + workflow,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-11-22T23:58:00Z",
            "updated_at": "2026-11-23T08:10:00Z",
        }
        artifact = {
            "id": number + 10,
            "name": name,
            "expired": False,
            "size_in_bytes": len(raw),
            "workflow_run": {"id": number, "head_sha": controller},
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "created_at": "2026-11-23T08:05:00Z",
        }
        route = f"repos/{repo}/actions/runs/{number}"
        records[route] = run
        records[route + "/attempts/2"] = dict(run)
        records[route + "/artifacts?per_page=100&page=1"] = {
            "total_count": 1,
            "artifacts": [artifact],
        }
        if label == "desktop_soak":
            records[route + "/attempts/2/jobs?per_page=100&page=1"] = {
                "total_count": 2,
                "jobs": [
                    {
                        "id": 50 + index,
                        "name": f"Desktop soak ({platform})",
                        "run_id": number,
                        "head_sha": controller,
                        "status": "completed",
                        "conclusion": "success",
                        "runner_id": index,
                        "runner_name": f"fixture-{platform}",
                        "labels": ["self-hosted", "xcagi-physical", platform],
                        "started_at": "2026-11-22T23:59:00Z",
                        "completed_at": "2026-11-23T08:03:00Z",
                    }
                    for index, platform in enumerate(("windows", "macos"), 1)
                ],
            }
        archives[f"repos/{repo}/actions/artifacts/{number + 10}/zip"] = raw
        run_ids[label] = str(number)

    def download(path, destination):
        destination.write_bytes(archives[path])

    def collect(directory, **kwargs):
        return mod.collect_sources(
            repository=repo,
            release_sha="a" * 40,
            runs=run_ids,
            output_dir=directory,
            api=kwargs.pop("api", records.__getitem__),
            download=kwargs.pop("download", download),
            ancestor=lambda sha: sha in {"a" * 40, controller},
            **kwargs,
        )

    return records, collect


def test_original_workflow_attempt_and_archive_bytes_are_read_back(tmp_path):
    mod = _module()
    _, collect = _actions_fixture(mod)
    proof = collect(tmp_path / "sources")
    assert proof["release_sha"] == "a" * 40
    assert proof["sources"]["convergence"]["controller_sha"] == "b" * 40
    assert proof["sources"]["convergence"]["run_attempt"] == 2
    assert (tmp_path / "sources/convergence/release-convergence.json").is_file()
    assert json.loads((tmp_path / "sources/provenance.json").read_text()) == proof
    source = proof["sources"]["desktop_soak"]
    assert (
        source["native_jobs"]["windows"]["runner_id"] != source["native_jobs"]["macos"]["runner_id"]
    )
    assert (
        source["reports"]["windows"]
        == hashlib.sha256((tmp_path / "sources/desktop_soak/windows.json").read_bytes()).hexdigest()
    )
    assert (
        mod.verify_bundle(
            tmp_path / "sources/desktop_soak",
            release_sha="a" * 40,
            product_version="1.0.0.1",
            provenance=proof,
        )["passed"]
        is True
    )


@pytest.mark.parametrize(
    "fault", ["hosted", "missing_platform", "failed", "prior_attempt", "different_commit"]
)
def test_desktop_sources_require_current_successful_registered_device_jobs(tmp_path, fault):
    mod = _module()
    records, collect = _actions_fixture(mod)
    listing = records["repos/42433422/XCMAX/actions/runs/5/attempts/2/jobs?per_page=100&page=1"]
    row = listing["jobs"][0]
    if fault == "hosted":
        row["labels"] = ["windows-latest"]
    elif fault == "missing_platform":
        listing["jobs"].pop()
        listing["total_count"] = 1
    elif fault == "failed":
        row["conclusion"] = "failure"
    elif fault == "prior_attempt":
        row["started_at"] = "2026-11-20T00:00:00Z"
    else:
        row["head_sha"] = "f" * 40
    with pytest.raises(ValueError, match="desktop_soak"):
        collect(tmp_path / "sources")
    assert not (tmp_path / "sources/provenance.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "other_workflow",
        "fork",
        "failed",
        "incomplete",
        "prior_attempt",
        "wrong_sha",
        "digest",
    ],
)
def test_unrelated_or_stale_source_cannot_satisfy_release_closure(tmp_path, mutation):
    mod = _module()
    records, collect = _actions_fixture(mod)
    route = "repos/42433422/XCMAX/actions/runs/1"
    run, listing = records[route], records[route + "/artifacts?per_page=100&page=1"]
    artifact = listing["artifacts"][0]
    if mutation == "other_workflow":
        run["path"] = ".github/workflows/untrusted.yml"
    elif mutation == "fork":
        run["head_repository"] = {"full_name": "attacker/XCMAX"}
    elif mutation == "failed":
        run["conclusion"] = "failure"
    elif mutation == "incomplete":
        listing["total_count"] = 2
        records[route + "/artifacts?per_page=100&page=2"] = {"total_count": 2, "artifacts": []}
    elif mutation == "prior_attempt":
        artifact["created_at"] = "2026-11-21T23:59:59Z"
    elif mutation == "wrong_sha":
        artifact["workflow_run"]["head_sha"] = "c" * 40
    elif mutation == "digest":
        artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        collect(tmp_path / "sources")
    assert not (tmp_path / "sources/provenance.json").exists()


def test_rerun_during_readback_and_unsafe_archive_are_rejected(tmp_path):
    mod = _module()
    records, collect = _actions_fixture(mod)
    readbacks = 0

    def api(path):
        nonlocal readbacks
        if path == "repos/42433422/XCMAX/actions/runs/1":
            readbacks += 1
            if readbacks == 2:
                return {**records[path], "run_attempt": 3}
        return records[path]

    with pytest.raises(ValueError, match="run changed"):
        collect(tmp_path / "raced", api=api)
    _, unsafe = _actions_fixture(mod, member="../outside.json")
    with pytest.raises(ValueError, match="unsafe artifact"):
        unsafe(tmp_path / "unsafe")
    assert not (tmp_path / "outside.json").exists()



def test_native_job_readback_cannot_race_into_another_attempt(tmp_path):
    mod = _module()
    records, collect = _actions_fixture(mod)
    route = "repos/42433422/XCMAX/actions/runs/5"
    jobs_route = route + "/attempts/2/jobs?per_page=100&page=1"
    jobs_read = False

    def api(path):
        nonlocal jobs_read
        if path == jobs_route:
            jobs_read = True
        if path == route and jobs_read:
            return {**records[path], "run_attempt": 3}
        return records[path]

    with pytest.raises(ValueError, match="desktop_soak: run changed"):
        collect(tmp_path / "raced", api=api)
    assert jobs_read
    assert not (tmp_path / "raced/provenance.json").exists()


def test_closure_identity_step_runs_from_source_and_generated_workflow(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    catalog = json.loads((repo / "FHD/config/download_release.json").read_text())
    for path in (
        repo / "FHD/.github/workflows/closure-evidence-report.yml",
        repo / ".github/workflows/fhd-closure-evidence-report.yml",
    ):
        workflow = yaml.safe_load(path.read_text())
        job = workflow["jobs"]["build-reports"]
        checkout = job["steps"][0]
        assert checkout["with"]["fetch-depth"] == 0
        step = next(row for row in job["steps"] if row.get("id") == "identity")
        output = tmp_path / ("source" if "FHD" in str(path.parent) else "published")
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=repo / job["defaults"]["run"]["working-directory"],
            env={
                **os.environ,
                "RELEASE_SHA": sha,
                "PRODUCT_VERSION": "",
                "GITHUB_OUTPUT": str(output),
                "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_text() == f"version={catalog['download_version']}\n"
        # All executable script references resolve from the actual job cwd.
        for row in job["steps"]:
            for token in row.get("run", "").split():
                if token.startswith("scripts/") and token.endswith(".py"):
                    assert (repo / "FHD" / token).is_file()


def test_only_catalog_versions_can_be_reported():
    mod = _module()
    assert mod.resolve_product_version("1.0.0.1") == "1.0.0.1"
    with pytest.raises(ValueError, match="catalog|registered"):
        mod.resolve_product_version("9.9.9.9")
