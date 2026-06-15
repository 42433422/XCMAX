#!/usr/bin/env python3
"""Migrate ``except OPERATIONAL_ERRORS`` to ``except RECOVERABLE_ERRORS`` across FHD/app."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "FHD" / "app"

SKIP_SUFFIXES = (
    "utils/operational_errors.py",
)

EXCEPT_RE = re.compile(r"\bexcept\s+OPERATIONAL_ERRORS\b")
IMPORT_OLD = re.compile(
    r"from app\.utils\.operational_errors import OPERATIONAL_ERRORS\b"
)
IMPORT_MULTI = re.compile(
    r"from app\.utils\.operational_errors import ([^\n]+)"
)


def _patch_file(path: Path) -> bool:
    rel = path.relative_to(APP_ROOT).as_posix()
    if any(rel.endswith(s) for s in SKIP_SUFFIXES):
        return False

    text = path.read_text(encoding="utf-8")
    if "OPERATIONAL_ERRORS" not in text:
        return False

    new_text = EXCEPT_RE.sub("except RECOVERABLE_ERRORS", text)

    if IMPORT_OLD.search(new_text):
        new_text = IMPORT_OLD.sub(
            "from app.utils.operational_errors import RECOVERABLE_ERRORS", new_text
        )
    else:
        def _expand_import(match: re.Match[str]) -> str:
            names = match.group(1)
            if "OPERATIONAL_ERRORS" not in names:
                return match.group(0)
            names = names.replace("OPERATIONAL_ERRORS", "RECOVERABLE_ERRORS")
            return f"from app.utils.operational_errors import {names}"

        new_text = IMPORT_MULTI.sub(_expand_import, new_text)

    if new_text == text:
        return False

    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    changed = 0
    for path in sorted(APP_ROOT.rglob("*.py")):
        if _patch_file(path):
            changed += 1
            print(path.relative_to(REPO_ROOT))
    print(f"migrated {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
