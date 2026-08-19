#!/usr/bin/env python3
"""Make parameters with a ``None`` default explicitly optional."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Incompatible default for parameter "(?P<param>[^"]+)" \(default has type "None", parameter has type "[^"]+"\)  \[assignment\]$'
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
    return sum(len(line) + 1 for line in lines[: line_no - 1]) + _char_column(lines[line_no - 1], byte_column)


def _find_argument(module: ast.Module, line: int, name: str) -> ast.arg | None:
    functions = [
        node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line <= int(node.end_lineno or node.lineno)
    ]
    if not functions:
        return None
    function = max(functions, key=lambda node: node.lineno)
    arguments = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    return next((argument for argument in arguments if argument.arg == name), None)


def _fix_file(path: Path, diagnostics: list[tuple[int, str]]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    module = ast.parse(original)
    replacements: dict[tuple[int, int], str] = {}
    for line, parameter in diagnostics:
        argument = _find_argument(module, line, parameter)
        annotation = argument.annotation if argument is not None else None
        if annotation is None or annotation.end_lineno is None or annotation.end_col_offset is None:
            continue
        start = _offset(lines, annotation.lineno, annotation.col_offset)
        end = _offset(lines, annotation.end_lineno, annotation.end_col_offset)
        source = original[start:end]
        if "None" in source:
            continue
        replacements[(start, end)] = f"{source} | None"

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
            grouped[match.group("file")].append((int(match.group("line")), match.group("param")))
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
