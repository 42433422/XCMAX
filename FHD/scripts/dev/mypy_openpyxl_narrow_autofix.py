#!/usr/bin/env python3
# mypy: disable-error-code="union-attr"
"""Insert explicit non-null guards for openpyxl active worksheets.

``Workbook.active`` is typed as optional by openpyxl, while newly created and
successfully loaded workbooks in these code paths require an active sheet.  A
guard at the first dereference documents that invariant and removes cascaded
attribute/index diagnostics without changing the successful path.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Item "None" of "(?P<type>[^"]*(?:WorksheetOrChartsheetLike|Workbook)[^"]*)" has no attribute "[^"]+"  \[union-attr\]$'
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


def _scope_for_line(module: ast.Module, line: int) -> ast.AST:
    candidates: list[ast.AST] = [module]
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno <= line <= int(node.end_lineno or node.lineno):
            candidates.append(node)
    return max(candidates, key=lambda node: getattr(node, "lineno", 0))


def _optional_name_at_line(module: ast.Module, line: int) -> str | None:
    names: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Attribute) or node.lineno != line:
            continue
        value = node.value
        if isinstance(value, ast.Name):
            names.append(value.id)
    return names[0] if names else None


def _fix_file(path: Path, error_lines: list[int]) -> int:
    original = path.read_text(encoding="utf-8")
    module = ast.parse(original)
    lines = original.splitlines()
    grouped: dict[tuple[int, str], list[int]] = defaultdict(list)
    for line in error_lines:
        name = _optional_name_at_line(module, line)
        if not name:
            continue
        scope = _scope_for_line(module, line)
        grouped[(getattr(scope, "lineno", 0), name)].append(line)

    insertions: list[tuple[int, str]] = []
    for (_scope_line, name), occurrences in grouped.items():
        first_line = min(occurrences)
        previous = lines[first_line - 2].strip() if first_line >= 2 else ""
        if previous == f"assert {name} is not None":
            continue
        indent = re.match(r"\s*", lines[first_line - 1]).group(0)
        insertions.append((first_line - 1, f"{indent}assert {name} is not None"))

    for index, statement in sorted(insertions, reverse=True):
        lines.insert(index, statement)
    if insertions:
        path.write_text(
            "\n".join(lines) + ("\n" if original.endswith("\n") else ""), encoding="utf-8"
        )
    return len(insertions)


def main() -> int:
    grouped: dict[str, list[int]] = defaultdict(list)
    for line in _run_mypy().splitlines():
        if match := ERROR.match(line):
            grouped[match.group("file")].append(int(match.group("line")))
    inserted = 0
    for relative, error_lines in grouped.items():
        path = Path(relative)
        if not path.is_absolute():
            path = FHD_ROOT / path
        inserted += _fix_file(path, error_lines)
    print(f"inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
