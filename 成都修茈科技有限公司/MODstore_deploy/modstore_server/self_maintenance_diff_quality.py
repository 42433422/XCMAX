"""Run formatter gates against every changed MODstore Python file."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

_SAFE_GIT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_MODSTORE_PYTHON_SCOPES = ("modman/", "modstore_server/", "tests/")


def _validate_git_ref(value: str) -> str:
    ref = str(value or "").strip()
    if not _SAFE_GIT_REF.fullmatch(ref) or ref.startswith("-") or ".." in ref:
        raise ValueError(f"unsafe git ref: {ref!r}")
    return ref


def changed_modstore_python_files(
    *,
    base_ref: str,
    target_ref: str,
    repo_root: Path,
    modstore_root: Path,
) -> list[str]:
    """Return the exact changed Python targets, relative to MODstore root."""

    base = _validate_git_ref(base_ref)
    target = _validate_git_ref(target_ref)
    if base == target:
        raise ValueError("base and target refs must differ")
    diff_spec = base if target == "WORKTREE" else f"{base}...{target}"
    proc = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
            diff_spec,
            "--",
            "*.py",
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"git diff failed with exit {proc.returncode}: {detail}")

    raw_paths = list((proc.stdout or b"").split(b"\0"))
    if target == "WORKTREE":
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "*.py"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if untracked.returncode != 0:
            detail = (untracked.stderr or b"").decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"git ls-files failed with exit {untracked.returncode}: {detail}")
        raw_paths.extend((untracked.stdout or b"").split(b"\0"))

    prefix = modstore_root.resolve().relative_to(repo_root.resolve()).as_posix().rstrip("/") + "/"
    targets: list[str] = []
    for raw_path in raw_paths:
        if not raw_path:
            continue
        repo_path = raw_path.decode("utf-8", errors="strict").replace("\\", "/")
        if not repo_path.startswith(prefix):
            continue
        relative = repo_path[len(prefix) :]
        if relative.endswith(".py") and relative.startswith(_MODSTORE_PYTHON_SCOPES):
            targets.append(relative)
    return sorted(set(targets))


def run_quality_tool(
    *,
    tool: str,
    base_ref: str,
    target_ref: str,
    repo_root: Path,
    modstore_root: Path,
) -> int:
    """Execute Black or isort on the complete changed-file set."""

    targets = changed_modstore_python_files(
        base_ref=base_ref,
        target_ref=target_ref,
        repo_root=repo_root,
        modstore_root=modstore_root,
    )
    if tool == "black":
        args: Sequence[str] = (sys.executable, "-m", "black", "--check", *targets)
    elif tool == "isort":
        args = (sys.executable, "-m", "isort", "--check-only", "--diff", *targets)
    else:
        raise ValueError(f"unsupported quality tool: {tool!r}")

    if not targets:
        print(
            json.dumps(
                {
                    "base_ref": base_ref,
                    "status": "passed_no_changed_python_files",
                    "target_ref": target_ref,
                    "tool": tool,
                },
                sort_keys=True,
            )
        )
        return 0
    proc = subprocess.run(list(args), cwd=modstore_root, check=False)
    return int(proc.returncode)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", choices=("black", "isort"), required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--target-ref", required=True)
    args = parser.parse_args(argv)
    modstore_root = Path(__file__).resolve().parents[1]
    repo_root = modstore_root.parents[1]
    return run_quality_tool(
        tool=args.tool,
        base_ref=args.base_ref,
        target_ref=args.target_ref,
        repo_root=repo_root,
        modstore_root=modstore_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
