#!/usr/bin/env python3
"""
Architecture Fitness Function

Validates architectural invariants that should hold true across all commits.
Run: python scripts/arch_fitness.py
Exit code: 0 = all checks pass, 1 = violations found
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
MODSTORE_SERVER_DIR = Path(r"e:\成都修茈科技有限公司\MODstore_deploy\modstore_server")

MAX_FILE_LINES = 500
BASELINE_FILE = Path(__file__).resolve().parent / "arch_fitness_baseline.txt"

VIOLATIONS: list[str] = []


def _violation_key(violation: str) -> str:
    """基线键：`[check-type] path`（不含行号与行数后缀）。"""
    key = violation.split(" — ", 1)[0].strip() if " — " in violation else violation.strip()
    if "] " in key:
        prefix, path_part = key.split("] ", 1)
        path_part = path_part.replace("\\", "/")
        return f"{prefix}] {path_part}"
    return key.replace("\\", "/")


def _load_baseline_keys() -> set[str]:
    if not BASELINE_FILE.is_file():
        return set()
    keys: set[str] = set()
    for raw in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(_violation_key(line))
    return keys


# Giant-file violations are special: the baseline records a *frozen line ceiling*
# per file. A baselined giant file is suppressed only while it stays at-or-below
# its frozen size — growth past the ceiling is a NEW violation. Without this, the
# plain key-baseline (which strips the count) lets a 3,657-line file grow to
# 10,000 and stay green. This is the ratchet that freezes giant-file growth.
_GIANT_RE = re.compile(r"^\[giant-file\]\s+(?P<path>.+?)\s+—\s+(?P<n>\d+)\s+lines")
# Legacy baseline entries had no count suffix; treat them as "frozen, count
# unknown" so an old baseline never starts failing until it's bumped with counts.
_LEGACY_GIANT_CEILING = 10**9


def _giant_path_and_count(violation: str) -> tuple[str, int] | None:
    m = _GIANT_RE.match(violation.strip())
    if not m:
        return None
    return m.group("path").replace("\\", "/"), int(m.group("n"))


def _load_giant_baseline() -> dict[str, int]:
    """Map ``path -> frozen line ceiling`` from baselined ``[giant-file]`` lines."""
    ceilings: dict[str, int] = {}
    if not BASELINE_FILE.is_file():
        return ceilings
    for raw in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("[giant-file]"):
            continue
        pc = _giant_path_and_count(line)
        if pc:
            path, n = pc
            ceilings[path] = max(ceilings.get(path, 0), n)
        else:
            key = _violation_key(line)
            path = key.split("] ", 1)[1] if "] " in key else key
            ceilings.setdefault(path, _LEGACY_GIANT_CEILING)
    return ceilings


def _is_excluded_path(path: Path) -> bool:
    parts = path.parts
    if "__pycache__" in parts:
        return True
    if any(".v1_backup" in p for p in parts):
        return True
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError):
        return 0


def check_no_v1_backup_files() -> None:
    for path in APP_DIR.rglob("*.v1_backup"):
        rel = path.relative_to(REPO_ROOT)
        VIOLATIONS.append(f"[v1_backup] {rel} — backup file must be removed")


def check_routes_not_import_services() -> None:
    routes_dirs = [APP_DIR / "routes", APP_DIR / "fastapi_routes"]
    for routes_dir in routes_dirs:
        if not routes_dir.is_dir():
            continue
        for py in routes_dir.rglob("*.py"):
            rel = py.relative_to(REPO_ROOT)
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module and "app.services" in node.module:
                    names = ", ".join(a.name for a in node.names)
                    VIOLATIONS.append(
                        f"[routes->services] {rel}:{node.lineno} — "
                        f"from {node.module} import {names} "
                        f"(routes should use app.application, not app.services)"
                    )


def check_domain_not_depend_on_infrastructure() -> None:
    domain_dir = APP_DIR / "domain"
    if not domain_dir.is_dir():
        return
    for py in domain_dir.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module and "app.infrastructure" in node.module:
                names = ", ".join(a.name for a in node.names)
                VIOLATIONS.append(
                    f"[domain->infrastructure] {rel}:{node.lineno} — "
                    f"from {node.module} import {names} "
                    f"(domain must not depend on infrastructure)"
                )


def check_no_giant_files_in_app() -> None:
    if not APP_DIR.is_dir():
        return
    for py in APP_DIR.rglob("*.py"):
        if _is_excluded_path(py):
            continue
        line_count = _count_lines(py)
        if line_count > MAX_FILE_LINES:
            rel = py.relative_to(REPO_ROOT)
            VIOLATIONS.append(
                f"[giant-file] {rel} — {line_count} lines (max {MAX_FILE_LINES} in app/)"
            )


def check_no_giant_files_in_modstore_server() -> None:
    if not MODSTORE_SERVER_DIR.is_dir():
        print(f"  [skip] modstore_server not found at {MODSTORE_SERVER_DIR}")
        return
    for py in MODSTORE_SERVER_DIR.rglob("*.py"):
        if _is_excluded_path(py):
            continue
        line_count = _count_lines(py)
        if line_count > MAX_FILE_LINES:
            rel = py.relative_to(MODSTORE_SERVER_DIR.parent)
            VIOLATIONS.append(
                f"[giant-file] {rel} — {line_count} lines "
                f"(max {MAX_FILE_LINES} in modstore_server/)"
            )


def check_legacy_boundary() -> None:
    """legacy_* 文件必须收容在 app/legacy/ 下，禁止散落到 app/ 其他子目录。"""
    legacy_root = APP_DIR / "legacy"
    for py in APP_DIR.rglob("legacy_*.py"):
        if _is_excluded_path(py):
            continue
        try:
            py.relative_to(legacy_root)
            continue
        except ValueError:
            pass
        rel = py.relative_to(REPO_ROOT)
        VIOLATIONS.append(f"[legacy-boundary] {rel} — legacy_* file must live under app/legacy/")


def _classify_violations() -> list[str]:
    """Return only the violations that are NOT suppressed by the baseline.

    Non-giant-file checks use the path-keyed baseline. Giant-file checks use the
    count-aware ratchet: a baselined giant file is suppressed only while it stays
    at-or-below its frozen ceiling; growth past it (or a brand-new giant file) is
    reported.
    """
    key_baseline = _load_baseline_keys()
    giant_baseline = _load_giant_baseline()
    new_violations: list[str] = []
    for v in VIOLATIONS:
        if v.lstrip().startswith("[giant-file]"):
            pc = _giant_path_and_count(v)
            if pc is None:
                new_violations.append(v)
                continue
            path, n = pc
            ceiling = giant_baseline.get(path)
            if ceiling is None:
                new_violations.append(f"{v.rstrip()}  [NEW giant file — split it]")
            elif n > ceiling:
                new_violations.append(
                    f"{v.rstrip()}  [GREW past frozen ceiling {ceiling}; "
                    f"shrink it or run: python scripts/arch_fitness.py --bump]"
                )
            # else: at-or-below frozen ceiling -> suppressed
        elif _violation_key(v) not in key_baseline:
            new_violations.append(v)
    return new_violations


def _run_all_checks() -> None:
    VIOLATIONS.clear()
    check_no_v1_backup_files()
    check_routes_not_import_services()
    check_domain_not_depend_on_infrastructure()
    check_no_giant_files_in_app()
    check_no_giant_files_in_modstore_server()
    check_legacy_boundary()


def _baseline_line_for(violation: str) -> str:
    """How a violation is recorded in the baseline.

    Giant-file entries keep a count suffix so the ratchet can freeze growth;
    every other check is stored in its path-keyed form (matching existing style).
    """
    if violation.lstrip().startswith("[giant-file]"):
        pc = _giant_path_and_count(violation)
        if pc:
            path, n = pc
            return f"[giant-file] {path} — {n} lines (max {MAX_FILE_LINES} in app/)"
    return _violation_key(violation)


def _bump_baseline() -> int:
    """Reseed the baseline to exactly the current set of accepted violations.

    Standard ratchet ``--bump`` (cf. coverage_ratchet/layer_ratchet): run it
    deliberately to accept today's state. Freezes giant files at their current
    line counts and refreshes drifted line numbers; brand-new violations
    afterwards still fail. Run: ``python scripts/arch_fitness.py --bump``.
    """
    _run_all_checks()
    lines = sorted({_baseline_line_for(v) for v in VIOLATIONS})
    header = (
        f"# arch_fitness baseline — {len(lines)} accepted violation(s). "
        "Auto-managed by `python scripts/arch_fitness.py --bump`; do not hand-edit counts."
    )
    BASELINE_FILE.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    giant = sum(1 for ln in lines if ln.startswith("[giant-file]"))
    print(
        f"Bumped baseline: {len(lines)} entries ({giant} giant-file ceilings) -> {BASELINE_FILE.name}."
    )
    return 0


def main() -> int:
    if "--bump" in sys.argv or "--bump-giant" in sys.argv:
        return _bump_baseline()

    print("=== Architecture Fitness Check ===\n")

    _run_all_checks()

    new_violations = _classify_violations()
    baselined = len(VIOLATIONS) - len(new_violations)

    if baselined:
        print(
            f"  [baseline] {baselined} known violation(s) suppressed (see arch_fitness_baseline.txt)"
        )

    if new_violations:
        print(f"FAIL {len(new_violations)} new violation(s) (total found {len(VIOLATIONS)}):\n")
        for v in new_violations:
            print(f"  {v}")
        print()
        return 1

    if VIOLATIONS:
        print("PASS: no new violations (baseline only).")
        return 0

    print("PASS: all architecture fitness checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
