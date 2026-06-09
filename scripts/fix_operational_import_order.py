#!/usr/bin/env python3
"""Move OPERATIONAL_ERRORS import after all ``from __future__`` lines."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "FHD" / "app"
IMPORT = "from app.utils.operational_errors import OPERATIONAL_ERRORS"


def _advance_past_header(lines: list[str], start: int) -> int:
    insert = start
    if insert < len(lines) and lines[insert].startswith("#!"):
        insert += 1
    while insert < len(lines):
        s = lines[insert].strip()
        if s == "":
            insert += 1
            continue
        if s.startswith("#") and "coding" in s:
            insert += 1
            continue
        if s.startswith("#"):
            insert += 1
            continue
        if s.startswith('"""') or s.startswith("'''"):
            quote = '"""' if '"""' in s else "'''"
            if s.count(quote) >= 2 and s not in (quote, quote * 3):
                insert += 1
                continue
            insert += 1
            while insert < len(lines) and quote not in lines[insert]:
                insert += 1
            insert += 1
            continue
        break
    while insert < len(lines) and lines[insert].strip().startswith("from __future__"):
        insert += 1
    return insert


def fix_text(text: str) -> str:
    if IMPORT not in text:
        return text
    lines = text.splitlines()
    kept = [ln for ln in lines if ln.strip() != IMPORT]
    insert = _advance_past_header(kept, 0)
    while insert < len(kept) and kept[insert].strip() == "":
        insert += 1
    kept.insert(insert, IMPORT)
    return "\n".join(kept) + ("\n" if text.endswith("\n") else "")


def main() -> int:
    n = 0
    for path in sorted(ROOT.rglob("*.py")):
        original = path.read_text(encoding="utf-8")
        fixed = fix_text(original)
        if fixed != original:
            path.write_text(fixed, encoding="utf-8")
            n += 1
    print(f"fixed {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
