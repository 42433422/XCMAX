#!/usr/bin/env python3
"""Bounded cleanup for successful FHD releases and rollback backups."""

from __future__ import annotations

import argparse
import re
import shutil
import time
from pathlib import Path

_RELEASE_RE = re.compile(r"^fhd-full-[A-Za-z0-9._-]+\.tar\.gz$")
_PART_RE = re.compile(r"^(?:fhd-full-[A-Za-z0-9._-]+|fhd-api-image)\.tar\.gz\.part$")
_BACKUP_RE = re.compile(r"^pre-\d{8}-\d{6}$")


def _safe_directory(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path == Path(path.anchor) or len(path.parts) < 3:
        raise ValueError(f"refusing broad cleanup target: {path}")
    return path


def prune_release_cache(
    release_dir: str | Path,
    *,
    current_artifact: str,
    retain_releases: int = 8,
    part_max_age_hours: int = 24,
    now: float | None = None,
) -> dict[str, list[str]]:
    root = _safe_directory(release_dir)
    if not root.is_dir():
        return {"removed_releases": [], "removed_partials": []}
    retain = max(2, int(retain_releases))
    clock = float(now if now is not None else time.time())
    releases = sorted(
        (
            item
            for item in root.iterdir()
            if item.is_file() and not item.is_symlink() and _RELEASE_RE.fullmatch(item.name)
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    keep_names = {current_artifact}
    keep_names.update(item.name for item in releases[:retain])
    removed_releases: list[str] = []
    for item in releases:
        if item.name in keep_names:
            continue
        item.unlink()
        removed_releases.append(item.name)

    cutoff = clock - max(1, int(part_max_age_hours)) * 3600
    removed_partials: list[str] = []
    for item in root.iterdir():
        if (
            item.is_file()
            and not item.is_symlink()
            and _PART_RE.fullmatch(item.name)
            and item.stat().st_mtime < cutoff
        ):
            item.unlink()
            removed_partials.append(item.name)
    return {
        "removed_releases": sorted(removed_releases),
        "removed_partials": sorted(removed_partials),
    }


def prune_backups(backup_dir: str | Path, *, retain_backups: int = 5) -> list[str]:
    root = _safe_directory(backup_dir)
    if not root.is_dir():
        return []
    backups = sorted(
        (
            item
            for item in root.iterdir()
            if item.is_dir() and not item.is_symlink() and _BACKUP_RE.fullmatch(item.name)
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for item in backups[max(2, int(retain_backups)) :]:
        shutil.rmtree(item)
        removed.append(item.name)
    return sorted(removed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--current-artifact", required=True)
    parser.add_argument("--retain-releases", type=int, default=8)
    parser.add_argument("--retain-backups", type=int, default=5)
    parser.add_argument("--part-max-age-hours", type=int, default=24)
    args = parser.parse_args()

    releases = prune_release_cache(
        args.release_dir,
        current_artifact=args.current_artifact,
        retain_releases=args.retain_releases,
        part_max_age_hours=args.part_max_age_hours,
    )
    backups = prune_backups(args.backup_dir, retain_backups=args.retain_backups)
    print(
        "cleanup "
        f"releases={len(releases['removed_releases'])} "
        f"partials={len(releases['removed_partials'])} "
        f"backups={len(backups)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
