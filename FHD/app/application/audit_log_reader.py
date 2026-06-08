"""读取 AUDIT_LOG_PATH JSON Lines 审计日志（分页）。"""

from __future__ import annotations

import json
import os
from typing import Any

from app.utils.audit_events import audit_log_path


def list_audit_log_entries(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    path = audit_log_path()
    if not path or not os.path.isfile(path):
        return {"items": [], "total": 0, "path_configured": bool(path)}

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return {"items": [], "total": 0, "path_configured": True, "read_error": True}

    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
        except json.JSONDecodeError:
            continue

    total = len(records)
    # 最新在前
    records.reverse()
    page = records[offset : offset + limit]
    return {"items": page, "total": total, "path_configured": True}
