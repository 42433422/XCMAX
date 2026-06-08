from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_audit_logger = logging.getLogger("audit")


def audit_log(
    event_type: str,
    user_id: int | None,
    ip_address: str,
    details: dict | None = None,
    success: bool = True,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "user_id": user_id,
        "ip_address": ip_address,
        "details": details or {},
        "success": success,
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False))
