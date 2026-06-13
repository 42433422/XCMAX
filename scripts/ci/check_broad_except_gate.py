#!/usr/bin/env python3
"""CI gate: forbid new broad ``except Exception`` outside boundary allowlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "FHD" / "app"
BASELINE_PATH = Path(__file__).resolve().parent / "broad_except_baseline.txt"

BROAD_RE = re.compile(r"^\s*except\s+Exception\b")
ALLOWLIST_SUFFIXES = (
    "middleware/error_handler.py",
    "utils/error_handling.py",
    "neuro_bus/bus.py",
    "fastapi_app/lifespan.py",
    "infrastructure/mods/mod_auth.py",
)


def _count_broad(root: Path) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(rel.endswith(s) for s in ALLOWLIST_SUFFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        count = sum(1 for line in text if BROAD_RE.match(line) and "noqa: broad-except-boundary" not in line)
        if count:
            hits.append((rel, count))
    return hits


def main() -> int:
    hits = _count_broad(APP_ROOT)
    total = sum(c for _, c in hits)
    baseline = 0
    if BASELINE_PATH.is_file():
        baseline = int(BASELINE_PATH.read_text(encoding="utf-8").strip() or "0")
    if total > baseline:
        print(f"broad except gate FAILED: {total} > baseline {baseline}")
        for rel, count in hits[:40]:
            print(f"  {rel}: {count}")
        if len(hits) > 40:
            print(f"  ... and {len(hits) - 40} more files")
        return 1
    print(f"broad except gate OK: {total} (baseline {baseline})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
