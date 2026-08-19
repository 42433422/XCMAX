#!/usr/bin/env python3
"""Add defensive defaults at optional JSON-to-builtin conversion boundaries."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Argument 1 to "(?P<fn>int|float|len|dict|enumerate)" has incompatible type "(?P<type>[^"]*(?:None|Any)[^"]*)"; expected .+  \[arg-type\]$'
)
DEFAULTS = {"int": "0", "float": "0.0", "len": "[]", "dict": "{}", "enumerate": "[]"}


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


def _absolute_offset(lines: list[str], line_no: int, byte_column: int) -> int:
    return sum(len(line) + 1 for line in lines[: line_no - 1]) + _char_column(lines[line_no - 1], byte_column)


def _fix_file(path: Path, diagnostics: list[tuple[int, str]]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    module = ast.parse(original)
    replacements: dict[tuple[int, int], str] = {}
    for error_line, function_name in diagnostics:
        candidates = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function_name
            and len(node.args) >= 1
            and node.lineno <= error_line <= int(node.end_lineno or node.lineno)
        ]
        if not candidates:
            continue
        call = min(candidates, key=lambda node: int(node.end_lineno or node.lineno) - node.lineno)
        argument = call.args[0]
        if isinstance(argument, ast.BoolOp) and isinstance(argument.op, ast.Or):
            continue
        if argument.end_lineno is None or argument.end_col_offset is None:
            continue
        start = _absolute_offset(lines, argument.lineno, argument.col_offset)
        end = _absolute_offset(lines, argument.end_lineno, argument.end_col_offset)
        expression = original[start:end]
        replacements[(start, end)] = f"({expression} or {DEFAULTS[function_name]})"

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
            grouped[match.group("file")].append((int(match.group("line")), match.group("fn")))
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
