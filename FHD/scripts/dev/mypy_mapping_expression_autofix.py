#!/usr/bin/env python3
"""Default optional mapping expressions before mapping-method access."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Item "None" of "(?P<type>(?:Any \| )?dict\[[^"]+\](?: \| None)?)" has no attribute "(?P<attr>get|items|values|keys|update|pop|setdefault)"  \[union-attr\]$'
)


def _run_mypy() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "app/", "--no-error-summary"],
        cwd=FHD_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


def _char_column(line: str, byte_column: int) -> int:
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))


def _offset(lines: list[str], line_no: int, byte_column: int) -> int:
    return sum(len(line) + 1 for line in lines[: line_no - 1]) + _char_column(
        lines[line_no - 1], byte_column
    )


def _fix_file(path: Path, diagnostics: list[tuple[int, str]]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    module = ast.parse(original)
    replacements: dict[tuple[int, int], str] = {}
    for line, attribute_name in diagnostics:
        candidates = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Attribute)
            and node.attr == attribute_name
            and node.lineno == line
        ]
        if not candidates:
            continue
        attribute = min(candidates, key=lambda node: node.col_offset)
        value = attribute.value
        if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
            continue
        if value.end_lineno is None or value.end_col_offset is None:
            continue
        start = _offset(lines, value.lineno, value.col_offset)
        end = _offset(lines, value.end_lineno, value.end_col_offset)
        expression = original[start:end]
        replacements[(start, end)] = f"({expression} or {{}})"

    updated = original
    for (start, end), replacement in sorted(replacements.items(), reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if replacements:
        path.write_text(updated, encoding="utf-8")
    return len(replacements)


def main() -> int:
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in _run_mypy().splitlines():
        if match := ERROR.match(line):
            grouped[match.group("file")].append((int(match.group("line")), match.group("attr")))
    replaced = 0
    for relative, diagnostics in grouped.items():
        path = Path(relative)
        if not path.is_absolute():
            path = FHD_ROOT / path
        replaced += _fix_file(path, diagnostics)
    print(f"replaced={replaced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
