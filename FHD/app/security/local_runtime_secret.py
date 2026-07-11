"""Read the local MODstore/FHD shared secret without sourcing a shell file.

The daily runtime already writes a private env snapshot under Application
Support.  Desktop FHD is not always launched by the same launchd job, so its
process environment may not contain the shared key.  Only a small allow-list of
keys is read, and an insecure or foreign-owned snapshot is rejected.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

_ALLOWED_KEYS = frozenset(
    {
        "MODSTORE_INTERNAL_API_KEY",
        "XCAGI_MARKET_INTERNAL_API_KEY",
        "XCAGI_CS_INTAKE_LINK_SECRET",
    }
)


def _snapshot_path() -> Path:
    configured = str(os.environ.get("MODSTORE_DAILY_ENV_SNAPSHOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "XCMAX" / "modstore-daily.env"


def _safe_snapshot(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or stat.st_size > 2_000_000:
        return False
    if hasattr(os, "getuid") and stat.st_uid != os.getuid():
        return False
    # Secrets must not be readable or writable by group/other users.
    return (stat.st_mode & 0o077) == 0


def _decode_shell_value(raw: str) -> str:
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError:
        return ""
    return parts[0] if len(parts) == 1 else ""


def local_runtime_secret(*keys: str) -> str:
    requested = [key for key in keys if key in _ALLOWED_KEYS]
    for key in requested:
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value

    path = _snapshot_path()
    if not requested or not _safe_snapshot(path):
        return ""
    wanted = set(requested)
    found: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in wanted:
                    continue
                decoded = _decode_shell_value(value.strip()).strip()
                if decoded:
                    found[key] = decoded
    except OSError:
        return ""
    for key in requested:
        if found.get(key):
            return found[key]
    return ""


__all__ = ["local_runtime_secret"]
