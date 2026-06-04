"""
应用层审计事件写入（与 HTTP 中间件 JSON Lines 格式对齐）。

供 auth_service、RBAC、Mod SDK 等在非 HTTP 路径记录敏感操作。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()


def audit_log_path() -> str:
    return (os.environ.get("AUDIT_LOG_PATH") or "").strip()


def append_audit_event(record: dict[str, Any]) -> None:
    """追加一行 JSON 到 ``AUDIT_LOG_PATH``（未配置时静默跳过）。"""
    path = audit_log_path()
    if not path:
        return
    if "ts" not in record:
        record = {**record, "ts": datetime.now(timezone.utc).isoformat()}
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _WRITE_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        logger.debug("append_audit_event failed: %s", exc)


def write_sensitive_audit_event(
    *,
    action: str,
    actor: str | int | None = None,
    success: bool = True,
    request_id: str | None = None,
    client_host: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """写入带 ``sensitive`` / ``action`` 的应用层审计行。"""
    record: dict[str, Any] = {
        "sensitive": True,
        "action": str(action or "")[:64],
        "success": success,
        "source": "application",
    }
    if actor is not None:
        record["actor"] = str(actor)[:64]
    if request_id:
        record["request_id"] = request_id[:128]
    if client_host:
        record["client_host"] = client_host[:128]
    if details:
        record["details"] = details
    append_audit_event(record)
