"""Deterministic marketing build-receipt auditor; never builds or writes files."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("build_receipt")
    issues: list[dict[str, str]] = []
    if not isinstance(receipt, dict):
        issues.append({"code": "missing_build_receipt", "detail": "build_receipt is required"})
        receipt = {}
    if str(receipt.get("build_status") or "") != "passed":
        issues.append(
            {"code": "build_not_passed", "detail": "supplied build status must be passed"}
        )
    pages = receipt.get("pages") if isinstance(receipt.get("pages"), list) else []
    if not pages:
        issues.append({"code": "pages_missing", "detail": "at least one output page is required"})
    missing = (
        receipt.get("assets_missing") if isinstance(receipt.get("assets_missing"), list) else []
    )
    if missing:
        issues.append(
            {"code": "assets_missing", "detail": "supplied receipt reports missing assets"}
        )
    responsive = (
        receipt.get("responsive_checks")
        if isinstance(receipt.get("responsive_checks"), list)
        else []
    )
    if not responsive or any(
        str(item.get("status") or "") != "passed" for item in responsive if isinstance(item, dict)
    ):
        issues.append(
            {
                "code": "responsive_checks_incomplete",
                "detail": "all supplied responsive checks must pass",
            }
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied marketing build receipt is complete"
        if approved
        else "marketing build receipt has gaps",
        "pages": [str(item) for item in pages],
        "issues": issues,
        "evidence": ["fixture_only", "receipt_audit", "no_build", "no_file_write"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
