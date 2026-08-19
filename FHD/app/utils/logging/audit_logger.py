"""Audit logging helpers."""

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.utils.logging.audit_events import append_audit_event
from app.utils.operational_errors import RECOVERABLE_ERRORS

_audit_logger = logging.getLogger("audit")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_audit_logger.addHandler(_handler)
_audit_logger.setLevel(logging.INFO)


def audit_log(
    event_type: str,
    user_id: Any = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
    success: bool = True,
    *,
    actor_id: Any = None,
    ip: str | None = None,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> int:
    """Write one audit event and return its process-unique numeric identifier.

    The keyword aliases support newer compliance routes while preserving the
    original positional API used by authentication services.
    """
    audit_id = time.time_ns()
    resolved_user_id = actor_id if actor_id is not None else user_id
    resolved_ip = ip if ip is not None else ip_address
    resolved_details = payload if payload is not None else (details or {})
    entry = {
        "audit_id": audit_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "user_id": resolved_user_id,
        "ip_address": resolved_ip,
        "details": resolved_details,
        "success": success,
        "severity": severity,
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    # 可选落盘（AUDIT_LOG_PATH 未配置即 no-op）；落盘失败绝不可中断主流程。
    try:
        append_audit_event(
            {
                "action": event_type,
                "audit_id": audit_id,
                "actor": resolved_user_id,
                "client_host": resolved_ip,
                "details": resolved_details,
                "success": success,
                "severity": severity,
            }
        )
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 审计副作用必须吞掉一切异常
        pass
    return audit_id
