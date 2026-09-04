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
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REPORT_FILENAMES = (
    "release-convergence-report.json",
    "security-report.json",
    "production-reliability-report.json",
    "customer-value-report.json",
)
STAGES = ("payment", "installation", "first_use", "outcome", "acceptance", "reuse")


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
    product_version: str = "1.0.0.1",
    now: datetime | None = None,
) -> dict[str, Any]:
    release_sha = release_sha.strip().lower()
    if not FULL_SHA.fullmatch(release_sha):
        raise ValueError("release_sha must be an exact lowercase 40-character Git SHA")
    if product_version != "1.0.0.1":
        raise ValueError("the closure contract keeps product_version at 1.0.0.1")
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    release_id = f"xcagi-{product_version}-{release_sha}"

    convergence = _load(convergence_path)
    security = _load(security_path)
    slo = _load(slo_path)
    rollback = _load(rollback_path)
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
            "two_consecutive_daily_scans": security.get("passed") is True,
            "applicable_open": security.get("applicable_open", {}),
            "scanners": security.get("scanners", {}),
            "blockers": security_blockers,
        },
        "source_evidence": [_source("security_scan_pair", security_path, security)],
    }

    slo_blockers = list(slo.get("blockers") or [])
    rollback_blockers = list(rollback.get("blockers") or [])
    reliability_passed = bool(
        slo.get("passed") is True
        and slo.get("release_id") == release_id
        and int(slo.get("continuous_days") or 0) >= 90
        and rollback.get("passed") is True
        and rollback.get("release_sha") == release_sha
        and not slo_blockers
        and not rollback_blockers
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
        },
        "source_evidence": [
            _source("production_slo_window", slo_path, slo),
            _source("upgrade_rollback", rollback_path, rollback),
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
    customer_passed = bool(
        customer.get("value_ledger_ready") is True
        and customer.get("three_customer_loop_verified") is True
        and customer_count >= 3
        and customer.get("release_sha") == release_sha
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-convergence", type=Path, required=True)
    parser.add_argument("--security", type=Path, required=True)
    parser.add_argument("--slo", type=Path, required=True)
    parser.add_argument("--upgrade-rollback", type=Path, required=True)
    parser.add_argument("--customer-value", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--product-version", default="1.0.0.1")
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
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
