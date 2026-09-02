#!/usr/bin/env python3
"""Forbid direct broad exception handlers in repository-owned Python code.

Named boundary tuples (for example ``BOUNDARY_ERRORS``) remain available for
real plugin, process, and lifecycle boundaries.  Direct ``Exception`` and
``BaseException`` handlers are rejected so every catch-all remains explicit
and searchable.  The locked upstream LangGraph mirror is measured separately:
it may improve, but its pinned baseline may not grow unnoticed.  Files under
``OWNED_EXCLUDED_PREFIXES`` are exempt from the owned gate: the legal
document-material generators there are not runtime code and their intentional
broad handlers (docx failure must not block txt output) stay out of scope.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_BASELINES = {"FHD/third_party/langgraph": 56}
# FHD/docs/legal/ 为软著鉴别材料生成脚本，非运行时代码；其 broad except（docx 失败不阻塞 txt 产出）属有意豁免。
OWNED_EXCLUDED_PREFIXES = ("FHD/docs/legal/",)


def _python_paths() -> list[Path]:
    """Return tracked and non-ignored untracked Python files."""
    proc = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.py",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    relpaths = {os.fsdecode(item) for item in proc.stdout.split(b"\0") if item}
    return [path for rel in sorted(relpaths) if (path := REPO_ROOT / rel).is_file()]


def _direct_broad_handler(node: ast.ExceptHandler) -> bool:
    def direct(item: ast.expr) -> bool:
        return isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"}

    if node.type is None:
        return False
    if direct(node.type):
        return True
    return isinstance(node.type, ast.Tuple) and any(direct(item) for item in node.type.elts)


def _scan(paths: list[Path]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            # A tracked file may disappear between ``git ls-files`` and this
            # read (notably when a deletion is part of the current change).
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            # Syntax validity belongs to the compile gate; documentation may
            # intentionally contain incomplete Python snippets.
            continue
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and _direct_broad_handler(node)
        )
        if count:
            hits.append((path.relative_to(REPO_ROOT).as_posix(), count))
    return hits


def _vendor_root(rel: str) -> str | None:
    return next(
        (root for root in VENDOR_BASELINES if rel == root or rel.startswith(f"{root}/")),
        None,
    )


def main() -> int:
    hits = _scan(_python_paths())
    owned = [
        (rel, count)
        for rel, count in hits
        if _vendor_root(rel) is None and not rel.startswith(OWNED_EXCLUDED_PREFIXES)
    ]
    failed = False

    if owned:
        failed = True
        print(f"broad except gate FAILED: {sum(count for _, count in owned)} owned handlers")
        for rel, count in owned[:80]:
            print(f"  {rel}: {count}")
        if len(owned) > 80:
            print(f"  ... and {len(owned) - 80} more files")

    for root, baseline in VENDOR_BASELINES.items():
        current = sum(count for rel, count in hits if _vendor_root(rel) == root)
        if current > baseline:
            failed = True
            print(f"vendor broad except gate FAILED: {root}: {current} > {baseline}")
        else:
            print(f"vendor broad except gate OK: {root}: {current} <= {baseline}")

    if failed:
        return 1
    print("owned broad except gate OK: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
