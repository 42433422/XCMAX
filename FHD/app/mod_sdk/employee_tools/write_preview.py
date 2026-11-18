"""Reversible snapshots and diff previews for employee file writes.

Snapshot metadata and the original bytes live under ``MODSTORE_RUNTIME_DIR``
(falling back to the system temp directory). Undo refuses to overwrite a file
that changed after the recorded write.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime
from itertools import islice
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
logger = logging.getLogger(__name__)


def snapshot_root(target: Path, context: dict[str, Any]) -> Path:
    base = os.environ.get("MODSTORE_RUNTIME_DIR") or tempfile.gettempdir()
    scope = [
        str(Path(context.get("workspace_root") or os.getcwd()).resolve()),
        str(target.resolve()),
        *(str(context.get(key) or "") for key in ("user_id", "tenant_id", "mod_id")),
    ]
    namespace = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
    return Path(base) / "write-snapshots" / namespace


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_unified_diff(
    rel_path: str, before: str, after: str, *, max_lines: int = _MAX_DIFF_LINES
) -> tuple[list[str], bool]:
    """Return a unified diff and whether it was truncated."""
    lines = list(
        islice(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            ),
            max_lines + 1,
        )
    )
    return lines[:max_lines], len(lines) > max_lines


def save_snapshot(
    rel_path: str,
    before: bytes | None,
    after: bytes | None,
    *,
    target: Path,
    context: dict[str, Any],
    pending: bool = False,
) -> dict[str, Any]:
    """Persist the pre-write content; returns metadata including ``snapshot_id``."""
    root = snapshot_root(target, context)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot_id = uuid.uuid4().hex
    (root / f"{snapshot_id}.bak").write_bytes(before or b"")
    meta = {
        "snapshot_id": snapshot_id,
        "path": rel_path,
        "existed": before is not None,
        "before_sha256": _sha256(before) if before is not None else "",
        "after_sha256": _sha256(after) if after is not None else None,
        "pending": pending,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (root / f"{snapshot_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def read_snapshot(
    snapshot_id: str, *, target: Path, context: dict[str, Any]
) -> dict[str, Any] | None:
    if len(snapshot_id) != 32 or any(char not in "0123456789abcdef" for char in snapshot_id):
        return None
    meta_path = snapshot_root(target, context) / f"{snapshot_id}.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def restore_snapshot(snapshot_id: str, target: Path, *, context: dict[str, Any]) -> dict[str, Any]:
    """Restore ``target`` to the snapshot; fail closed when the file changed since."""
    meta = read_snapshot(snapshot_id, target=target, context=context)
    if meta is None or meta.get("pending"):
        return {"ok": False, "error": "快照不存在或已损坏"}
    try:
        current = target.read_bytes() if target.is_file() else None
        digest = _sha256(current) if current is not None else None
        if digest != meta.get("after_sha256"):
            return {"ok": False, "error": "文件在写入后又被修改，已拒绝撤销"}
        if meta.get("existed"):
            backup = (snapshot_root(target, context) / f"{snapshot_id}.bak").read_bytes()
            if _sha256(backup) != meta.get("before_sha256"):
                return {"ok": False, "error": "快照原始内容已损坏，已拒绝撤销"}
            target.write_bytes(backup)
        else:
            target.unlink(missing_ok=True)
    except OSError:
        logger.warning("Write snapshot restoration failed", exc_info=True)
        return {"ok": False, "error": "撤销失败，请检查文件权限或稍后重试"}
    return {"ok": True, "path": str(meta.get("path") or ""), "restored": True}


def snapshot_payload(
    rel_path: str,
    before: bytes | None,
    after: bytes | None,
    *,
    target: Path,
    context: dict[str, Any],
    prepared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diff plus snapshot metadata for a single write, omitting oversized snapshots."""
    diff, truncated = build_unified_diff(
        rel_path,
        (before or b"").decode("utf-8", errors="replace"),
        (after or b"").decode("utf-8", errors="replace"),
    )
    if before is not None and len(before) > _MAX_SNAPSHOT_BYTES:
        return {"diff": diff, "diff_truncated": truncated, "snapshot_skipped": "文件过大"}
    meta = prepared or save_snapshot(rel_path, before, after, target=target, context=context)
    if prepared:
        meta.update(after_sha256=_sha256(after) if after is not None else None, pending=False)
        (snapshot_root(target, context) / f"{meta['snapshot_id']}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    return {
        "diff": diff,
        "diff_truncated": truncated,
        "snapshot_id": meta["snapshot_id"],
    }
