import json
import logging
from datetime import UTC, datetime

from app.utils.audit_events import append_audit_event

_audit_logger = logging.getLogger("audit")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_audit_logger.addHandler(_handler)
_audit_logger.setLevel(logging.INFO)


def audit_log(event_type: str, user_id, ip_address, details, success: bool = True):
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "user_id": user_id,
        "ip_address": ip_address,
        "details": details,
        "success": success,
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    # 可选落盘（AUDIT_LOG_PATH 未配置即 no-op）；落盘失败绝不可中断主流程。
    try:
        append_audit_event(
            {
                "action": event_type,
                "actor": user_id,
                "client_host": ip_address,
                "details": details,
                "success": success,
            }
        )
    except Exception:  # noqa: BLE001 - 审计副作用必须吞掉一切异常
        pass
