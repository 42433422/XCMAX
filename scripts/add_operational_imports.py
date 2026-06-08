#!/usr/bin/env python3
"""Ensure every file using OPERATIONAL_ERRORS imports it after __future__ lines."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "FHD" / "app"
IMPORT = "from app.utils.operational_errors import OPERATIONAL_ERRORS"


def _has_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.utils.operational_errors":
            for alias in node.names:
                if alias.name == "OPERATIONAL_ERRORS":
                    return True
    return False


def _uses_operational(text: str) -> bool:
    return "OPERATIONAL_ERRORS" in text


def _insert_import(text: str) -> str:
    lines = text.splitlines()
    insert = 0
    if lines and lines[0].startswith("#!"):
        insert = 1
    # module docstring
    if insert < len(lines):
        s = lines[insert].strip()
        if s.startswith('"""') or s.startswith("'''"):
            quote = '"""' if '"""' in s else "'''"
            if s.count(quote) < 2:
                insert += 1
                while insert < len(lines) and quote not in lines[insert]:
                    insert += 1
            insert += 1
    while insert < len(lines) and lines[insert].strip() == "":
        insert += 1
    while insert < len(lines) and lines[insert].strip().startswith("from __future__"):
        insert += 1
    while insert < len(lines) and lines[insert].strip() == "":
        insert += 1
    lines.insert(insert, IMPORT)
    out = "\n".join(lines)
    if text.endswith("\n"):
        out += "\n"
    return out


def main() -> int:
    n = 0
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "operational_errors.py":
            continue
        text = path.read_text(encoding="utf-8")
        if not _uses_operational(text) or IMPORT in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        if _has_import(tree):
            continue
        path.write_text(_insert_import(text), encoding="utf-8")
        n += 1
    print(f"added import to {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
