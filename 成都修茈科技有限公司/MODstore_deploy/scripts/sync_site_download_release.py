#!/usr/bin/env python3
"""Publish the website download manifest for the exact product version being deployed.

The site reads ``/download-release.json`` from the immutable release tree, so the Git
copy (frozen at 1.0.0.1) would otherwise be served after every deploy.  Prefer the
release-managed pointer written by the desktop release flow; fall back to the release
SSOT ``FHD/config/download_release.json``.  Fail closed unless the published manifest's
version equals the product version.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

MIRRORS = ("MODstore_deploy/market/public", "MODstore_deploy/market/dist", "corp-butler")


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def matches(data: dict | None, version: str) -> bool:
    history = (data or {}).get("release_history")
    return bool(
        data
        and str(data.get("version_lock") or "") == version
        and isinstance(history, list)
        and history
        and isinstance(history[0], dict)
        and str(history[0].get("version") or "") == version
    )


def release_managed(release_root: Path, version: str) -> dict | None:
    builds = sorted(
        (release_root / "update/releases/builds" / version).glob("*/download-release.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in [*builds, release_root / f"xcagi-v{version}/download-release.json"]:
        data = _load(path)
        if matches(data, version):
            return data
    return None


def from_ssot(base: dict, ssot: dict, version: str, git_sha: str) -> dict:
    keys = ("version_lock", "download_version", "android_version", "android_git_sha")
    out = {**base, **{k: ssot[k] for k in keys if k in ssot}}
    out.update(release_history=ssot.get("release_history"), git_sha=git_sha, source="release_ssot")
    out["generated_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--release-root", type=Path, default=Path("/var/www"))
    args = parser.parse_args()
    pointer = args.site_root / "download-release.json"
    data = release_managed(args.release_root, args.version)
    if data is None:
        ssot = _load(args.ssot)
        if not matches(ssot, args.version):
            print(f"[error] release SSOT is not version {args.version}", file=sys.stderr)
            return 1
        data = from_ssot(_load(pointer) or {}, ssot, args.version, args.git_sha)
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for target in [pointer, *(args.site_root / m / pointer.name for m in MIRRORS)]:
        if target == pointer or target.parent.is_dir():
            target.write_text(rendered, encoding="utf-8")
            if not matches(_load(target), args.version):
                print(f"[error] {target} version != {args.version}", file=sys.stderr)
                return 1
    print(f"[ok] download-release.json = {args.version} ({data.get('source', 'release')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
