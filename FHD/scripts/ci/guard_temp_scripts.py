#!/usr/bin/env python3
"""Block tracked temporary diagnostics and newly added throwaway scripts."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_BASENAMES = {"_find_zero.py", "_analyze_coverage.py"}
TEMP_PREFIXES = ("fix_", "check_", "final_")


def _git(*args: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(FHD_ROOT), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _repo_root() -> Path:
    roots = _git("rev-parse", "--show-toplevel")
    return Path(roots[0]) if roots else FHD_ROOT


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def _fhd_rel(path: str) -> str:
    norm = _norm(path)
    return norm.removeprefix("FHD/")


def _is_allowed_temp_home(path: str) -> bool:
    rel = _fhd_rel(path)
    return rel.startswith(
        (
            "XCAGI/tools/",
            "XCAGI/archive/",
            "tools/",
            "archive/",
            "scripts/launchers/",
        )
    )


def _is_forbidden_basename(path: str) -> bool:
    return Path(_norm(path)).name in FORBIDDEN_BASENAMES


def _is_new_throwaway(path: str) -> bool:
    if _is_allowed_temp_home(path):
        return False
    rel = _fhd_rel(path)
    basename = Path(rel).name
    if _is_forbidden_basename(path):
        return True
    if re.match(r"_fail.*\.txt$", basename):
        return True
    if basename.endswith(".v1_backup"):
        return True
    if not basename.endswith(".py") or not basename.startswith(TEMP_PREFIXES):
        return False
    if "/" not in rel:
        return True
    if re.match(r"scripts/[^/]+\.py$", rel):
        return True
    return bool(re.match(r"(.*/)?产品文件夹/[^/]+\.py$", rel))


def _read_stdin_paths() -> list[str]:
    if sys.stdin.isatty():
        return []
    return [_norm(line) for line in sys.stdin.read().splitlines() if line.strip()]


def _report(kind: str, paths: list[str]) -> int:
    if not paths:
        return 0
    print(f"Forbidden temporary artifacts ({kind}):", file=sys.stderr)
    for path in sorted(dict.fromkeys(paths)):
        print(f"  - {path}", file=sys.stderr)
    print(
        "Move durable helpers under tools/, scripts/dev/, scripts/ci/, or archive with a real name; "
        "do not commit throwaway diagnostics such as _find_zero.py or _analyze_coverage.py.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-tracked", action="store_true", help="scan all tracked files for globally forbidden names")
    parser.add_argument("--added-from-git", action="store_true", help="scan staged added files for throwaway patterns")
    parser.add_argument("--added-from-stdin", action="store_true", help="scan newline-delimited added files from stdin")
    parser.add_argument("paths", nargs="*", help="changed paths to scan for globally forbidden names")
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    forbidden_existing: list[str] = []
    if args.all_tracked:
        forbidden_existing.extend(
            path
            for path in _git("ls-files", "--full-name")
            if (repo_root / _norm(path)).exists() and _is_forbidden_basename(path)
        )
    forbidden_existing.extend(
        path
        for path in args.paths
        if (repo_root / _norm(path)).exists() and _is_forbidden_basename(path)
    )

    added_paths: list[str] = []
    if args.added_from_git:
        added_paths.extend(_git("diff", "--cached", "--name-only", "--diff-filter=A"))
    if args.added_from_stdin:
        added_paths.extend(_read_stdin_paths())

    forbidden_added = [path for path in added_paths if _is_new_throwaway(path)]
    return _report("tracked", forbidden_existing) or _report("newly added", forbidden_added)


if __name__ == "__main__":
    raise SystemExit(main())
