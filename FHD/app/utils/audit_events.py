"""AUDIT_LOG_PATH 解析（audit_log_reader 用）。"""

from __future__ import annotations

import os


def audit_log_path() -> str | None:
    path = (os.environ.get("AUDIT_LOG_PATH") or "").strip()
    return path or None
