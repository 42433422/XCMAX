"""日更分支自动清理（防分支爆炸）。

清理对象（仅前缀白名单，永不误删 main/auto-daily/当前分支）：
- ``cr/*``            单个 CR 短分支
- ``auto/daily-*``    每日汇总分支（``auto/daily`` 长期分支本身受保护）

删除条件（满足其一）：
1. 已合并进 base 分支（``git branch --merged base``）；或
2. 末次提交早于保留窗口 ``MODSTORE_BRANCH_CLEANUP_KEEP_DAYS``（默认 7 天）。

本地删 + 远端删（best-effort）；任何失败不抛错、不阻断日更主链。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CLEAN_PREFIXES = ("cr/", "auto/daily-")
_PROTECTED = {"main", "master", "auto/daily", "HEAD"}


def _git(root: str, args: List[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout, shell=False
    )


def _enabled() -> bool:
    return (os.environ.get("MODSTORE_BRANCH_CLEANUP_ENABLED", "1") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _keep_days() -> int:
    try:
        return max(0, int(os.environ.get("MODSTORE_BRANCH_CLEANUP_KEEP_DAYS", "7")))
    except ValueError:
        return 7


def prune_stale_branches(
    root: str,
    *,
    base: str = "",
    push_remote: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """清理已合并/超期的 cr/* 与 auto/daily-* 分支。返回统计。"""
    if not _enabled():
        return {"ok": True, "skipped": True, "reason": "MODSTORE_BRANCH_CLEANUP_ENABLED=0"}
    try:
        from modstore_server.cr_git_pipeline import is_git_repo

        if not is_git_repo(Path(root)):
            return {"ok": True, "skipped": True, "reason": "not_git_repo"}
    except Exception:
        pass

    remote = (
        push_remote or os.environ.get("MODSTORE_DEPLOY_PUSH_REMOTE", "origin")
    ).strip() or "origin"
    keep_days = _keep_days()
    cutoff = time.time() - keep_days * 86400

    base_ref = (base or os.environ.get("MODSTORE_AUTO_PR_BASE_BRANCH", "")).strip()
    if not base_ref:
        head = _git(root, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"]).stdout.strip()
        base_ref = head.rsplit("/", 1)[-1] if head else "main"

    current = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    # 已合并进 base 的本地分支集合
    merged = set()
    mres = _git(root, ["branch", "--merged", base_ref, "--format=%(refname:short)"])
    if mres.returncode == 0:
        merged = {x.strip() for x in mres.stdout.splitlines() if x.strip()}

    listing = _git(
        root, ["for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads/"]
    )
    deleted_local: List[str] = []
    deleted_remote: List[str] = []
    kept: List[str] = []
    for line in listing.stdout.splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        name, ts_raw = parts[0].strip(), parts[1].strip()
        if name in _PROTECTED or name == current or name == base_ref:
            continue
        if not any(name.startswith(p) for p in _CLEAN_PREFIXES):
            continue
        try:
            ts = float(ts_raw)
        except ValueError:
            ts = 0.0
        is_merged = name in merged
        is_old = ts and ts < cutoff
        if not (is_merged or is_old):
            kept.append(name)
            continue
        if dry_run:
            deleted_local.append(name + ("(merged)" if is_merged else "(old)"))
            continue
        if _git(root, ["branch", "-D", name]).returncode == 0:
            deleted_local.append(name)
        # 远端同名分支也删（best-effort）
        if _git(root, ["push", remote, "--delete", name], timeout=90).returncode == 0:
            deleted_remote.append(name)

    result = {
        "ok": True,
        "base": base_ref,
        "keep_days": keep_days,
        "deleted_local": deleted_local,
        "deleted_remote": deleted_remote,
        "kept": kept,
        "dry_run": dry_run,
    }
    logger.info(
        "branch_janitor: base=%s keep=%dd deleted_local=%d deleted_remote=%d kept=%d dry=%s",
        base_ref,
        keep_days,
        len(deleted_local),
        len(deleted_remote),
        len(kept),
        dry_run,
    )
    return result
