"""Approval-evidence parsing used by the autonomy guard SSOT."""

from __future__ import annotations

import os
from typing import Any

from app.domain.autonomy.risk_types import RiskLevel, truthy


def human_approval_evidence(context: dict[str, Any]) -> tuple[bool, str]:
    approver = str(context.get("approved_by") or context.get("approver") or "").strip()
    if truthy(context.get("human_approved")) and approver:
        return True, approver
    return False, ""


def approval_evidence(context: dict[str, Any], risk: RiskLevel) -> tuple[bool, str]:
    approved, approver = human_approval_evidence(context)
    if approved:
        return approved, approver
    approver = str(context.get("approved_by") or context.get("approver") or "").strip()
    if risk == RiskLevel.MEDIUM and truthy(context.get("allow_medium_risk")):
        return True, approver or "legacy_explicit_runtime_approval"
    if risk == RiskLevel.HIGH and truthy(context.get("allow_high_risk_real_run")):
        configured = (
            os.environ.get("FHD_RISK_HIGH_GATE_TOKEN")
            or os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN")
            or ""
        ).strip()
        supplied = str(context.get("high_risk_gate_token") or "").strip()
        if configured and supplied and supplied == configured:
            return True, approver or "legacy_high_risk_gate"
    return False, ""


__all__ = ["approval_evidence", "human_approval_evidence"]
