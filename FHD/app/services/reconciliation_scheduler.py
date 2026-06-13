"""对账调度占位（operations-line API SSOT；完整调度器待独立迭代）。"""

from __future__ import annotations

from typing import Any


def get_reconciliation_status() -> dict[str, Any]:
    return {"last_run": None, "auto_confirm_enabled": False, "success": True}


def run_reconciliation_preview_cycle() -> dict[str, Any]:
    return {"success": True, "dry_run": True, "preview": True}


def run_reconciliation_full_cycle() -> dict[str, Any]:
    return {"success": True, "dry_run": False}
