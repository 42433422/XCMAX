#!/usr/bin/env python3
"""Fail-closed security release gate over normalized scanner evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_SCANNERS = (
    "codeql",
    "dependabot",
    "trivy-filesystem",
    "trivy-image",
    "python-dependencies",
    "node-dependencies",
    "desktop-prerelease",
    "gitleaks",
    "production-host",
)
BLOCKING_SEVERITIES = {"critical", "high"}


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _false_positive_is_valid(finding: dict[str, Any], now: datetime) -> bool:
    approval = finding.get("false_positive_approval")
    if not isinstance(approval, dict):
        return False
    reviewed_at = _parse_time(approval.get("reviewed_at"))
    reviewer = str(approval.get("reviewer") or "").strip()
    author = str(finding.get("author") or "").strip()
    evidence = str(approval.get("evidence") or "").strip()
    review_due = _parse_time(approval.get("review_due"))
    return bool(
        reviewer
        and reviewer != author
        and evidence
        and reviewed_at
        and reviewed_at <= now
        and review_due
        and review_due >= now
    )


def evaluate(
    reports_dir: Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
    release_sha: str = "",
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    blockers: list[str] = []
    scanner_results: dict[str, Any] = {}
    applicable_counts = {"critical": 0, "high": 0}
    for scanner in REQUIRED_SCANNERS:
        path = reports_dir / f"{scanner}.json"
        if not path.is_file():
            blockers.append(f"{scanner}:report_missing")
            scanner_results[scanner] = {"available": False, "fresh": False, "blocking": 0}
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            blockers.append(f"{scanner}:report_invalid")
            scanner_results[scanner] = {"available": False, "fresh": False, "blocking": 0}
            continue
        available = report.get("available") is True
        scanned_at = _parse_time(report.get("scanned_at"))
        fresh = bool(
            scanned_at and current - timedelta(hours=max_age_hours) <= scanned_at <= current
        )
        if not available:
            blockers.append(f"{scanner}:scanner_unavailable")
        if not fresh:
            blockers.append(f"{scanner}:report_stale")
        if release_sha and str(report.get("release_sha") or "").lower() != release_sha.lower():
            blockers.append(f"{scanner}:release_sha_mismatch")
        if release_sha and str(report.get("source_sha") or "").lower() != release_sha.lower():
            blockers.append(f"{scanner}:source_sha_mismatch")
        findings = report.get("findings") if isinstance(report.get("findings"), list) else []
        blocking_ids: list[str] = []
        secret_ids: list[str] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if str(finding.get("status") or "open").lower() not in {"open", "active"}:
                continue
            finding_id = str(finding.get("id") or "unidentified")
            if finding.get("secret") is True:
                secret_ids.append(finding_id)
            severity = str(finding.get("severity") or "").lower()
            applicable = finding.get("applicable", True) is not False
            if severity in BLOCKING_SEVERITIES and applicable:
                if finding.get("disposition") == "false_positive" and _false_positive_is_valid(
                    finding, current
                ):
                    continue
                applicable_counts[severity] += 1
                blocking_ids.append(finding_id)
        if secret_ids:
            blockers.append(f"{scanner}:unresolved_secret:{','.join(sorted(secret_ids))}")
        if blocking_ids:
            blockers.append(f"{scanner}:critical_or_high:{','.join(sorted(blocking_ids))}")
        scanner_results[scanner] = {
            "available": available,
            "fresh": fresh,
            "blocking": len(blocking_ids),
            "unresolved_secrets": len(secret_ids),
        }
    return {
        "schema": "security-release-gate/v1",
        "generated_at": current.isoformat(),
        "passed": not blockers,
        "required_scanners": list(REQUIRED_SCANNERS),
        "applicable_open": applicable_counts,
        "blockers": blockers,
        "scanners": scanner_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--release-sha", default="")
    args = parser.parse_args()
    result = evaluate(
        args.reports_dir,
        max_age_hours=args.max_age_hours,
        release_sha=args.release_sha,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
