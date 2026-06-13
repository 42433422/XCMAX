#!/usr/bin/env python3
"""Ratchet: type-safety debt (mypy ignores, ts-nocheck, frontend any)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = FHD_ROOT / "app"
FRONTEND_SRC = FHD_ROOT / "frontend" / "src"

TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore\b")
TS_NOCHECK = re.compile(r"@ts-nocheck\b")
ANY_WORD = re.compile(r"\bany\b")


def _count_in_tree(root: Path, pattern: re.Pattern[str], glob: str) -> tuple[int, int]:
    total = 0
    files = 0
    if not root.exists():
        return 0, 0
    for path in root.rglob(glob):
        if not path.is_file():
            continue
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = len(pattern.findall(text))
        if hits:
            files += 1
            total += hits
    return total, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-type-ignore", type=int, default=69)
    parser.add_argument("--max-ts-nocheck", type=int, default=3)
    parser.add_argument("--max-any", type=int, default=539)
    args = parser.parse_args()

    ti, ti_files = _count_in_tree(APP_ROOT, TYPE_IGNORE, "*.py")
    nc, nc_files = _count_in_tree(FRONTEND_SRC, TS_NOCHECK, "*")
    any_hits, any_files = 0, 0
    for ext in ("*.ts", "*.tsx", "*.vue"):
        n, f = _count_in_tree(FRONTEND_SRC, ANY_WORD, ext)
        any_hits += n
        if n:
            any_files += f

    print(f"type_ignore={ti} ({ti_files} files)")
    print(f"ts_nocheck={nc} ({nc_files} files)")
    print(f"frontend_any={any_hits} ({any_files} files)")

    failed = False
    if ti > args.max_type_ignore:
        print(f"FAIL: type_ignore > {args.max_type_ignore}", file=sys.stderr)
        failed = True
    if nc > args.max_ts_nocheck:
        print(f"FAIL: ts_nocheck > {args.max_ts_nocheck}", file=sys.stderr)
        failed = True
    if any_hits > args.max_any:
        print(f"FAIL: frontend_any > {args.max_any}", file=sys.stderr)
        failed = True

    if failed:
        return 1
    print("OK: within baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
