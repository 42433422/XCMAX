"""读取 AUDIT_LOG_PATH JSON Lines 审计日志（分页）。"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any

from app.utils.audit_events import audit_log_path


def _load_all_records() -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []

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
    records.reverse()
    return records


def list_audit_log_entries(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    path = audit_log_path()
    if not path or not os.path.isfile(path):
        return {"items": [], "total": 0, "path_configured": bool(path)}

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    records = _load_all_records()
    total = len(records)
    page = records[offset : offset + limit]
    return {"items": page, "total": total, "path_configured": True}


def export_audit_log_csv(*, limit: int = 500) -> str:
    """导出最近 N 条审计记录为 CSV 文本（管理员下载用）。"""
    limit = max(1, min(int(limit), 2000))
    records = _load_all_records()[:limit]
    if not records:
        return "action,timestamp,success,user_id,ip\n"

    fieldnames: list[str] = []
    for row in records:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in records:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return buf.getvalue()
