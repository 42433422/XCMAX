#!/usr/bin/env python3
"""Normalize native scanner JSON into the security release gate contract."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _severity(value: Any, *, default: str = "unknown") -> str:
    raw = str(value or default).strip().lower()
    try:
        score = float(raw)
    except (TypeError, ValueError):
        score = None
    if score is not None:
        if score >= 9:
            return "critical"
        if score >= 7:
            return "high"
        if score >= 4:
            return "medium"
        return "low"
    return {
        "error": "high",
        "warning": "medium",
        "warn": "medium",
        "note": "low",
        "info": "low",
        "moderate": "medium",
    }.get(raw, raw)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_native_payload(kind: str, data: Any) -> None:
    """Reject scanner error envelopes and structurally incomplete output.

    Several scanners emit valid JSON even when their service is unavailable.
    Treating such an error document as an empty finding list would create a
    false green release gate.
    """

    if kind in {"codeql", "dependabot"}:
        if not isinstance(data, list):
            raise ValueError(f"{kind} output must be a list")
        for row in _flatten_pages(data):
            if not isinstance(row, dict):
                raise ValueError(f"{kind} output contains a non-object row")
            required = (
                {"number", "rule", "state"}
                if kind == "codeql"
                else {"number", "dependency", "security_advisory", "state"}
            )
            if not required.issubset(row):
                raise ValueError(f"{kind} output contains an error envelope")
        return
    if kind == "trivy":
        if not isinstance(data, dict) or not isinstance(data.get("Results"), list):
            raise ValueError("trivy output is incomplete")
        return
    if kind == "pip-audit":
        if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
            raise ValueError("pip-audit output is incomplete")
        return
    if kind == "npm-audit":
        documents = data if isinstance(data, list) else [data]
        if not documents:
            raise ValueError("npm audit output is empty")
        for document in documents:
            if (
                not isinstance(document, dict)
                or not isinstance(document.get("vulnerabilities"), dict)
                or not isinstance(document.get("metadata"), dict)
                or not isinstance(document["metadata"].get("vulnerabilities"), dict)
            ):
                raise ValueError("npm audit output contains an error envelope")
        return
    if kind == "sarif":
        if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
            raise ValueError("SARIF output is incomplete")
        return
    raise ValueError(f"unsupported scanner kind: {kind}")


def _finding(
    identifier: Any, severity: Any, *, secret: bool = False, **extra: Any
) -> dict[str, Any]:
    return {
        "id": str(identifier or "unidentified"),
        "severity": _severity(severity),
        "status": "open",
        "applicable": True,
        "secret": secret,
        **extra,
    }


def _dismissal_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a manual dismissal into independently reviewable evidence.

    The dismissal comment must be JSON containing ``author``, ``evidence`` and
    ``review_due``.  The platform-authenticated dismissing user is the reviewer.
    Missing or malformed data remains blocking in the release gate.
    """

    raw_comment = str(row.get("dismissed_comment") or "").strip()
    try:
        comment = json.loads(raw_comment)
    except (TypeError, ValueError):
        comment = {}
    if not isinstance(comment, dict):
        comment = {}
    dismissed_by = row.get("dismissed_by")
    reviewer = (
        str(dismissed_by.get("login") or "") if isinstance(dismissed_by, dict) else ""
    )
    return {
        "status": "active",
        "disposition": "false_positive",
        "author": str(comment.get("author") or ""),
        "dismissal_reason": str(row.get("dismissed_reason") or ""),
        "false_positive_approval": {
            "reviewer": reviewer,
            "reviewed_at": str(row.get("dismissed_at") or ""),
            "evidence": str(comment.get("evidence") or ""),
            "review_due": str(comment.get("review_due") or ""),
        },
    }


def _flatten_pages(data: Any) -> list[Any]:
    if not isinstance(data, list):
        return []
    if data and all(isinstance(item, list) for item in data):
        return [row for page in data for row in page]
    return data


def _validate_codeql_provenance(
    data: Any,
    *,
    release_sha: str,
    required_categories: list[str],
    now: datetime | None = None,
) -> str:
    """Prove that CodeQL findings came from the exact release commit.

    The alerts API is repository-global.  Without checking the analyses API, a
    scan can accidentally export findings from the previous main commit and
    relabel them with the requested release SHA.  Require the newest analysis
    for every configured language category to match the frozen commit and be
    no older than 24 hours.
    """

    rows = [row for row in _flatten_pages(data) if isinstance(row, dict)]
    if not rows:
        raise ValueError("CodeQL analysis provenance is empty")
    expected = release_sha.strip().lower()
    if not expected:
        raise ValueError("CodeQL release SHA is empty")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    latest_by_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = str(row.get("category") or "").strip()
        created_at = str(row.get("created_at") or "")
        if not category or not created_at:
            continue
        previous = latest_by_category.get(category)
        if previous is None or created_at > str(previous.get("created_at") or ""):
            latest_by_category[category] = row
    categories = required_categories or sorted(latest_by_category)
    if not categories:
        raise ValueError("CodeQL analysis categories are empty")
    for category in categories:
        row = latest_by_category.get(category)
        if row is None:
            raise ValueError(f"CodeQL analysis category missing: {category}")
        if str(row.get("commit_sha") or "").strip().lower() != expected:
            raise ValueError(f"CodeQL analysis SHA mismatch: {category}")
        try:
            created = datetime.fromisoformat(
                str(row.get("created_at") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"CodeQL analysis timestamp invalid: {category}") from exc
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age = current - created.astimezone(UTC)
        if age.total_seconds() < 0 or age.total_seconds() > 24 * 60 * 60:
            raise ValueError(f"CodeQL analysis stale: {category}")
    return expected


def normalize(kind: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if kind == "codeql":
        for row in _flatten_pages(data):
            if not isinstance(row, dict) or row.get("state") not in (
                None,
                "open",
                "dismissed",
            ):
                continue
            rule = row.get("rule") if isinstance(row.get("rule"), dict) else {}
            severity = rule.get("security_severity_level") or rule.get("severity")
            extra = _dismissal_fields(row) if row.get("state") == "dismissed" else {}
            findings.append(
                _finding(row.get("number") or rule.get("id"), severity, **extra)
            )
    elif kind == "dependabot":
        for row in _flatten_pages(data):
            if not isinstance(row, dict) or row.get("state") not in (
                None,
                "open",
                "dismissed",
            ):
                continue
            advisory = row.get("security_advisory") or {}
            dependency = row.get("dependency") or {}
            extra = _dismissal_fields(row) if row.get("state") == "dismissed" else {}
            findings.append(
                _finding(
                    row.get("number")
                    or advisory.get("ghsa_id")
                    or dependency.get("package", {}).get("name"),
                    advisory.get("severity"),
                    **extra,
                )
            )
    elif kind == "trivy":
        for result in data.get("Results", []) if isinstance(data, dict) else []:
            if not isinstance(result, dict):
                continue
            for row in result.get("Vulnerabilities") or []:
                if isinstance(row, dict):
                    findings.append(
                        _finding(row.get("VulnerabilityID"), row.get("Severity"))
                    )
            for row in result.get("Secrets") or []:
                if isinstance(row, dict):
                    findings.append(
                        _finding(row.get("RuleID"), row.get("Severity"), secret=True)
                    )
    elif kind == "pip-audit":
        for dependency in (
            data.get("dependencies", []) if isinstance(data, dict) else []
        ):
            if not isinstance(dependency, dict):
                continue
            for vulnerability in dependency.get("vulns") or []:
                if isinstance(vulnerability, dict):
                    aliases = vulnerability.get("aliases") or []
                    findings.append(
                        _finding(
                            vulnerability.get("id")
                            or (aliases[0] if aliases else dependency.get("name")),
                            vulnerability.get("severity") or "high",
                        )
                    )
    elif kind == "npm-audit":
        documents = data if isinstance(data, list) else [data]
        for document in documents:
            vulnerabilities = (
                document.get("vulnerabilities", {})
                if isinstance(document, dict)
                else {}
            )
            for name, row in vulnerabilities.items():
                if isinstance(row, dict):
                    findings.append(_finding(name, row.get("severity")))
    elif kind == "sarif":
        for run in data.get("runs", []) if isinstance(data, dict) else []:
            if not isinstance(run, dict):
                continue
            for row in run.get("results") or []:
                if not isinstance(row, dict):
                    continue
                properties = (
                    row.get("properties")
                    if isinstance(row.get("properties"), dict)
                    else {}
                )
                findings.append(
                    _finding(
                        row.get("ruleId"),
                        properties.get("security-severity")
                        or row.get("level")
                        or "high",
                    )
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scanner", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--provenance-input", type=Path)
    parser.add_argument("--required-codeql-category", action="append", default=[])
    args = parser.parse_args()
    available = args.input.is_file()
    findings: list[dict[str, Any]] = []
    error = ""
    source_sha = args.release_sha.strip().lower()
    if available:
        try:
            native_payload = _load(args.input)
            _validate_native_payload(args.kind, native_payload)
            if args.kind == "codeql":
                if not args.provenance_input or not args.provenance_input.is_file():
                    raise ValueError("CodeQL analysis provenance is missing")
                source_sha = _validate_codeql_provenance(
                    _load(args.provenance_input),
                    release_sha=args.release_sha,
                    required_categories=args.required_codeql_category,
                )
            findings = normalize(args.kind, native_payload)
            if args.scanner == "gitleaks":
                for finding in findings:
                    finding["secret"] = True
        except (OSError, TypeError, ValueError) as exc:
            available = False
            if args.kind == "codeql":
                source_sha = ""
            error = f"{type(exc).__name__}:{str(exc)[:200]}"
    payload = {
        "schema": "security-scanner-evidence/v1",
        "scanner": args.scanner,
        "release_sha": args.release_sha.strip().lower(),
        "source_sha": source_sha,
        "scanned_at": datetime.now(UTC).isoformat(),
        "available": available,
        "error": error,
        "findings": findings,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if available else 2


if __name__ == "__main__":
    raise SystemExit(main())
