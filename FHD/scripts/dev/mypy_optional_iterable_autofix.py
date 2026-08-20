#!/usr/bin/env python3
"""Default optional JSON arrays before iteration."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Item "None" of "(?P<type>[^"]*(?:list\[[^"]+\]|Any)[^"]*)" has no attribute "__iter__" \(not iterable\)  \[union-attr\]$'
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


def _iterable_for_line(module: ast.Module, line: int) -> ast.expr | None:
    candidates: list[ast.expr] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.For, ast.AsyncFor)) and node.lineno <= line <= int(
            node.end_lineno or node.lineno
        ):
            candidates.append(node.iter)
        elif isinstance(node, ast.comprehension):
            iterable = node.iter
            if iterable.lineno <= line <= int(iterable.end_lineno or iterable.lineno):
                candidates.append(iterable)
    if not candidates:
        return None
    return min(candidates, key=lambda node: int(node.end_lineno or node.lineno) - node.lineno)


def _fix_file(path: Path, error_lines: list[int]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    module = ast.parse(original)
    replacements: dict[tuple[int, int], str] = {}
    for line in error_lines:
        iterable = _iterable_for_line(module, line)
        if iterable is None or iterable.end_lineno is None or iterable.end_col_offset is None:
            continue
        if isinstance(iterable, ast.BoolOp) and isinstance(iterable.op, ast.Or):
            continue
        start = _offset(lines, iterable.lineno, iterable.col_offset)
        end = _offset(lines, iterable.end_lineno, iterable.end_col_offset)
        replacements[(start, end)] = f"({original[start:end]} or [])"
    updated = original
    for (start, end), replacement in sorted(replacements.items(), reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if replacements:
        path.write_text(updated, encoding="utf-8")
    return len(replacements)


def main() -> int:
    grouped: dict[str, list[int]] = defaultdict(list)
    for line in _run_mypy().splitlines():
        if match := ERROR.match(line):
            grouped[match.group("file")].append(int(match.group("line")))
    replaced = 0
    for relative, error_lines in grouped.items():
        path = Path(relative)
        if not path.is_absolute():
            path = FHD_ROOT / path
        replaced += _fix_file(path, error_lines)
    print(f"replaced={replaced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
