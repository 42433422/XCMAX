"""Fixture-only payment bridge contract auditor; never calls a provider."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("contract_receipt")
    issues: list[dict[str, str]] = []
    if not isinstance(receipt, dict):
        issues.append(
            {"code": "missing_contract_receipt", "detail": "contract_receipt is required"}
        )
        receipt = {}
    required_fields = {str(item) for item in receipt.get("signature_fields", []) if str(item)}
    if not {"merchant_id", "order_id", "amount", "nonce", "signature"}.issubset(required_fields):
        issues.append(
            {
                "code": "signature_contract_incomplete",
                "detail": "required signature field names are missing",
            }
        )
    if receipt.get("idempotency_test_passed") is not True:
        issues.append(
            {"code": "idempotency_unproven", "detail": "callback idempotency test must pass"}
        )
    if receipt.get("real_charge_attempted") is not False:
        issues.append(
            {
                "code": "real_charge_not_excluded",
                "detail": "fixture must explicitly exclude a real charge",
            }
        )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied payment bridge contract is complete"
        if approved
        else "payment bridge contract needs review",
        "issues": issues,
        "evidence": ["fixture_only", "field_names_only", "no_payment_provider", "no_real_charge"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
