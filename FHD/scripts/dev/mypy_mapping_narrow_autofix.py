#!/usr/bin/env python3
"""Normalize optional JSON mappings before their first mapping operation.

External JSON, manifest and metadata fields commonly have a runtime shape of
``dict | None | Any``.  Calling ``.get`` directly both crashes on malformed
payloads and prevents static narrowing.  This tool inserts a local defensive
normalization at the statement that first dereferences each reported value.
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
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Item "None" of "(?P<type>(?:Any \| )?dict\[[^"]+\](?: \| None)?)" has no attribute "get"  \[union-attr\]$'
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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line <= int(node.end_lineno or node.lineno):
                candidates.append(node)
    return max(candidates, key=lambda node: getattr(node, "lineno", 0))


def _statement_for_line(module: ast.Module, line: int) -> ast.stmt | None:
    candidates = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.stmt) and node.lineno <= line <= int(node.end_lineno or node.lineno)
    ]
    return (
        min(candidates, key=lambda node: int(node.end_lineno or node.lineno) - node.lineno)
        if candidates
        else None
    )


def _mapping_name_at_line(module: ast.Module, line: int) -> str | None:
    for node in ast.walk(module):
        if not isinstance(node, ast.Attribute) or node.lineno != line or node.attr != "get":
            continue
        if isinstance(node.value, ast.Name):
            return node.value.id
    return None


def _fix_file(path: Path, error_lines: list[int]) -> int:
    original = path.read_text(encoding="utf-8")
    module = ast.parse(original)
    lines = original.splitlines()
    groups: dict[tuple[int, str], list[int]] = defaultdict(list)
    statements: dict[tuple[int, str], ast.stmt] = {}
    for line in error_lines:
        name = _mapping_name_at_line(module, line)
        statement = _statement_for_line(module, line)
        if not name or statement is None:
            continue
        scope = _scope_for_line(module, line)
        key = (getattr(scope, "lineno", 0), name)
        groups[key].append(statement.lineno)
        statements[(statement.lineno, name)] = statement

    insertions: list[tuple[int, list[str]]] = []
    for (_scope_line, name), statement_lines in groups.items():
        first_line = min(statement_lines)
        statement = statements[(first_line, name)]
        indent = " " * statement.col_offset
        previous = lines[first_line - 2].strip() if first_line >= 2 else ""
        if previous == f"{name} = {{}}" or previous == f"if not isinstance({name}, dict):":
            continue
        insertions.append(
            (
                first_line - 1,
                [
                    f"{indent}if not isinstance({name}, dict):",
                    f"{indent}    {name} = {{}}",
                ],
            )
        )

    for index, block in sorted(insertions, reverse=True):
        lines[index:index] = block
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
