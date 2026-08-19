#!/usr/bin/env python3
"""Declare type-only host contracts for composition mixins.

Many FHD services are assembled with multiple inheritance.  A mixin can call a
method supplied by a sibling base at runtime, but mypy only sees the mixin in
isolation.  This tool converts the resulting ``attr-defined`` diagnostics into
an explicit, enumerated ``TYPE_CHECKING`` contract inside that mixin.  It does
not add a catch-all ``__getattr__`` and has no runtime effect.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ATTR_ERROR = re.compile(
    r'^(?P<file>[^:]+):\d+: error: "(?P<class>[^"\[]+Mixin)" has no attribute "(?P<attr>[^"]+)"  \[attr-defined\]$'
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


def _has_typing_import(lines: list[str], name: str) -> bool:
    try:
        module = ast.parse("\n".join(lines))
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(alias.name == name or alias.name == "*" for alias in node.names)
        for node in module.body
    )


def _add_typing_name(lines: list[str], name: str) -> None:
    if _has_typing_import(lines, name):
        return
    for index, line in enumerate(lines):
        if not line.startswith("from typing import"):
            continue
        if "(" not in line:
            lines[index] = f"{line.rstrip()}, {name}"
            return
        for close_index in range(index + 1, len(lines)):
            if lines[close_index].strip() == ")":
                lines.insert(close_index, f"    {name},")
                return
    module = ast.parse("\n".join(lines))
    insert_at = 0
    if module.body and isinstance(module.body[0], ast.Expr):
        value = module.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            insert_at = int(module.body[0].end_lineno or module.body[0].lineno)
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_at = max(insert_at, int(node.end_lineno or node.lineno))
    lines.insert(insert_at, f"from typing import {name}")


def _class_insert_line(node: ast.ClassDef) -> int:
    if node.body and isinstance(node.body[0], ast.Expr):
        value = node.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return int(node.body[0].end_lineno or node.body[0].lineno)
    return node.lineno


def _fix_file(path: Path, contracts: dict[str, set[str]]) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    module = ast.parse(original)
    classes = {
        node.name: node
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef) and node.name in contracts
    }
    insertions: list[tuple[int, list[str]]] = []
    declared = 0
    for class_name, attrs in contracts.items():
        node = classes.get(class_name)
        if node is None:
            continue
        existing = {
            child.target.id
            for child in node.body
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
        }
        missing = sorted(attrs - existing)
        if not missing:
            continue
        indent = " " * (node.col_offset + 4)
        block = [f"{indent}if TYPE_CHECKING:"]
        block.extend(f"{indent}    {attr}: Any" for attr in missing)
        insertions.append((_class_insert_line(node), block))
        declared += len(missing)

    for line_no, block in sorted(insertions, reverse=True):
        lines[line_no:line_no] = block
    if declared:
        _add_typing_name(lines, "Any")
        _add_typing_name(lines, "TYPE_CHECKING")
        path.write_text("\n".join(lines) + ("\n" if original.endswith("\n") else ""), encoding="utf-8")
    return declared


def main() -> int:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for line in _run_mypy().splitlines():
        match = ATTR_ERROR.match(line)
        if match:
            grouped[match.group("file")][match.group("class")].add(match.group("attr"))
    declared = 0
    for relative, contracts in grouped.items():
        path = Path(relative)
        if not path.is_absolute():
            path = FHD_ROOT / path
        declared += _fix_file(path, contracts)
    print(f"declared={declared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
