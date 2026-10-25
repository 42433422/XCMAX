"""Run formatter gates against every changed MODstore Python file."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Sequence

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


def _git_blob(
    *,
    repo_root: Path,
    target_ref: str,
    repo_path: str,
) -> bytes:
    """Read one regular-file snapshot from a target Git tree."""

    target = _validate_git_ref(target_ref)
    proc = subprocess.run(
        ["git", "show", f"{target}:{repo_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"git show failed for {repo_path!r} at {target!r} with exit {proc.returncode}: {detail}"
        )
    return proc.stdout or b""


@contextmanager
def _quality_root(
    *,
    target_ref: str,
    targets: Sequence[str],
    repo_root: Path,
    modstore_root: Path,
) -> Iterator[Path]:
    """Yield files from the tree being checked, not the caller's checkout."""

    target = _validate_git_ref(target_ref)
    if target == "WORKTREE":
        yield modstore_root
        return

    modstore_prefix = (
        modstore_root.resolve().relative_to(repo_root.resolve()).as_posix().rstrip("/")
    )
    with TemporaryDirectory(prefix="xcmax-diff-quality-") as temp_dir:
        quality_root = Path(temp_dir) / "MODstore_deploy"
        quality_root.mkdir(parents=True)
        for relative in ("pyproject.toml", *targets):
            destination = quality_root / relative
            if not destination.resolve().is_relative_to(quality_root.resolve()):
                raise ValueError(f"unsafe target path: {relative!r}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(
                _git_blob(
                    repo_root=repo_root,
                    target_ref=target,
                    repo_path=f"{modstore_prefix}/{relative}",
                )
            )
        yield quality_root


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
    if tool == "black":
        args: Sequence[str] = (sys.executable, "-m", "black", "--check", *targets)
    elif tool == "isort":
        args = (sys.executable, "-m", "isort", "--check-only", "--diff", *targets)
    else:
        raise ValueError(f"unsupported quality tool: {tool!r}")

    with _quality_root(
        target_ref=target_ref,
        targets=targets,
        repo_root=repo_root,
        modstore_root=modstore_root,
    ) as checked_root:
        proc = subprocess.run(list(args), cwd=checked_root, check=False)
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
