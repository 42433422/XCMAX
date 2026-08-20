#!/usr/bin/env python3
"""Purge local upload temp files older than TTL (default 7 days)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TTL_DAYS = 7

TARGET_DIRS = [
    FHD_ROOT / "uploads" / "temp",
    FHD_ROOT / "workspace" / "uploads" / "chat",
    FHD_ROOT / "workspace" / "uploads" / "tutorial",
]


def _purge_dir(root: Path, *, cutoff: float, dry_run: bool) -> list[str]:
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        rel = str(path.relative_to(FHD_ROOT))
        if dry_run:
            removed.append(rel)
            continue
        try:
            path.unlink()
            removed.append(rel)
        except OSError:
            pass
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge aged local upload temp files")
    parser.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--data-dir",
        default="",
        help="Optional desktop userData root; also purges uploads under it if present",
    )
    args = parser.parse_args()
    cutoff = time.time() - max(1, args.ttl_days) * 86400
    dirs = list(TARGET_DIRS)
    if args.data_dir.strip():
        data = Path(args.data_dir).expanduser().resolve()
        dirs.extend(
            [
                data / "uploads" / "temp",
                data / "workspace" / "uploads" / "chat",
                data / "workspace" / "uploads" / "tutorial",
            ]
        )
    all_removed: list[str] = []
    for d in dirs:
        all_removed.extend(_purge_dir(d, cutoff=cutoff, dry_run=args.dry_run))
    mode = "would remove" if args.dry_run else "removed"
    print(f"{mode} {len(all_removed)} file(s) (ttl={args.ttl_days}d)")
    for item in all_removed[:50]:
        print(f"  - {item}")
    if len(all_removed) > 50:
        print(f"  ... and {len(all_removed) - 50} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
