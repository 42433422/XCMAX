#!/usr/bin/env python3
"""CI gate: forbid ``OPERATIONAL_ERRORS`` and bare catch of programming-bug types."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "FHD" / "app"

OPERATIONAL_RE = re.compile(r"\bOPERATIONAL_ERRORS\b")
BUG_CATCH_RE = re.compile(
    r"^\s*except\s+(TypeError|KeyError|AttributeError)\s*:\s*$"
)

SKIP_SUFFIXES = (
    "middleware/error_handler.py",
    "utils/error_handling.py",
)


def _scan(root: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(rel.endswith(s) for s in SKIP_SUFFIXES):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if OPERATIONAL_RE.search(line):
                hits.append((rel, lineno, line.strip()))
            if BUG_CATCH_RE.match(line) and "noqa" not in line:
                hits.append((rel, lineno, line.strip()))
    return hits


def main() -> int:
    hits = _scan(APP_ROOT)
    if hits:
        print(f"operational errors gate FAILED: {len(hits)} violation(s)")
        for rel, lineno, line in hits[:50]:
            print(f"  {rel}:{lineno}: {line}")
        if len(hits) > 50:
            print(f"  ... and {len(hits) - 50} more")
        return 1
    print("operational errors gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
