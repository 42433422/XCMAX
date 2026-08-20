"""Fixture-only redacted security finding auditor; never accepts secret values."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential|value)"
)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _SENSITIVE_KEY.search(str(key)) or _contains_sensitive_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("finding_summary")
    # Platform-owned execution-envelope keys are outside this employee's input
    # contract.  Inspect only the declared finding_summary object, while still
    # rejecting any secret-shaped field before reading or returning its value.
    if _contains_sensitive_key(summary):
        return {
            "ok": False,
            "status": "blocked",
            "summary": "sensitive-value-shaped fields are not accepted",
            "issues": [
                {
                    "code": "sensitive_input_blocked",
                    "detail": "provide redacted counts and rule ids only",
                }
            ],
            "evidence": ["input_rejected_before_processing"],
            "read_only": True,
            "side_effects": [],
        }
    issues: list[dict[str, str]] = []
    if not isinstance(summary, dict):
        issues.append({"code": "missing_finding_summary", "detail": "finding_summary is required"})
        summary = {}
    if summary.get("redacted") is not True:
        issues.append(
            {"code": "redaction_unproven", "detail": "fixture must declare redacted=true"}
        )
    if int(summary.get("prohibited_hits") or 0) > 0:
        issues.append(
            {
                "code": "prohibited_hit_detected",
                "detail": "prohibited findings require immediate block",
            }
        )
    if int(summary.get("high_severity_count") or 0) > 0:
        issues.append(
            {"code": "high_severity_finding", "detail": "high-severity findings require review"}
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "redacted finding summary is clear"
        if approved
        else "security finding summary requires review",
        "issues": issues,
        "evidence": [
            "fixture_only",
            "redacted_counts_only",
            "no_repository_scan",
            "no_secret_output",
        ],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
