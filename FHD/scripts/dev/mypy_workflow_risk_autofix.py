#!/usr/bin/env python3
"""Route dynamic workflow risk strings through the shared literal normalizer."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(
    r'^(?P<file>[^:]+):(?P<line>\d+): error: Argument "(?P<arg>risk|risk_level)" to "(?:WorkflowNode|PlanGraph)" has incompatible type "str"; expected "Literal\[\'low\', \'medium\', \'high\'\]"  \[arg-type\]$'
)
IMPORT = "from app.application.workflow.types import normalize_workflow_risk"


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
    for error_line, argument_name in diagnostics:
        candidates = [
            keyword
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and node.lineno <= error_line <= int(node.end_lineno or node.lineno)
            for keyword in node.keywords
            if keyword.arg == argument_name
            and keyword.value.lineno
            <= error_line
            <= int(keyword.value.end_lineno or keyword.value.lineno)
        ]
        if not candidates:
            continue
        keyword = min(
            candidates,
            key=lambda item: int(item.value.end_lineno or item.value.lineno) - item.value.lineno,
        )
        value = keyword.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "normalize_workflow_risk":
                continue
        if value.end_lineno is None or value.end_col_offset is None:
            continue
        start = _offset(lines, value.lineno, value.col_offset)
        end = _offset(lines, value.end_lineno, value.end_col_offset)
        replacements[(start, end)] = f"normalize_workflow_risk({original[start:end]})"

    updated = original
    for (start, end), replacement in sorted(replacements.items(), reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if replacements and IMPORT not in updated:
        updated_lines = updated.splitlines()
        updated_module = ast.parse(updated)
        imports = [
            node for node in updated_module.body if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        insert_line = max((int(node.end_lineno or node.lineno) for node in imports), default=0)
        updated_lines.insert(insert_line, IMPORT)
        updated = "\n".join(updated_lines) + ("\n" if original.endswith("\n") else "")
    if replacements:
        path.write_text(updated, encoding="utf-8")
    return len(replacements)


def main() -> int:
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in _run_mypy().splitlines():
        if match := ERROR.match(line):
            grouped[match.group("file")].append((int(match.group("line")), match.group("arg")))
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
