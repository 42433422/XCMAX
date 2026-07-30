"""Bounded retention for automatic XCAGI desktop database backups."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Keep one current recovery point plus one weekly/recent fallback by default.
# A count bound is necessary because a production desktop database can be several
# gigabytes; age-only retention can fill a workstation before the cutoff expires.
DEFAULT_LOCAL_BACKUP_KEEP = 2
DEFAULT_DAILY_RETENTION_DAYS = 7
DEFAULT_WEEKLY_RETENTION_DAYS = 28
WEEKLY_MARKER = "weekly"
AUTOMATIC_BACKUP_RE = re.compile(r"^xcagi-(?P<version>.+?)(?:-weekly)?-(?P<stamp>\d{14})\.db$")


def configured_local_backup_keep() -> int:
    """Return a validated local automatic-backup count limit."""
    raw = (os.environ.get("XCAGI_LOCAL_BACKUP_KEEP") or "").strip()
    if not raw:
        return DEFAULT_LOCAL_BACKUP_KEEP
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "invalid XCAGI_LOCAL_BACKUP_KEEP=%r; using %d",
            raw,
            DEFAULT_LOCAL_BACKUP_KEEP,
        )
        return DEFAULT_LOCAL_BACKUP_KEEP
    if value < 1 or value > 100:
        logger.warning(
            "XCAGI_LOCAL_BACKUP_KEEP must be between 1 and 100; using %d",
            DEFAULT_LOCAL_BACKUP_KEEP,
        )
        return DEFAULT_LOCAL_BACKUP_KEEP
    return value


def _pending_rollback_backup(backups_dir: Path) -> Path | None:
    """Resolve a pending Electron rollback backup only when it is in backups_dir."""
    marker = backups_dir.parent / "rollback-marker.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        raw_path = str(payload.get("databaseBackupPath") or "").strip()
        if not raw_path:
            return None
        candidate = Path(raw_path).expanduser().resolve()
        resolved_dir = backups_dir.resolve()
        if candidate.parent != resolved_dir:
            logger.warning(
                "ignoring rollback backup outside XCAGI backups directory: %s",
                candidate,
            )
            return None
        return candidate
    except (OSError, ValueError, TypeError):
        return None


def _remove_backup_family(path: Path) -> bool:
    """Remove a backup and SQLite sidecars, but only after the database unlink works."""
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        logger.warning("failed to clean up automatic backup %s: %s", path, exc)
        return False

    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("failed to clean up backup sidecar %s: %s", sidecar, exc)
    logger.info("cleaned up automatic backup: %s", path.name)
    return True


def cleanup_local_backups(
    backups_dir: Path,
    *,
    keep: int | None = None,
    retention_days: int = DEFAULT_DAILY_RETENTION_DAYS,
    weekly_retention_days: int = DEFAULT_WEEKLY_RETENTION_DAYS,
    protected: Iterable[Path] = (),
    now: datetime | None = None,
) -> list[Path]:
    """Bound automatic backups by count while preserving recovery invariants.

    The newest in-retention automatic backup is retained. If a recent weekly
    backup exists, it occupies one of the retained slots. A backup referenced by
    ``rollback-marker.json`` and explicit ``protected`` paths are retained in
    addition to the normal count limit. Malformed names and manual ``*.bak``
    files are never touched.
    """
    if not backups_dir.is_dir():
        return []

    limit = configured_local_backup_keep() if keep is None else keep
    if limit < 1:
        raise ValueError("keep must be at least 1")

    entries: list[tuple[Path, float, bool]] = []
    for path in backups_dir.glob("xcagi-*.db"):
        if AUTOMATIC_BACKUP_RE.fullmatch(path.name) is None:
            continue
        try:
            entries.append((path, path.stat().st_mtime, WEEKLY_MARKER in path.stem))
        except OSError as exc:
            logger.warning("failed to inspect automatic backup %s: %s", path, exc)
    entries.sort(key=lambda item: (item[1], item[0].name), reverse=True)
    if not entries:
        return []

    current = now or datetime.now()
    weekly_cutoff = (current - timedelta(days=weekly_retention_days)).timestamp()
    daily_cutoff = (current - timedelta(days=retention_days)).timestamp()

    mandatory: set[Path] = set()
    for candidate in protected:
        try:
            resolved = candidate.resolve()
            if resolved.parent == backups_dir.resolve():
                mandatory.add(resolved)
        except OSError:
            continue
    rollback_backup = _pending_rollback_backup(backups_dir)
    if rollback_backup is not None:
        mandatory.add(rollback_backup)

    policy_keep: set[Path] = set()
    newest_path, newest_mtime, newest_is_weekly = entries[0]
    newest_cutoff = weekly_cutoff if newest_is_weekly else daily_cutoff
    if newest_mtime >= newest_cutoff:
        policy_keep.add(newest_path.resolve())
    recent_weekly = next(
        (
            path.resolve()
            for path, mtime, is_weekly in entries
            if is_weekly and mtime >= weekly_cutoff
        ),
        None,
    )
    if recent_weekly is not None and len(policy_keep) < limit:
        policy_keep.add(recent_weekly)
    for path, mtime, is_weekly in entries:
        if len(policy_keep) >= limit:
            break
        cutoff = weekly_cutoff if is_weekly else daily_cutoff
        if mtime >= cutoff:
            policy_keep.add(path.resolve())

    keep_paths = mandatory | policy_keep
    removed: list[Path] = []
    for path, _mtime, _is_weekly in reversed(entries):
        if path.resolve() in keep_paths:
            continue
        if _remove_backup_family(path):
            removed.append(path)
    return removed
