#!/usr/bin/env python3
"""Triage/dedupe security release-scan findings without rubber-stamping."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BLOCKING = {"critical", "high"}


def _finding_key(scanner: str, finding: dict[str, Any]) -> tuple[str, ...]:
    return (
        scanner,
        str(finding.get("id") or ""),
        str(finding.get("rule_id") or finding.get("rule") or ""),
        str(finding.get("path") or finding.get("file") or ""),
        str(finding.get("severity") or "").lower(),
    )


def triage(reports_dir: Path) -> dict[str, Any]:
    raw_blocking = 0
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    by_severity: Counter[str] = Counter()
    scanners_seen: list[str] = []
    errors: list[str] = []
    for path in sorted(reports_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            errors.append(f"invalid_report:{path.name}")
            continue
        scanner = path.stem
        scanners_seen.append(scanner)
        findings = report.get("findings") if isinstance(report, dict) else None
        if not isinstance(findings, list) or report.get("available") is not True:
            errors.append(f"unavailable_report:{path.name}")
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                errors.append(f"invalid_finding:{path.name}")
                continue
            if str(finding.get("status") or "open").lower() not in {"open", "active"}:
                continue
            severity = str(finding.get("severity") or "").lower()
            if severity not in BLOCKING:
                continue
            if finding.get("applicable", True) is False:
                continue
            raw_blocking += 1
            key = _finding_key(scanner, finding)
            if key not in unique:
                unique[key] = {
                    "scanner": scanner,
                    "id": finding.get("id"),
                    "rule_id": finding.get("rule_id") or finding.get("rule"),
                    "path": finding.get("path") or finding.get("file"),
                    "severity": severity,
                    "title": finding.get("title") or finding.get("message") or "",
                }
                by_severity[severity] += 1
    if not scanners_seen:
        errors.append("no_reports")
    return {
        "schema": "xcagi.security_findings_triage/v1",
        "scanners": scanners_seen,
        "errors": errors,
        "raw_blocking_count": raw_blocking,
        "unique_blocking_count": len(unique),
        "unique_by_severity": dict(by_severity),
        "unique_findings": list(unique.values()),
        "rubber_stamp_forbidden": True,
        "gate_still_fail_closed": True,
        "note": "Deduped inventory for human verification; security_release_gate.py remains authoritative.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = triage(args.reports_dir)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if result["errors"] else 1 if result["unique_blocking_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
