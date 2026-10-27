"""Scheduled reconciliation and safe escalation of customer-value evidence."""

from __future__ import annotations

import os
from typing import Any

from modstore_server.customer_value_escalation import (
    ensure_customer_value_gap_escalation,
)
from modstore_server.customer_value_reconciler import reconcile_paid_customer_value


def _window_days() -> int:
    try:
        configured = int(os.environ.get("MODSTORE_CUSTOMER_VALUE_WINDOW_DAYS", "90"))
    except ValueError:
        configured = 90
    return max(1, min(configured, 3650))


def reconcile_customer_value_with_escalation() -> dict[str, Any]:
    """Reconcile authoritative value first, then create only internal approval work."""

    window_days = _window_days()
    reconciled = reconcile_paid_customer_value(
        window_days=window_days,
        include_evidence=True,
    )
    if reconciled.get("source_ready") is not True:
        return reconciled
    escalation = ensure_customer_value_gap_escalation(
        evidence=reconciled.get("evidence"),
        window_days=window_days,
    )
    return {**reconciled, "escalation": escalation}


__all__ = ["reconcile_customer_value_with_escalation"]
