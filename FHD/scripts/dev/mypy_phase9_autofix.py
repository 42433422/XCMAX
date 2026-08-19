#!/usr/bin/env python3
"""Mechanical Phase 9 mypy fixes for explicit Any boundaries.

The fixer is deliberately narrow: it only wraps a single-line ``return`` that
mypy reports as ``no-any-return`` in ``typing.cast`` and annotates an otherwise
untyped empty container with ``Any``.  Diagnostics are grouped per file and
applied bottom-up, so adding imports cannot shift later targets.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]

MYPY_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): error: Returning Any from function declared to return (?P<rtype>.+?)  \[no-any-return\]$"
)
VAR_ANNOTATED = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Need type annotation for "(?P<name>\w+)"  \[var-annotated\]$'
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


def _add_typing_name(lines: list[str], name: str) -> None:
    try:
        module = ast.parse("\n".join(lines))
        for node in module.body:
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                if any(alias.name == name or alias.name == "*" for alias in node.names):
                    return
    except SyntaxError:
        pass
    for index, line in enumerate(lines):
        if not line.startswith("from typing import"):
            continue
        if re.search(rf"\b{re.escape(name)}\b", line):
            return
        if "(" not in line:
            lines[index] = f"{line.rstrip()}, {name}"
            return
        for close_index in range(index + 1, len(lines)):
            if lines[close_index].strip() == ")":
                indent = re.match(r"\s*", lines[index + 1]).group(0) if index + 1 < len(lines) else "    "
                lines.insert(close_index, f"{indent}{name},")
                return

    source = "\n".join(lines)
    try:
        module = ast.parse(source)
        insert_at = 0
        if module.body and isinstance(module.body[0], ast.Expr):
            value = module.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                insert_at = int(module.body[0].end_lineno or module.body[0].lineno)
        for node in module.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                insert_at = max(insert_at, int(node.end_lineno or node.lineno))
    except SyntaxError:
        insert_at = 0
    lines.insert(insert_at, f"from typing import {name}")


def _fix_file(path: Path, diagnostics: list[tuple[str, int, str]]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    fixed = 0
    needs_cast = False
    needs_any = False

    for kind, line_no, detail in sorted(diagnostics, key=lambda item: item[1], reverse=True):
        index = line_no - 1
        if index < 0 or index >= len(lines):
            continue
        line = lines[index]
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if kind == "return":
            if not stripped.startswith("return ") or stripped.startswith("return cast("):
                continue
            expression = stripped[len("return ") :].strip()
            if not expression or expression.endswith(("(", "[", "{")):
                continue
            lines[index] = f"{indent}return cast({detail}, {expression})"
            needs_cast = True
            needs_any = needs_any or bool(re.search(r"\bAny\b", detail))
            fixed += 1
        elif kind == "var":
            name = detail
            match = re.match(rf"^(?P<indent>\s*){re.escape(name)}\s*=\s*(?P<expr>\[\]|\{{\}})\s*$", line)
            if not match:
                continue
            lines[index] = f"{match.group('indent')}{name}: Any = {match.group('expr')}"
            needs_any = True
            fixed += 1

    if needs_cast:
        _add_typing_name(lines, "cast")
    if needs_any:
        _add_typing_name(lines, "Any")
    if fixed:
        path.write_text("\n".join(lines) + ("\n" if original.endswith("\n") else ""), encoding="utf-8")
    return fixed


def _repair_cast_any_imports() -> int:
    repaired = 0
    for path in (FHD_ROOT / "app").rglob("*.py"):
        original = path.read_text(encoding="utf-8")
        if not re.search(r"cast\([\"'][^\"']*\bAny\b", original):
            continue
        lines = original.splitlines()
        before = list(lines)
        _add_typing_name(lines, "Any")
        if lines != before:
            path.write_text(
                "\n".join(lines) + ("\n" if original.endswith("\n") else ""),
                encoding="utf-8",
            )
            repaired += 1
    return repaired


def main() -> int:
    grouped: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for raw_line in _run_mypy().splitlines():
        if match := MYPY_LINE.match(raw_line):
            grouped[match.group("file")].append(
                ("return", int(match.group("line")), match.group("rtype"))
            )
        elif match := VAR_ANNOTATED.match(raw_line):
            grouped[match.group("file")].append(
                ("var", int(match.group("line")), match.group("name"))
            )

    fixed = 0
    for relative, diagnostics in grouped.items():
        path = Path(relative)
        if not path.is_absolute():
            path = FHD_ROOT / path
        fixed += _fix_file(path, diagnostics)
    repaired = _repair_cast_any_imports()
    print(f"fixed={fixed} repaired_any_imports={repaired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
