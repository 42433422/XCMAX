"""Fixture-only iOS release-candidate receipt auditor; never uploads."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("release_candidate")
    issues: list[dict[str, str]] = []
    if not isinstance(candidate, dict):
        issues.append(
            {"code": "missing_release_candidate", "detail": "release_candidate is required"}
        )
        candidate = {}
    for field in (
        "archive_passed",
        "codesign_verified",
        "device_install_passed",
        "core_flow_passed",
    ):
        if candidate.get(field) is not True:
            issues.append(
                {
                    "code": f"{field}_missing",
                    "detail": f"{field} must be proven by the supplied receipt",
                }
            )
    if candidate.get("app_store_upload_requested") is not False:
        issues.append(
            {
                "code": "store_upload_not_excluded",
                "detail": "fixture must explicitly exclude App Store upload",
            }
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied iOS candidate receipt is complete"
        if approved
        else "iOS candidate needs review",
        "issues": issues,
        "evidence": [
            "fixture_only",
            "receipt_audit",
            "no_archive",
            "no_install",
            "no_store_upload",
        ],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
