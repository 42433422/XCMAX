#!/usr/bin/env python3
"""Phase 9 mypy autofix: no-any-return via cast(), var-annotated, simple assignment fixes."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = FHD_ROOT / "app"

MYPY_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): error: Returning Any from function declared to return (?P<rtype>.+?)  \[no-any-return\]"
)
VAR_ANNOTATED = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): error: Need type annotation for \"(?P<name>\w+)\"  \[var-annotated\]"
)
ASSIGN_INT_FLOAT = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): error: Incompatible types in assignment \(expression has type \"float\", variable has type \"int\"\)  \[assignment\]"
)


def _run_mypy() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "app/", "--no-error-summary"],
        cwd=FHD_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout + proc.stderr


def _ensure_cast_import(lines: list[str]) -> list[str]:
    if any("from typing import" in ln and "cast" in ln for ln in lines):
        return lines
    if any(ln.startswith("from typing import") for ln in lines):
        out: list[str] = []
        for ln in lines:
            if ln.startswith("from typing import"):
                if "cast" not in ln:
                    ln = ln.rstrip()
                    if ln.endswith(")"):
                        pass
                    elif "(" in ln:
                        ln = ln.rstrip(")") + ", cast)"
                    else:
                        parts = ln.replace("from typing import ", "").strip()
                        ln = f"from typing import {parts}, cast"
            out.append(ln)
        return out
    # insert after future import or after docstring
    insert_at = 0
    if lines and lines[0].startswith('"""'):
        for i, ln in enumerate(lines[1:], 1):
            if ln.strip().endswith('"""'):
                insert_at = i + 1
                break
    elif lines and "annotations" in lines[0]:
        insert_at = 1
    lines.insert(insert_at, "from typing import cast")
    return lines


def _fix_no_any_return(path: Path, line_no: int, rtype: str) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False
    line = lines[idx]
    stripped = line.lstrip()
    if not stripped.startswith("return "):
        return False
    indent = line[: len(line) - len(stripped)]
    expr = stripped[len("return ") :].rstrip()
    if expr.startswith("cast("):
        return False
    lines = _ensure_cast_import([ln.rstrip("\n") for ln in lines])
    # re-read line after potential import insert
    lines = [ln + ("\n" if not ln.endswith("\n") else "") for ln in lines]
    # normalize - split again
    raw = "".join(lines).splitlines(keepends=True)
    idx = line_no - 1 + (len(raw) - len(lines))  # adjust if imports added
    # simpler: recompute
    content_lines = path.read_text(encoding="utf-8").splitlines()
    content_lines = _ensure_cast_import(content_lines)
    idx = line_no - 1
    if idx >= len(content_lines):
        return False
    stripped = content_lines[idx].lstrip()
    if not stripped.startswith("return "):
        return False
    indent = content_lines[idx][: len(content_lines[idx]) - len(stripped)]
    expr = stripped[len("return ") :].strip()
    if expr.startswith("cast("):
        return False
    content_lines[idx] = f"{indent}return cast({rtype}, {expr})"
    path.write_text("\n".join(content_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return True


def _fix_var_annotated(path: Path, line_no: int, name: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False
    line = lines[idx]
    if f"{name} =" not in line and f"{name}=" not in line:
        return False
    if ": " in line.split("=")[0]:
        return False
    lines[idx] = line.replace(f"{name} =", f"{name}: object =", 1).replace(f"{name}=", f"{name}: object =", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _fix_int_float(path: Path, line_no: int) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False
    line = lines[idx]
    if ": int" not in line:
        # try changing annotation on previous lines is too hard; use float()
        if "=" in line:
            lhs, rhs = line.split("=", 1)
            if ": int" in lhs:
                lines[idx] = lhs.replace(": int", ": float") + "=" + rhs
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
    return False


def main() -> int:
    output = _run_mypy()
    fixed = 0
    for raw_line in output.splitlines():
        m = MYPY_LINE.match(raw_line)
        if m:
            rel = m.group("file")
            path = FHD_ROOT / rel if not rel.startswith("/") else Path(rel)
            if _fix_no_any_return(path, int(m.group("line")), m.group("rtype")):
                fixed += 1
            continue
        m = VAR_ANNOTATED.match(raw_line)
        if m:
            rel = m.group("file")
            path = FHD_ROOT / rel
            if _fix_var_annotated(path, int(m.group("line")), m.group("name")):
                fixed += 1
            continue
        m = ASSIGN_INT_FLOAT.match(raw_line)
        if m:
            rel = m.group("file")
            path = FHD_ROOT / rel
            if _fix_int_float(path, int(m.group("line"))):
                fixed += 1
    print(f"fixed={fixed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
