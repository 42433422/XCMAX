#!/usr/bin/env python3
"""XCMAX 收工清理：删运行时残留，不碰源码 / 未提交业务改动 / 密钥。

优先清理：
- 各处 .retort 运行时（保留 absorption_state.json）
- .xcmax-logs / .xcmax-pids 陈旧文件
- 常见 __pycache__ / .pytest_cache / *.pyc（仅仓库内浅层）
- Para 执行器的陈旧任务克隆、超大日志和历史安装备份
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_MAX_AGE_SEC = int(os.environ.get("XCMAX_CLEAN_LOG_MAX_AGE_SEC") or 7 * 24 * 3600)
PID_MAX_AGE_SEC = int(os.environ.get("XCMAX_CLEAN_PID_MAX_AGE_SEC") or 2 * 24 * 3600)
RUNTIME_WORKSPACE_MAX_AGE_SEC = int(
    os.environ.get("XCMAX_CLEAN_RUNTIME_WORKSPACE_MAX_AGE_SEC") or 2 * 3600
)
RUNTIME_LOG_MAX_BYTES = int(
    os.environ.get("XCMAX_CLEAN_RUNTIME_LOG_MAX_BYTES") or 16 * 1024 * 1024
)
RUNTIME_LOG_TAIL_BYTES = int(
    os.environ.get("XCMAX_CLEAN_RUNTIME_LOG_TAIL_BYTES") or 4 * 1024 * 1024
)
RUNTIME_BACKUP_KEEP = int(os.environ.get("XCMAX_CLEAN_RUNTIME_BACKUP_KEEP") or 3)
TMP_WORKSPACE_ROOT = Path(os.environ.get("XCMAX_CLEAN_TMP_ROOT") or "/private/tmp")
TMP_WORKSPACE_MAX_AGE_SEC = int(
    os.environ.get("XCMAX_CLEAN_TMP_WORKSPACE_MAX_AGE_SEC") or 7 * 24 * 3600
)
TMP_WORKSPACE_PREFIXES = tuple(
    item.strip()
    for item in (
        os.environ.get("XCMAX_CLEAN_TMP_WORKSPACE_PREFIXES") or "xcmax-,xcagi-"
    ).split(",")
    if item.strip()
)
AGENT_RUNTIME_ROOT = Path.home() / "XCMAX-runtime" / "para-main-agent"
FHD_DESKTOP_LOG_ROOT = Path(
    os.environ.get("XCMAX_CLEAN_FHD_DESKTOP_LOG_ROOT")
    or Path.home() / "XCMAX-runtime" / "fhd-desktop" / "logs"
)
_TASK_DIR_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-",
    re.IGNORECASE,
)
_BACKUP_MARKERS = (".backup-", ".backup.", ".bak-", ".bak.")
BOUNDARY_ERRORS = (Exception,)


def _rm_tree(path: Path, removed: list[str]) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    try:
        removed.append(str(path.relative_to(ROOT)))
    except ValueError:
        removed.append(str(path))


def _clean_retort(
    project: Path, removed: list[str], kept: list[str], errors: list[str]
) -> None:
    try:
        sys.path.insert(0, str(ROOT / "packages" / "retort_engine"))
        from retort_engine.workspace_hygiene import clean_workspace

        result = clean_workspace(
            project, keep_durable_state=True, purge_empty_runtime=True
        )
        removed.extend(result.get("removed") or [])
        kept.extend(result.get("kept") or [])
        errors.extend(result.get("errors") or [])
    except BOUNDARY_ERRORS as exc:
        # Fallback: wipe ephemeral under .retort manually
        runtime = project / ".retort"
        if not runtime.exists():
            return
        for child in list(runtime.iterdir()):
            if child.name == "absorption_state.json" and child.is_file():
                kept.append(str(child.relative_to(ROOT)))
                continue
            try:
                _rm_tree(child, removed)
            except OSError as err:
                errors.append(f"{child}: {err}")
        errors.append(f"retort_hygiene_import_fallback:{exc}")


def _clean_aged_dir(path: Path, max_age: int, removed: list[str]) -> None:
    if not path.is_dir():
        return
    now = time.time()
    for item in path.iterdir():
        try:
            age = now - item.stat().st_mtime
        except OSError:
            continue
        if age < max_age:
            continue
        _rm_tree(item, removed)


def _registered_git_worktrees(errors: list[str]) -> set[Path]:
    """Return all worktrees registered by this checkout, resolving stale entries safely."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "list", "--porcelain"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"git_worktree_list: {exc}")
        return set()
    if proc.returncode:
        errors.append(f"git_worktree_list: {proc.stderr.strip() or proc.returncode}")
        return set()
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in proc.stdout.splitlines()
        if line.startswith("worktree ")
    }


def _git_workspace_state(path: Path) -> str:
    """Classify a directory without ever treating an unknown directory as disposable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode:
        return "unknown"
    return "dirty" if proc.stdout.strip() else "clean"


def _candidate_git_roots(path: Path) -> list[Path]:
    """Locate the common task layouts without recursively walking arbitrary temp files."""
    candidates = [path, path / "repo", path / "worktree"]
    return [
        candidate
        for candidate in candidates
        if _git_workspace_state(candidate) != "unknown"
    ]


def _has_registered_worktree(path: Path, registered: set[Path]) -> bool:
    resolved = path.resolve()
    return any(
        worktree == resolved or resolved in worktree.parents for worktree in registered
    )


def _clean_unregistered_temp_workspaces(
    temp_root: Path,
    *,
    max_age: int,
    prefixes: tuple[str, ...],
    removed: list[str],
    kept: list[str],
    errors: list[str],
    registered_worktrees: set[Path] | None = None,
) -> None:
    """Remove only old, clean, unregistered XCMAX task sandboxes.

    A task sandbox is retained when it is an active Git worktree, has uncommitted
    changes, is too recent, or cannot be proven to be a Git workspace.  This
    intentionally favours preserving work over reclaiming disk space.
    """
    if not temp_root.is_dir():
        return
    registered = (
        registered_worktrees
        if registered_worktrees is not None
        else _registered_git_worktrees(errors)
    )
    now = time.time()
    for candidate in temp_root.iterdir():
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or not candidate.name.startswith(prefixes)
        ):
            continue
        try:
            age = now - candidate.stat().st_mtime
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        if _has_registered_worktree(candidate, registered):
            kept.append(f"{candidate}: registered_git_worktree")
            continue
        if age < max_age:
            kept.append(f"{candidate}: retention_window")
            continue
        git_roots = _candidate_git_roots(candidate)
        if len(git_roots) != 1:
            kept.append(f"{candidate}: unproven_temp_workspace")
            continue
        if _git_workspace_state(git_roots[0]) != "clean":
            kept.append(f"{candidate}: uncommitted_changes")
            continue
        try:
            _rm_tree(candidate, removed)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")


def _clean_agent_runtime_workspaces(
    runtime_root: Path,
    *,
    max_age: int,
    removed: list[str],
    errors: list[str],
) -> None:
    workspace = runtime_root / "workspace"
    if not workspace.is_dir():
        return
    now = time.time()
    for item in workspace.iterdir():
        if not item.is_dir() or not _TASK_DIR_RE.match(item.name):
            continue
        try:
            if now - item.stat().st_mtime < max_age:
                continue
            _rm_tree(item, removed)
        except OSError as exc:
            errors.append(f"{item}: {exc}")


def _trim_runtime_logs(
    logs: Path,
    *,
    max_bytes: int,
    tail_bytes: int,
    removed: list[str],
    errors: list[str],
) -> None:
    if not logs.is_dir():
        return
    bounded_tail = max(0, min(tail_bytes, max_bytes))
    for path in logs.glob("*.log"):
        try:
            size = path.stat().st_size
            if size <= max_bytes:
                continue
            with path.open("r+b") as stream:
                stream.seek(max(0, size - bounded_tail))
                tail = stream.read(bounded_tail)
                stream.seek(0)
                stream.write(tail)
                stream.truncate()
            removed.append(f"trimmed:{path}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")


def _trim_agent_runtime_logs(
    runtime_root: Path,
    *,
    max_bytes: int,
    tail_bytes: int,
    removed: list[str],
    errors: list[str],
) -> None:
    _trim_runtime_logs(
        runtime_root / "logs",
        max_bytes=max_bytes,
        tail_bytes=tail_bytes,
        removed=removed,
        errors=errors,
    )


def _prune_agent_runtime_backups(
    runtime_root: Path,
    *,
    keep: int,
    removed: list[str],
    errors: list[str],
) -> None:
    if not runtime_root.is_dir():
        return
    groups: dict[str, list[Path]] = {}
    for path in runtime_root.iterdir():
        if not path.is_file():
            continue
        marker = next((value for value in _BACKUP_MARKERS if value in path.name), "")
        if not marker:
            continue
        groups.setdefault(path.name.split(marker, 1)[0], []).append(path)
    retain = max(0, keep)
    for paths in groups.values():
        try:
            ordered = sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)
        except OSError as exc:
            errors.append(f"runtime_backup_sort: {exc}")
            continue
        for path in ordered[retain:]:
            try:
                _rm_tree(path, removed)
            except OSError as exc:
                errors.append(f"{path}: {exc}")


def _is_git_tracked(path: Path) -> bool:
    try:
        rel = str(path.relative_to(ROOT))
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "--", rel],
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, ValueError):
        return False


def _clean_shallow_caches(removed: list[str]) -> None:
    names = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    # 仅扫浅层，避免全仓 walk 过慢；跳过已被 git 跟踪的目录（少数历史误入库 pyc）
    candidates = [
        ROOT,
        ROOT / "FHD",
        ROOT / "packages" / "retort_engine",
        ROOT / "成都修茈科技有限公司" / "MODstore_deploy",
    ]
    for base in candidates:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.name not in names or not path.is_dir():
                continue
            try:
                depth = len(path.relative_to(base).parts)
            except ValueError:
                continue
            if depth > 6:
                continue
            if _is_git_tracked(path) or any(
                _is_git_tracked(p) for p in path.rglob("*") if p.is_file()
            ):
                continue
            _rm_tree(path, removed)


def main() -> int:
    removed: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    for project in (ROOT, ROOT / "packages" / "retort_engine"):
        _clean_retort(project, removed, kept, errors)

    _clean_aged_dir(ROOT / ".xcmax-logs", LOG_MAX_AGE_SEC, removed)
    _clean_aged_dir(ROOT / ".xcmax-pids", PID_MAX_AGE_SEC, removed)
    _clean_shallow_caches(removed)
    _clean_agent_runtime_workspaces(
        AGENT_RUNTIME_ROOT,
        max_age=RUNTIME_WORKSPACE_MAX_AGE_SEC,
        removed=removed,
        errors=errors,
    )
    _trim_agent_runtime_logs(
        AGENT_RUNTIME_ROOT,
        max_bytes=RUNTIME_LOG_MAX_BYTES,
        tail_bytes=RUNTIME_LOG_TAIL_BYTES,
        removed=removed,
        errors=errors,
    )
    _trim_runtime_logs(
        FHD_DESKTOP_LOG_ROOT,
        max_bytes=RUNTIME_LOG_MAX_BYTES,
        tail_bytes=RUNTIME_LOG_TAIL_BYTES,
        removed=removed,
        errors=errors,
    )
    _prune_agent_runtime_backups(
        AGENT_RUNTIME_ROOT,
        keep=RUNTIME_BACKUP_KEEP,
        removed=removed,
        errors=errors,
    )
    _clean_unregistered_temp_workspaces(
        TMP_WORKSPACE_ROOT,
        max_age=TMP_WORKSPACE_MAX_AGE_SEC,
        prefixes=TMP_WORKSPACE_PREFIXES,
        removed=removed,
        kept=kept,
        errors=errors,
    )

    # 去重
    removed = sorted(set(removed))
    kept = sorted(set(kept))
    payload = {
        "status": "clean" if not errors else "partial",
        "root": str(ROOT),
        "removed_count": len(removed),
        "kept_count": len(kept),
        "error_count": len(errors),
        "removed": removed[:80],
        "kept": kept[:40],
        "errors": errors[:20],
        "first_principle": "clean_workspace_after_every_closed_run",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
