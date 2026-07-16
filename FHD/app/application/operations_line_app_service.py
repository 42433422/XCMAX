"""Application facade for operations-line health / signoff / reconciliation."""

from __future__ import annotations

from typing import Any


def compute_operations_health() -> dict[str, Any]:
    from app.services.operations_line_bridge import compute_operations_health as impl

    return impl()


def run_contract_expiry_scan(*, days_ahead: int = 30, dry_run: bool = True) -> dict[str, Any]:
    from app.services.contract_lifecycle import run_contract_expiry_scan as impl

    return impl(days_ahead=days_ahead, dry_run=dry_run)


def signoff_backend_info() -> dict[str, Any]:
    from app.services.user_cs_delivery_signoff import signoff_backend_info as impl

    return impl()


def get_reconciliation_status() -> dict[str, Any]:
    from app.services.reconciliation_scheduler import get_reconciliation_status as impl

    return impl()


def run_reconciliation(*, dry_run: bool = False) -> dict[str, Any]:
    from app.services.reconciliation_scheduler import (
        run_reconciliation_full_cycle,
        run_reconciliation_preview_cycle,
    )

    return run_reconciliation_preview_cycle() if dry_run else run_reconciliation_full_cycle()


__all__ = [
    "compute_operations_health",
    "get_reconciliation_status",
    "run_contract_expiry_scan",
    "run_reconciliation",
    "signoff_backend_info",
]
