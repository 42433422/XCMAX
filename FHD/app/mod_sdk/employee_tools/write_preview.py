"""Reversible snapshots and diff previews for employee file writes.

Snapshot metadata and the original bytes live under ``MODSTORE_RUNTIME_DIR``
(falling back to the system temp directory). Undo refuses to overwrite a file
that changed after the recorded write.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "build_unified_diff",
    "read_snapshot",
    "restore_snapshot",
    "save_snapshot",
    "snapshot_root",
]

_MAX_DIFF_LINES = 200
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


def snapshot_root() -> Path:
    base = os.environ.get("MODSTORE_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "write-snapshots"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_unified_diff(
    rel_path: str, before: str, after: str, *, max_lines: int = _MAX_DIFF_LINES
) -> tuple[list[str], bool]:
    """Return a unified diff and whether it was truncated."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    return lines[:max_lines], len(lines) > max_lines


def save_snapshot(rel_path: str, before: str | None, after: str) -> dict[str, Any]:
    """Persist the pre-write content; returns metadata including ``snapshot_id``."""
    root = snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    snapshot_id = uuid.uuid4().hex
    (root / f"{snapshot_id}.bak").write_text(before or "", encoding="utf-8")
    meta = {
        "snapshot_id": snapshot_id,
        "path": rel_path,
        "existed": before is not None,
        "before_sha256": _sha256(before) if before is not None else "",
        "after_sha256": _sha256(after),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (root / f"{snapshot_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def read_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    meta_path = snapshot_root() / f"{snapshot_id}.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def restore_snapshot(snapshot_id: str, target: Path) -> dict[str, Any]:
    """Restore ``target`` to the snapshot; fail closed when the file changed since."""
    meta = read_snapshot(snapshot_id)
    if meta is None:
        return {"ok": False, "error": "快照不存在或已损坏"}
    current = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    if current is None or _sha256(current) != str(meta.get("after_sha256") or ""):
        return {"ok": False, "error": "文件在写入后又被修改，已拒绝撤销"}
    backup = snapshot_root() / f"{snapshot_id}.bak"
    try:
        if meta.get("existed"):
            target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            target.unlink(missing_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"撤销失败: {exc}"}
    return {"ok": True, "path": str(meta.get("path") or ""), "restored": True}


def snapshot_payload(rel_path: str, before: str | None, after: str) -> dict[str, Any]:
    """Diff plus snapshot metadata for a single write, omitting oversized snapshots."""
    diff, truncated = build_unified_diff(rel_path, before or "", after)
    if before is not None and len(before.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
        return {"diff": diff, "diff_truncated": truncated, "snapshot_skipped": "文件过大"}
    meta = save_snapshot(rel_path, before, after)
    return {
        "diff": diff,
        "diff_truncated": truncated,
        "snapshot_id": meta["snapshot_id"],
    }
