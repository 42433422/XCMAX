"""Bounded tail reads for append-only self-maintenance JSONL ledgers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_MAX_RECORD_BYTES = 1024 * 1024
DEFAULT_MAX_SCAN_BYTES = 64 * 1024 * 1024
DEFAULT_READ_CHUNK_BYTES = 64 * 1024


def _json_object(raw: bytes) -> Optional[Dict[str, Any]]:
    if not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl_tail(
    path: Path,
    *,
    limit: int,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
    max_scan_bytes: int = DEFAULT_MAX_SCAN_BYTES,
    chunk_size: int = DEFAULT_READ_CHUNK_BYTES,
) -> List[Dict[str, Any]]:
    """Return the newest valid objects without unbounded record or file scans.

    Records larger than ``max_record_bytes`` are discarded while their chunks
    are scanned; their complete bytes are never retained. ``max_scan_bytes``
    also bounds synchronous I/O when a ledger contains too few valid rows.
    Returned rows preserve their original chronological order.
    """

    if limit <= 0 or max_record_bytes <= 0 or max_scan_bytes <= 0 or chunk_size <= 0:
        return []
    if not path.exists():
        return []

    rows: List[Dict[str, Any]] = []
    fragment = b""
    fragment_oversized = False
    chunk_size = min(chunk_size, max_record_bytes, max_scan_bytes)

    def prepend_fragment(piece: bytes) -> None:
        nonlocal fragment, fragment_oversized
        if fragment_oversized:
            return
        if len(piece) > max_record_bytes - len(fragment):
            fragment = b""
            fragment_oversized = True
            return
        fragment = piece + fragment

    def append_row(raw: bytes) -> None:
        if len(raw) > max_record_bytes:
            return
        value = _json_object(raw)
        if value is not None:
            rows.append(value)

    try:
        file_size = path.stat().st_size
        scan_start = max(0, file_size - max_scan_bytes)
        position = file_size
        with path.open("rb") as fh:
            while position > scan_start and len(rows) < limit:
                read_start = max(scan_start, position - chunk_size)
                fh.seek(read_start)
                chunk = fh.read(position - read_start)
                if not chunk:
                    break
                position = read_start
                parts = chunk.split(b"\n")
                if len(parts) == 1:
                    prepend_fragment(parts[0])
                    continue

                prepend_fragment(parts[-1])
                if not fragment_oversized:
                    append_row(fragment)
                if len(rows) >= limit:
                    break

                for raw in reversed(parts[1:-1]):
                    append_row(raw)
                    if len(rows) >= limit:
                        break

                fragment = parts[0] if len(parts[0]) <= max_record_bytes else b""
                fragment_oversized = len(parts[0]) > max_record_bytes

            if len(rows) < limit and scan_start == 0 and not fragment_oversized and fragment:
                append_row(fragment)
    except OSError:
        return []

    rows.reverse()
    return rows
