"""Fixture-only Nginx check-receipt auditor; never reads or reloads Nginx."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("config_check_receipt")
    issues: list[dict[str, str]] = []
    if not isinstance(receipt, dict):
        issues.append(
            {"code": "missing_config_check_receipt", "detail": "config_check_receipt is required"}
        )
        receipt = {}
    if receipt.get("syntax_ok") is not True:
        issues.append({"code": "syntax_not_proven", "detail": "supplied syntax check must pass"})
    if int(receipt.get("certificate_days_remaining") or 0) < 30:
        issues.append(
            {"code": "certificate_expiry_near", "detail": "certificate threshold is 30 days"}
        )
    if receipt.get("route_drift") is not False:
        issues.append(
            {"code": "route_drift_present", "detail": "supplied receipt reports route drift"}
        )
    if receipt.get("production_change_requested") is not False:
        issues.append(
            {
                "code": "production_change_not_excluded",
                "detail": "fixture must exclude production mutation",
            }
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied Nginx check receipt is healthy"
        if approved
        else "Nginx receipt needs review",
        "issues": issues,
        "evidence": ["fixture_only", "no_config_read", "no_shell", "no_reload"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
