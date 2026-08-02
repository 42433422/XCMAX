"""Runtime boundary between the desktop product and management-side employees."""

from __future__ import annotations

import os


def desktop_admin_employee_runtime_disabled() -> bool:
    """Desktop product SKUs must not start management employee triggers or cron jobs."""
    desktop_mode = os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower()
    product_sku = os.environ.get("XCAGI_PRODUCT_SKU", "").strip()
    return desktop_mode in {"1", "true", "yes", "on"} and bool(product_sku)


def desktop_employee_runtime_status() -> dict[str, object]:
    return {
        "registered": [],
        "active_employees": [],
        "event_types": [],
        "running": False,
        "disabled_reason": "desktop_product_boundary",
    }


__all__ = ["desktop_admin_employee_runtime_disabled", "desktop_employee_runtime_status"]
