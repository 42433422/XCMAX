#!/usr/bin/env python3
"""Replace ``except Exception`` with ``except OPERATIONAL_ERRORS`` across FHD/app."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "FHD" / "app"
IMPORT_LINE = "from app.utils.operational_errors import OPERATIONAL_ERRORS\n"

SKIP_SUFFIXES = (
    "middleware/error_handler.py",
    "utils/error_handling.py",
    "utils/operational_errors.py",
)

EXCEPT_PATTERNS = [
    (re.compile(r"(\s*)except Exception as (\w+)\s*:"), r"\1except OPERATIONAL_ERRORS as \2:"),
    (re.compile(r"(\s*)except Exception\s*:"), r"\1except OPERATIONAL_ERRORS:"),
]


def _needs_import(text: str) -> bool:
    return "OPERATIONAL_ERRORS" not in text


def _inject_import(text: str) -> str:
    if not _needs_import(text):
        return text
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if insert_at < len(lines) and ('"""' in lines[insert_at] or "'''" in lines[insert_at]):
        quote = '"""' if '"""' in lines[insert_at] else "'''"
        insert_at += 1
        while insert_at < len(lines) and quote not in lines[insert_at]:
            insert_at += 1
        insert_at += 1
    if insert_at < len(lines) and "from __future__" in lines[insert_at]:
        insert_at += 1
        while insert_at < len(lines) and (lines[insert_at].strip() == "" or "from __future__" in lines[insert_at]):
            if "from __future__" in lines[insert_at]:
                insert_at += 1
            elif lines[insert_at].strip() == "":
                insert_at += 1
            else:
                break
    lines.insert(insert_at, IMPORT_LINE)
    return "".join(lines)


def remediate_file(path: Path) -> bool:
    rel = path.relative_to(APP_ROOT).as_posix()
    if any(rel.endswith(s) for s in SKIP_SUFFIXES):
        return False
    original = path.read_text(encoding="utf-8")
    if "except Exception" not in original:
        return False
    updated = original
    for pattern, repl in EXCEPT_PATTERNS:
        updated = pattern.sub(repl, updated)
    if updated == original:
        return False
    if "OPERATIONAL_ERRORS" in updated:
        updated = _inject_import(updated)
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    changed = 0
    for path in sorted(APP_ROOT.rglob("*.py")):
        if remediate_file(path):
            changed += 1
            print(f"updated {path.relative_to(REPO_ROOT)}")
    print(f"done: {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
