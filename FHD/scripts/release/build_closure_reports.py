#!/usr/bin/env python3
"""Build the four redacted, content-addressed release closure reports.

The command writes reports even when a gate is closed so reviewers can see the
real blockers, but exits non-zero until every external proof is satisfied.
Raw evidence is represented by its schema and SHA256; customer/order/device
identifiers are never copied into the public reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.release.verify_desktop_soak import verify_bundle

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REPORT_FILENAMES = (
    "release-convergence-report.json",
    "security-report.json",
    "production-reliability-report.json",
    "customer-value-report.json",
)
STAGES = ("payment", "installation", "first_use", "outcome", "acceptance", "reuse")
SOURCE_WORKFLOWS = {
    "convergence": ("fhd-release-convergence-readback.yml", "xcagi-release-convergence"),
    "security/current": ("fhd-security-full-scan.yml", "xcagi-security-release-reports"),
    "security/previous": ("fhd-security-full-scan.yml", "xcagi-security-release-reports"),
    "rollback": ("fhd-upgrade-rollback-evidence.yml", "xcagi-upgrade-rollback-evidence"),
    "desktop_soak": ("fhd-desktop-soak.yml", "xcagi-desktop-soak"),
}
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


def resolve_product_version(value: str | None = None) -> str:
    """Resolve names from the existing catalog; this does not promote a release."""
    catalog = json.loads(
        (Path(__file__).resolve().parents[2] / "config/download_release.json").read_text()
    )
    version = value or catalog["download_version"]
    versions = {row["version"] for row in catalog["release_history"]}
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version) or version not in versions:
        raise ValueError("product version is not registered in download_release.json")
    return version


def _github_api(path: str) -> dict:
    response = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        check=True,
        timeout=60,
    )
    if len(response.stdout) > MAX_ARCHIVE_BYTES:
        raise ValueError("GitHub response exceeds the evidence limit")
    data = json.loads(response.stdout)
    if not isinstance(data, dict):
        raise ValueError("GitHub returned an invalid evidence object")
    return data


def _download(path: str, destination: Path) -> None:
    with destination.open("xb") as stream:
        subprocess.run(
            ["gh", "api", path],
            stdout=stream,
            stderr=subprocess.PIPE,
            check=True,
            timeout=180,
        )


def _ancestor(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
            capture_output=True,
            check=False,
            timeout=15,
        ).returncode
        == 0
    )


def _stamp(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("evidence timestamps must include a timezone")
    return result.astimezone(UTC)


def _native_jobs(api, route: str, run: dict, start: datetime, end: datetime) -> dict:
    """Bind reports to the actual registered-device jobs in this exact attempt."""
    data = api(f"{route}/attempts/{run['run_attempt']}/jobs?per_page=100&page=1")
    rows, count = data.get("jobs"), data.get("total_count")
    if (not isinstance(rows, list) or type(count) is not int or not 1 <= count <= 100
            or len(rows) != count or len({row.get("id") for row in rows}) != count):
        raise ValueError("desktop_soak: incomplete original native job listing")
    jobs = {}
    for platform in ("windows", "macos"):
        matches = [row for row in rows if row.get("name") == f"Desktop soak ({platform})"]
        if len(matches) != 1:
            raise ValueError(f"desktop_soak: {platform} original job missing or ambiguous")
        row = matches[0]
        labels = row.get("labels") if isinstance(row.get("labels"), list) else []
        if not (
            type(row.get("id")) is int and row["id"] > 0
            and row.get("run_id") == run["id"] and row.get("head_sha") == run["head_sha"]
            and row.get("status") == "completed" and row.get("conclusion") == "success"
            and type(row.get("runner_id")) is int and row["runner_id"] > 0
            and isinstance(row.get("runner_name"), str) and row["runner_name"]
            and {"self-hosted", "xcagi-physical", platform} <= {str(label).lower() for label in labels}
            and start <= _stamp(row.get("started_at")) <= _stamp(row.get("completed_at")) <= end
        ):
            raise ValueError(f"desktop_soak: {platform} original registered-device job mismatch")
        jobs[platform] = {key: row[key] for key in (
            "id", "runner_id", "runner_name", "labels", "started_at", "completed_at",
        )}
    if jobs["windows"]["runner_id"] == jobs["macos"]["runner_id"]:
        raise ValueError("desktop_soak: two distinct registered native runners are required")
    return jobs


def collect_source_artifact(
    *,
    repository: str,
    run: dict,
    name: str,
    label: str,
    output_dir: Path,
    api=_github_api,
    download=_download,
    current_run_attempt: tuple[int, int] | None = None,
    max_archive_bytes: int = MAX_ARCHIVE_BYTES,
) -> dict[str, Any]:
    """Read immutable original bytes for an already authenticated workflow run.

    The ordinary collector only calls this for completed successful runs. Native
    pre-publication consumers may bind the current in-progress run and attempt;
    only that bounded path uses observation time instead of a completion time.
    """
    attempt = run.get("run_attempt")
    controller = run["head_sha"]
    if type(max_archive_bytes) is not int or not 0 < max_archive_bytes <= 512 * 1024 * 1024:
        raise ValueError("invalid bounded evidence archive limit")
    if current_run_attempt is None and (
        run.get("status") != "completed" or run.get("conclusion") != "success"
    ):
        raise ValueError("complete successful original artifact source required")
    if current_run_attempt and (
        current_run_attempt != (run.get("id"), attempt)
        or run.get("status") != "in_progress"
        or run.get("conclusion") is not None
    ):
        raise ValueError("current native acceptance run/attempt mismatch")
    route = f"repos/{repository}/actions/runs/{run['id']}"
    workflow = str(run["path"]).removeprefix(".github/workflows/")
    original = api(f"{route}/attempts/{attempt}")
    if any(
        original.get(key) != run.get(key)
        for key in (
            "id",
            "run_attempt",
            "head_sha",
            "path",
            "status",
            "conclusion",
        )
    ):
        raise ValueError(f"{label}: original attempt changed")
    start = _stamp(original["run_started_at"])
    end = datetime.now(UTC) if current_run_attempt else _stamp(original["updated_at"])
    artifacts: list[dict] = []
    total: int | None = None
    for page in range(1, 101):
        data = api(f"{route}/artifacts?per_page=100&page={page}")
        count, rows = data.get("total_count"), data.get("artifacts")
        if (
            type(count) is not int
            or count < 0
            or count > 10000
            or not isinstance(rows, list)
            or (total is not None and count != total)
        ):
            raise ValueError(f"{label}: incomplete artifact listing")
        total = count
        artifacts.extend(rows)
        if len(artifacts) == total:
            break
        if not rows or len(artifacts) > total:
            raise ValueError(f"{label}: incomplete artifact listing")
    else:
        raise ValueError(f"{label}: artifact listing limit exceeded")
    ids = [row.get("id") for row in artifacts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label}: duplicate artifact IDs")
    matches = [row for row in artifacts if row.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"{label}: original artifact missing or ambiguous")
    artifact = matches[0]
    identity = artifact.get("workflow_run", {})
    artifact_id, size = artifact.get("id"), artifact.get("size_in_bytes")
    if not (
        type(artifact_id) is int
        and artifact_id > 0
        and artifact.get("expired") is False
        and type(size) is int
        and 0 < size <= max_archive_bytes
        and identity.get("id") == run["id"]
        and identity.get("head_sha") == controller
        and start <= _stamp(artifact.get("created_at")) <= end
        and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", ""))
    ):
        raise ValueError(f"{label}: original artifact/attempt identity mismatch")
    archive = output_dir / (label.replace("/", "-") + ".zip")
    download(f"repos/{repository}/actions/artifacts/{artifact_id}/zip", archive)
    if archive.stat().st_size != size or "sha256:" + _digest(archive) != artifact["digest"]:
        raise ValueError(f"{label}: original artifact byte digest mismatch")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        names = [member.filename for member in members]
        if (
            len(names) != len(set(names))
            or len(members) > 1000
            or sum(member.file_size for member in members) > max_archive_bytes
            or any(
                Path(name).is_absolute()
                or ".." in Path(name).parts
                or "\\" in name
                or Path(name).as_posix() != name.rstrip("/")
                for name in names
            )
            or any(stat.S_ISLNK(member.external_attr >> 16) for member in members)
        ):
            raise ValueError(f"{label}: unsafe artifact contents")
        bundle.extractall(output_dir / label)
    evidence = {
        "run_id": run["id"],
        "run_attempt": attempt,
        "controller_sha": controller,
        "workflow": workflow,
        "artifact_id": artifact_id,
        "artifact_digest": artifact["digest"],
        "run_started_at": original["run_started_at"],
        "artifact_created_at": artifact["created_at"],
    }
    if label == "desktop_soak":
        evidence["native_jobs"] = _native_jobs(api, route, run, start, end)
        evidence["reports"] = {
            platform: _digest(output_dir / label / f"{platform}.json")
            for platform in ("windows", "macos")
        }
    latest = api(route)
    if any(
        latest.get(key) != run.get(key)
        for key in (
            "id",
            "run_attempt",
            "head_sha",
            "status",
            "conclusion",
            *(() if current_run_attempt else ("updated_at",)),
        )
    ):
        raise ValueError(f"{label}: run changed during evidence readback")
    return evidence


def collect_sources(
    *,
    repository: str,
    release_sha: str,
    runs: dict[str, str],
    output_dir: Path,
    api=_github_api,
    download=_download,
    ancestor=_ancestor,
) -> dict[str, Any]:
    """Read original Actions artifacts; never trust a downloaded PASS by name alone.

    The controller SHA may be newer than the release under observation.  Both
    must belong to main; the report validators bind the measured release SHA.
    Artifact creation is bounded by the exact current run attempt, so evidence
    from a previous attempt cannot satisfy a successful rerun.
    """
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or not FULL_SHA.fullmatch(release_sha)
        or not ancestor(release_sha)
    ):
        raise ValueError("invalid repository or release outside main")
    if set(runs) != set(SOURCE_WORKFLOWS):
        raise ValueError("all original closure evidence sources are required")
    output_dir.mkdir(parents=True, exist_ok=False)
    proof: dict[str, Any] = {"release_sha": release_sha, "repository": repository, "sources": {}}
    for label, (workflow, name) in SOURCE_WORKFLOWS.items():
        run_id = str(runs[label])
        if not re.fullmatch(r"[1-9][0-9]*", run_id):
            raise ValueError(f"{label}: invalid original run ID")
        route = f"repos/{repository}/actions/runs/{run_id}"
        run = api(route)
        attempt = run.get("run_attempt")
        controller = run.get("head_sha", "")
        if not (
            str(run.get("id")) == run_id
            and type(attempt) is int
            and attempt > 0
            and run.get("repository", {}).get("full_name") == repository
            and run.get("head_repository", {}).get("full_name") == repository
            and run.get("path") == f".github/workflows/{workflow}"
            and run.get("head_branch") == "main"
            and run.get("event") == "workflow_dispatch"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and FULL_SHA.fullmatch(controller)
            and ancestor(controller)
        ):
            raise ValueError(f"{label}: original workflow provenance mismatch")
        proof["sources"][label] = collect_source_artifact(
            repository=repository,
            run=run,
            name=name,
            label=label,
            output_dir=output_dir,
            api=api,
            download=download,
        )
    (output_dir / "provenance.json").write_bytes(_canonical(proof))
    return proof


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    data = payload.get("data") if payload.get("ok") is True else None
    return data if isinstance(data, dict) else payload


def _source(label: str, path: Path, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "label": label,
        "schema": str(payload.get("schema") or "unknown"),
        "sha256": _digest(path),
    }


def _common(*, release_sha: str, product_version: str, generated_at: datetime) -> dict[str, Any]:
    return {
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "product_version": product_version,
        "release_sha": release_sha,
        "release_id": f"xcagi-{product_version}-{release_sha}",
    }


def build_reports(
    *,
    convergence_path: Path,
    security_path: Path,
    slo_path: Path,
    rollback_path: Path,
    customer_path: Path,
    output_dir: Path,
    release_sha: str,
    product_version: str | None = None,
    now: datetime | None = None,
    desktop_soak_dir: Path | None = None,
    provenance_path: Path | None = None,
) -> dict[str, Any]:
    release_sha = release_sha.strip().lower()
    if not FULL_SHA.fullmatch(release_sha):
        raise ValueError("release_sha must be an exact lowercase 40-character Git SHA")
    product_version = resolve_product_version(product_version)
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    release_id = f"xcagi-{product_version}-{release_sha}"

    convergence = _load(convergence_path)
    security = _load(security_path)
    slo = _load(slo_path)
    rollback = _load(rollback_path)
    desktop_soak = verify_bundle(
        desktop_soak_dir, release_sha=release_sha, product_version=product_version,
        provenance=_load(provenance_path) if provenance_path else None,
    )
    customer = _load(customer_path)
    common = _common(
        release_sha=release_sha,
        product_version=product_version,
        generated_at=generated_at,
    )

    source_states = Counter(
        str(row.get("status") or "unknown")
        for row in convergence.get("sources", [])
        if isinstance(row, dict)
    )
    convergence_blockers = list(convergence.get("blockers") or [])
    convergence_passed = bool(
        convergence.get("converged") is True
        and convergence.get("release_sha") == release_sha
        and convergence.get("release_id") == release_id
        and not convergence_blockers
    )
    release_report = {
        **common,
        "schema": "xcagi.closure.release_convergence/v1",
        "passed": convergence_passed,
        "summary": {
            "converged": convergence.get("converged") is True,
            "active_purchased_accounts": int(convergence.get("active_purchased_accounts") or 0),
            "reported_installations": int(convergence.get("reported_installations") or 0),
            "source_status_counts": dict(sorted(source_states.items())),
            "blockers": convergence_blockers,
        },
        "source_evidence": [_source("release_convergence", convergence_path, convergence)],
    }

    security_blockers = list(security.get("blockers") or [])
    security_passed = bool(
        security.get("passed") is True
        and security.get("release_sha") == release_sha
        and not security_blockers
    )
    security_report = {
        **common,
        "schema": "xcagi.closure.security/v1",
        "passed": security_passed,
        "summary": {
            "required_same_sha_scan": security.get("passed") is True,
            "scan_mode": security.get("mode", "unknown"),
            "applicable_open": security.get("applicable_open", {}),
            "scanners": security.get("scanners", {}),
            "blockers": security_blockers,
        },
        "source_evidence": [_source("security_scan_pair", security_path, security)],
    }

    slo_blockers = list(slo.get("blockers") or [])
    rollback_blockers = list(rollback.get("blockers") or [])
    if (
        rollback.get("verification_scope") != "measured_native_acceptance"
        and "independent_native_measurements_missing" not in rollback_blockers
    ):
        rollback_blockers.append("independent_native_measurements_missing")
    reliability_passed = bool(
        slo.get("passed") is True
        and slo.get("release_id") == release_id
        and int(slo.get("continuous_days") or 0) >= 90
        and rollback.get("passed") is True
        and rollback.get("verification_scope") == "measured_native_acceptance"
        and rollback.get("release_sha") == release_sha
        and not slo_blockers
        and not rollback_blockers
        and desktop_soak["passed"] is True
    )
    reliability_report = {
        **common,
        "schema": "xcagi.closure.production_reliability/v1",
        "passed": reliability_passed,
        "summary": {
            "continuous_days": int(slo.get("continuous_days") or 0),
            "day_0": str(slo.get("day_0") or ""),
            "day_n": str(slo.get("day_n") or ""),
            "slo_chain_tip": str(slo.get("chain_tip") or ""),
            "server_rto_minutes": rollback.get("server_rto_minutes"),
            "server_rpo_minutes": rollback.get("server_rpo_minutes"),
            "slo_blockers": slo_blockers,
            "upgrade_rollback_blockers": rollback_blockers,
            "upgrade_rollback_scope": rollback.get("verification_scope", "unverified"),
            "desktop_soak_scope": desktop_soak["verification_scope"],
            "desktop_soak_blockers": desktop_soak["blockers"],
            "desktop_soak_platforms": desktop_soak["per_platform"],
        },
        "source_evidence": [
            _source("production_slo_window", slo_path, slo),
            _source("upgrade_rollback", rollback_path, rollback),
        ] + [
            _source(f"desktop_soak_{platform}", desktop_soak_dir / f"{platform}.json",
                    {"schema": "xcagi.desktop_soak/v1"})
            for platform in ("windows", "macos")
            if desktop_soak_dir and (desktop_soak_dir / f"{platform}.json").is_file()
        ],
    }

    public_customers: list[dict[str, Any]] = []
    for row in customer.get("customers", []):
        if not isinstance(row, dict):
            continue
        stages = row.get("stages") if isinstance(row.get("stages"), dict) else {}
        public_customers.append(
            {
                "customer_alias": str(row.get("customer_alias") or "unverified"),
                "stages": {stage: stages.get(stage) is True for stage in STAGES},
                "ordered": row.get("ordered") is True,
                "complete": row.get("complete") is True,
                "gaps": [str(item) for item in row.get("gaps", [])],
            }
        )
    customer_count = int(customer.get("complete_customer_count") or 0)
    complete_customers = {
        row["customer_alias"]
        for row in public_customers
        if re.fullmatch(r"customer-[0-9a-f]{12}", row["customer_alias"])
        and row["ordered"]
        and row["complete"]
        and all(row["stages"].values())
        and not row["gaps"]
    }
    customer_blockers = []
    if (
        customer.get("schema") != "customer_value_evidence.v1"
        or customer.get("verification_scope") != "native_customer_release"
        or customer.get("release_binding_source") != "original_workflow_and_published_desktop"
        or customer.get("release_sha") != release_sha
    ):
        customer_blockers.append("original_customer_release_binding_missing")
    if customer_count != len(complete_customers) or customer_count < 3:
        customer_blockers.append("three_distinct_complete_customers_missing")
    if customer.get("value_ledger_ready") is not True:
        customer_blockers.append("authoritative_customer_ledger_unavailable")
    customer_passed = bool(
        customer.get("value_ledger_ready") is True
        and customer.get("three_customer_loop_verified") is True
        and customer_count >= 3
        and not customer_blockers
    )
    customer_report = {
        **common,
        "schema": "xcagi.closure.customer_value/v1",
        "passed": customer_passed,
        "summary": {
            "six_stage_counts": customer.get("six_stage_counts", {}),
            "complete_customer_count": customer_count,
            "complete_customer_target": 3,
            "lifecycle_gaps": customer.get("lifecycle_gaps", {}),
            "excluded": customer.get("excluded", {}),
            "customers": public_customers,
            "blockers": customer_blockers,
        },
        "source_evidence": [_source("customer_value", customer_path, customer)],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        REPORT_FILENAMES[0]: release_report,
        REPORT_FILENAMES[1]: security_report,
        REPORT_FILENAMES[2]: reliability_report,
        REPORT_FILENAMES[3]: customer_report,
    }
    report_entries: list[dict[str, Any]] = []
    for filename, report in reports.items():
        destination = output_dir / filename
        destination.write_bytes(_canonical(report))
        digest = _digest(destination)
        (output_dir / f"{filename}.sha256").write_text(f"{digest}  {filename}\n", encoding="utf-8")
        report_entries.append({"file": filename, "sha256": digest, "passed": report["passed"]})
    manifest = {
        **common,
        "schema": "xcagi.closure.evidence_manifest/v1",
        "passed": all(report["passed"] for report in reports.values()),
        "reports": report_entries,
    }
    (output_dir / "evidence-manifest.json").write_bytes(_canonical(manifest))
    return manifest


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"collect", "version"}:
        parser = argparse.ArgumentParser()
        parser.add_argument("command", choices=("collect", "version"))
        parser.add_argument("--product-version")
        parser.add_argument("--release-sha")
        parser.add_argument("--output-dir", type=Path)
        args = parser.parse_args()
        if args.command == "version":
            print(resolve_product_version(args.product_version))
        else:
            print(
                json.dumps(
                    collect_sources(
                        repository=os.environ["GITHUB_REPOSITORY"],
                        release_sha=args.release_sha,
                        runs=json.loads(os.environ["SOURCE_RUNS_JSON"]),
                        output_dir=args.output_dir,
                    ),
                    indent=2,
                )
            )
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-convergence", type=Path, required=True)
    parser.add_argument("--security", type=Path, required=True)
    parser.add_argument("--slo", type=Path, required=True)
    parser.add_argument("--upgrade-rollback", type=Path, required=True)
    parser.add_argument("--desktop-soak-dir", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--customer-value", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--product-version")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_reports(
        convergence_path=args.release_convergence,
        security_path=args.security,
        slo_path=args.slo,
        rollback_path=args.upgrade_rollback,
        customer_path=args.customer_value,
        output_dir=args.output_dir,
        release_sha=args.release_sha,
        product_version=args.product_version,
        desktop_soak_dir=args.desktop_soak_dir,
        provenance_path=args.provenance,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
