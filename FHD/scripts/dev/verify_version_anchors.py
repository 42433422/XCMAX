#!/usr/bin/env python3
"""Verify FHD v10 version anchors match VERSION.md (read-only; no bump)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ANCHORS: list[tuple[str, str]] = [
    ("pyproject.toml", r'version\s*=\s*"([\d.]+)"'),
    ("XCAGI/pyproject.toml", r'version\s*=\s*"([\d.]+)"'),
    ("frontend/package.json", r'"version"\s*:\s*"([\d.]+)"'),
    ("desktop/package.json", r'"version"\s*:\s*"([\d.]+)"'),
    ("package.json", r'"version"\s*:\s*"([\d.]+)"'),
    ("app/fastapi_app/factory.py", r'version="([\d.]+)"'),
    ("app/infrastructure/mods/manifest.py", r'current_version\s*=\s*"([\d.]+)"'),
    ("mobile-android/app/build.gradle.kts", r'versionName\s*=\s*"([\d.]+)"'),
    ("mobile-harmony/AppScope/app.json5", r'"versionName"\s*:\s*"([\d.]+)"'),
    # iOS：原生工程并入主干后追加锚点（config/product.yaml ends.mobile.channels.ios）
]


def _canonical_version() -> str:
    version_md = REPO_ROOT / "VERSION.md"
    if not version_md.is_file():
        raise FileNotFoundError(f"missing {version_md}")
    for line in version_md.read_text(encoding="utf-8").splitlines():
        if "**XCAGI 总版本**" in line:
            match = re.search(r"`([\d.]+)`", line)
            if match:
                return match.group(1)
    raise ValueError("could not parse canonical version from VERSION.md")


def verify() -> list[str]:
    expected = _canonical_version()
    errors: list[str] = []
    for rel_path, pattern in ANCHORS:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            errors.append(f"{rel_path}: file not found")
            continue
        match = re.search(pattern, full_path.read_text(encoding="utf-8"))
        if not match:
            errors.append(f"{rel_path}: version pattern not found")
            continue
        found = match.group(1)
        if found != expected:
            errors.append(f"{rel_path}: expected {expected}, found {found}")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Version anchor mismatches:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"OK: all anchors match {_canonical_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
