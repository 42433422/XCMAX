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
    "credential-rotation",
    "production-host",
)
BLOCKING_SEVERITIES = {"critical", "high"}


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
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
        author
        and reviewer
        and reviewer.casefold() != author.casefold()
        and evidence
        and reviewed_at
        and reviewed_at <= now
        and review_due
        and review_due >= now
    )


def _load_baseline(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Load the reviewed historical-risk baseline.

    Baseline 只冻结「已知历史存量」,且每条必须带责任人、理由和过期时间。
    文件缺失、结构不合法或字段不全时抛错,由调用方 fail closed,避免误删
    baseline 后历史债被静默放行。
    """

    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"baseline file missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"baseline unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "security-baseline/v1":
        raise ValueError("baseline schema mismatch")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("baseline entries invalid")
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("baseline entry invalid")
        scanner = str(entry.get("scanner") or "").strip()
        finding_id = str(entry.get("id") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        owner = str(entry.get("owner") or "").strip()
        expires = _parse_time(entry.get("expires"))
        if not (scanner and finding_id and reason and owner and expires):
            raise ValueError(f"baseline entry incomplete: {scanner}:{finding_id}")
        index[(scanner, finding_id)] = entry
    return index


def evaluate(
    reports_dir: Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
    release_sha: str = "",
    baseline: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    baseline_index = baseline or {}
    blockers: list[str] = []
    scanner_results: dict[str, Any] = {}
    applicable_counts = {"critical": 0, "high": 0}
    suppressed: dict[str, list[str]] = {}
    expired_baselines: list[str] = []
    for scanner in REQUIRED_SCANNERS:
        path = reports_dir / f"{scanner}.json"
        if not path.is_file():
            blockers.append(f"{scanner}:report_missing")
            scanner_results[scanner] = {"available": False, "fresh": False, "blocking": 0}
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
                raise ValueError("normalized scanner report requires an explicit findings list")
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
        findings = report["findings"]
        blocking_ids: list[str] = []
        secret_ids: list[str] = []
        for index, finding in enumerate(findings):
            if (
                not isinstance(finding, dict)
                or not isinstance(finding.get("id"), str)
                or not finding["id"].strip()
                or str(finding.get("severity") or "").lower()
                not in {"critical", "high", "medium", "low", "unknown"}
                or str(finding.get("status", "open")).lower() not in {"open", "active", "closed"}
                or any(
                    key in finding and type(finding[key]) is not bool
                    for key in ("secret", "applicable")
                )
            ):
                blockers.append(f"{scanner}:finding_invalid:{index}")
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
                if finding.get("secret") is not True:
                    entry = baseline_index.get((scanner, finding_id))
                    if entry is not None:
                        expires = _parse_time(entry.get("expires"))
                        if expires and expires > current:
                            suppressed.setdefault(scanner, []).append(finding_id)
                            continue
                        expired_baselines.append(f"{scanner}:{finding_id}")
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
    if expired_baselines:
        blockers.append(f"baseline_expired:{','.join(sorted(expired_baselines))}")
    return {
        "schema": "security-release-gate/v1",
        "generated_at": current.isoformat(),
        "passed": not blockers,
        "required_scanners": list(REQUIRED_SCANNERS),
        "applicable_open": applicable_counts,
        "suppressed": {key: sorted(value) for key, value in sorted(suppressed.items())},
        "expired_baselines": sorted(expired_baselines),
        "blockers": blockers,
        "scanners": scanner_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--release-sha", default="")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        baseline = _load_baseline(args.baseline)
    except ValueError as exc:
        print(f"::error::security baseline invalid: {exc}")
        return 2
    result = evaluate(
        args.reports_dir,
        max_age_hours=args.max_age_hours,
        release_sha=args.release_sha,
        baseline=baseline,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
