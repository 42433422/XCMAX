"""Give strategy the existing customer-value ledger's aggregate observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from modstore_server.customer_value_evidence import build_customer_value_evidence
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_COUNTS = (
    "verified_paid_count",
    "verified_paid_amount_cents",
    "customer_goal_count",
    "paid_delivery_count",
    "paid_acceptance_count",
    "complete_customer_count",
)
_STAGES = ("payment", "installation", "first_use", "outcome", "acceptance", "reuse")
_SOURCES = {"python_payment_orders", "java_postgresql_internal_api"}


def customer_value_context() -> dict[str, Any]:
    """Read facts only; observations never authorize outreach or customer acceptance."""
    result: dict[str, Any] = {
        "status": "unknown",
        "source_owner": "unavailable",
        "observed_at": datetime.now(UTC).isoformat(),
        "window_days": 90,
        "value_ledger_ready": False,
        "interpretation": "observed_customer_value_not_incremental_profit",
    }
    try:
        evidence = build_customer_value_evidence(window_days=90)
        owner = evidence.get("source_owner")
        if owner not in _SOURCES:
            return result
        result["source_owner"] = owner
        observed_at = datetime.fromisoformat(evidence["generated_at"])
        if observed_at.tzinfo is None or observed_at > datetime.now(UTC):
            return result
        result["observed_at"] = observed_at.astimezone(UTC).isoformat()
        if not all(
            evidence.get(key) is True
            for key in (
                "value_ledger_ready",
                "source_available",
                "source_authoritative",
                "append_only_store_available",
            )
        ):
            return result
        counts = {key: evidence.get(key) for key in _COUNTS}
        stages = {key: evidence.get("six_stage_counts", {}).get(key) for key in _STAGES}
        gaps = {
            key: evidence.get("lifecycle_gaps", {}).get(key, 0)
            for key in (*_STAGES, "sequence", "enterprise_subject")
        }
        if any(
            type(value) is not int or value < 0
            for value in (*counts.values(), *stages.values(), *gaps.values())
        ):
            return result
        return {
            **result,
            "status": "ok",
            "value_ledger_ready": True,
            **counts,
            "six_stage_counts": stages,
            "lifecycle_gaps": gaps,
            "desktop_release_source_available": evidence.get("desktop_release_source_available")
            is True,
        }
    except RECOVERABLE_ERRORS:
        return result
