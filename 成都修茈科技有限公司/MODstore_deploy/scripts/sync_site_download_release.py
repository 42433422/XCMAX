#!/usr/bin/env python3
"""Preserve published desktop pointers during an unrelated server deployment.

Only an explicitly authorized desktop publisher may promote artifacts. Server SHA,
version ordering, build mtime and manual acceptance are never publication authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MIRRORS = (
    "MODstore_deploy/market/public",
    "MODstore_deploy/market/dist",
    "corp-butler",
)
POINTERS = ("download-release.json", "download-windows-hotfix.json")


def preserve(
    site_root: Path,
    published_site_root: Path,
    published_hotfix: Path | None = None,
    *,
    check: bool = False,
) -> None:
    # Validate the complete source set before changing the staged tree. Preserve bytes,
    # including unresolved legacy identity; do not turn preservation into acceptance.
    if not site_root.is_dir():
        raise ValueError(f"missing staged site: {site_root}")
    snapshots = {}
    for name in POINTERS:
        source = (
            published_hotfix
            if name == POINTERS[1] and published_hotfix
            else published_site_root / name
        )
        if not source.exists() and name != POINTERS[0]:
            snapshots[name] = None
            continue
        content = source.read_bytes()
        data = json.loads(content)
        if not isinstance(data, dict) or not data:
            raise ValueError(f"invalid published pointer: {source}")
        snapshots[name] = content
    for name, content in snapshots.items():
        for root in (site_root, *(site_root / mirror for mirror in MIRRORS)):
            if not root.is_dir():
                continue
            target = root / name
            if target.is_symlink() or not root.resolve().is_relative_to(
                site_root.resolve()
            ):
                raise ValueError(
                    f"prepared pointer must be local, not a symlink: {target}"
                )
            if check:
                actual = target.read_bytes() if target.is_file() else None
                if actual != content or (content is None and target.exists()):
                    raise ValueError(
                        f"stale prepared desktop pointer; explicit reconciliation required: {target}"
                    )
            elif content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
                if target.read_bytes() != content:
                    raise OSError(f"pointer preservation failed: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--published-site-root", type=Path, required=True)
    parser.add_argument("--published-hotfix", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only byte/absence parity before activation or rollback",
    )
    args = parser.parse_args()
    try:
        preserve(
            args.site_root,
            args.published_site_root,
            args.published_hotfix,
            check=args.check,
        )
    except (OSError, ValueError) as exc:
        print(
            f"[error] cannot preserve public desktop pointers: {exc}", file=sys.stderr
        )
        return 1
    print("[ok] public desktop pointers preserved; no publication or identity change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
