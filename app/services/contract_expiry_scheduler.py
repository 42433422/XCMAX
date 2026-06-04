"""合同到期扫描定时任务（可选启用 CONTRACT_EXPIRY_CRON_ENABLED=1）。"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def run_contract_expiry_scan(*, days_ahead: int = 30, dry_run: bool = False) -> dict[str, Any]:
    from app.services.contract_lifecycle import notify_contract_expiry_items, scan_contract_expiry

    scan = scan_contract_expiry(days_ahead=days_ahead)
    items = list(scan.get("items") or [])
    notify = notify_contract_expiry_items(items, dry_run=dry_run)
    return {"scan": scan, "notify": notify}


def maybe_run_contract_expiry_cron() -> dict[str, Any] | None:
    if (os.environ.get("CONTRACT_EXPIRY_CRON_ENABLED") or "").strip() not in ("1", "true", "yes"):
        return None
    days = int(os.environ.get("CONTRACT_EXPIRY_DAYS_AHEAD") or "30")
    logger.info("contract_expiry cron scan days_ahead=%s", days)
    return run_contract_expiry_scan(days_ahead=days, dry_run=False)
