#!/usr/bin/env python3
"""Prune stale / deletable git branches（默认 dry-run，仅输出报告）。

XCMAX 仓库拥有 886 个远端分支 / 193 个本地分支，大量 ``behind main`` 达
121–517，合并冲突成本爆炸。本工具在删除前提供安全性护栏：

- 默认 **dry-run**：只枚举、分类、打印报告，绝不动任何分支。
- 仅加 ``--apply`` 才真正 ``git push origin --delete <branch>`` 删除远端分支。
- 保护清单永不删除：``main`` / ``develop`` / ``release/*`` / 当前分支 / 有开放 PR 的分支。

分类（``--before`` / ``--stale-days`` / ``--behind`` 共同决定）：
- ``active``     最近有提交，不处理。
- ``stale``      超过陈旧阈值无提交（但未合并 / behind 不足 → 仅提示）。
- ``deletable``  已合并进 main + 超过陈旧阈值无提交 + behind 超过阈值 → 安全可删。
- ``protected``  保护清单，永不删除。

分类与 git 执行解耦（纯函数便于单测）：``classify`` / ``is_protected_branch`` /
``resolve_protection`` 只做决策，git 命令集中在 ``run_git`` / 枚举 / 删除函数中。

用法示例：
  python scripts/dev/prune_stale_branches.py            # dry-run 报告
  python scripts/dev/prune_stale_branches.py --list-all # 全量清单（dry-run）
  python scripts/dev/prune_stale_branches.py --apply    # 真正删除可删分支
  python scripts/dev/prune_stale_branches.py --apply --prune-local
  python scripts/dev/prune_stale_branches.py --before 2025-01-01 --behind 50 --stale-days 60
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 脚本位于 FHD/scripts/dev/ → 仓库根（FHD）为 parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

# 分类
ACTIVE = "active"
STALE = "stale"
DELETABLE = "deletable"
PROTECTED = "protected"

# 硬保护：永不删除
_PROTECTED_NAMES = {"main", "develop"}
_PROTECTED_PREFIXES = ("release/",)

# 默认阈值
DEFAULT_STALE_DAYS = 30
DEFAULT_BEHIND = 0


@dataclass
class BranchInfo:
    """单个分支的元数据与决策结果。"""

    name: str
    last_commit_iso: str  # YYYY-MM-DD
    ahead: int = 0  # 分支领先 main 的提交数
    behind: int = 0  # main 领先分支的提交数
    merged: bool = False  # 是否已合并进 main
    open_pr: bool = False
    protected: bool = False
    category: str = ACTIVE
    deletable: bool = False


# --------------------------------------------------------------------------- #
# 纯函数：决策逻辑（与 git 解耦，便于单测）
# --------------------------------------------------------------------------- #


def _parse_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date: {s!r} (expected YYYY-MM-DD)")


def is_protected_branch(name: str, current_branch: str) -> bool:
    """硬保护：main / develop / release/* / 当前分支。"""
    if name in _PROTECTED_NAMES:
        return True
    if name.startswith(_PROTECTED_PREFIXES):
        return True
    return name == current_branch


def resolve_protection(
    name: str, current_branch: str, open_pr: bool, include_open_pr: bool
) -> bool:
    """综合是否受保护。

    开放 PR 分支默认受保护（跳过）；``--also-open-pr`` 时不再因 open PR 受保护
    而进入候选清单，但删除仍被 ``classify`` 通过 ``deletable = not open_pr`` 拦截。
    """
    if is_protected_branch(name, current_branch):
        return True
    return open_pr and not include_open_pr


def classify(
    info: BranchInfo,
    *,
    today: dt.date,
    stale_days: int,
    behind_threshold: int,
    only_before: dt.date | None = None,
) -> BranchInfo:
    """按分类规则给 ``info`` 打上 category + deletable（原地修改并返回）。

    - protected → 不处理。
    - ``only_before`` 之后仍有提交 → active（不纳入清理范围）。
    - 超过 ``stale_days`` 无提交 + 已合并 + behind >= 阈值 → deletable。
    - 仅超过陈旧阈值 → stale；否则 active。
    - 开放 PR 分支永不 ``deletable``（即使落入 deletable 分类也只提示不删除）。
    """
    if info.protected:
        info.category = PROTECTED
        info.deletable = False
        return info

    last = _parse_date(info.last_commit_iso)
    if only_before is not None and last > only_before:
        info.category = ACTIVE
        info.deletable = False
        return info

    stale = last <= today - dt.timedelta(days=stale_days)
    if not stale:
        info.category = ACTIVE
        info.deletable = False
        return info

    if info.merged and info.behind >= behind_threshold:
        info.category = DELETABLE
        info.deletable = not info.open_pr  # 开放 PR 分支永不删除
        return info

    info.category = STALE
    info.deletable = False
    return info


# --------------------------------------------------------------------------- #
# git 执行层
# --------------------------------------------------------------------------- #


def run_git(args: list[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )


def current_branch(cwd: Path = REPO_ROOT) -> str:
    return run_git(["branch", "--show-current"], cwd=cwd).stdout.strip()


def list_open_pr_branches(cwd: Path = REPO_ROOT) -> set[str]:
    """依赖 gh CLI 获取开放 PR 的 head 分支；不可用时返回空集（不阻断）。"""
    try:
        r = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "headRefName",
                "--jq",
                ".[].headRefName",
            ],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    if r.returncode != 0:
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def list_remote_branches(cwd: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """返回 [(分支短名, last-commit YYYY-MM-DD), ...]（refs/remotes/origin）。"""
    r = run_git(
        ["for-each-ref", "refs/remotes/origin", "--format=%(refname:short) %(committerdate:short)"],
        cwd=cwd,
    )
    out: list[tuple[str, str]] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        ref, date = line.rsplit(" ", 1)
        ref = ref.removeprefix("origin/")
        out.append((ref, date.strip()))
    return out


def ahead_behind(name: str, main: str = "main", cwd: Path = REPO_ROOT) -> tuple[int, int]:
    """返回 (ahead, behind)：ahead=分支领先 main，behind=main 领先分支。"""
    r = run_git(
        ["rev-list", "--left-right", "--count", f"origin/{main}...origin/{name}"],
        cwd=cwd,
    )
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def is_merged(name: str, main: str = "main", cwd: Path = REPO_ROOT) -> bool:
    r = run_git(["merge-base", "--is-ancestor", f"origin/{name}", f"origin/{main}"], cwd=cwd)
    return r.returncode == 0


def local_branch_exists(name: str, cwd: Path = REPO_ROOT) -> bool:
    r = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], cwd=cwd)
    return r.returncode == 0


# 删除操作（仅 --apply 时调用）
def delete_remote(name: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return run_git(["push", "origin", "--delete", name], cwd=cwd)


def delete_local(name: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return run_git(["branch", "-D", name], cwd=cwd)


# --------------------------------------------------------------------------- #
# 组装与报告
# --------------------------------------------------------------------------- #


def build_report(
    *,
    before: dt.date | None,
    behind: int,
    stale_days: int,
    include_open_pr: bool,
    cwd: Path = REPO_ROOT,
) -> list[BranchInfo]:
    cur = current_branch(cwd)
    open_pr_names = list_open_pr_branches(cwd)
    infos: list[BranchInfo] = []
    for name, date in list_remote_branches(cwd):
        info = BranchInfo(name=name, last_commit_iso=date)
        info.open_pr = name in open_pr_names
        info.protected = resolve_protection(name, cur, info.open_pr, include_open_pr)
        if not info.protected:
            info.ahead, info.behind = ahead_behind(name, cwd=cwd)
            info.merged = is_merged(name, cwd=cwd)
        classify(
            info,
            today=dt.date.today(),
            stale_days=stale_days,
            behind_threshold=behind,
            only_before=before,
        )
        infos.append(info)
    return infos


def _action_label(info: BranchInfo, apply: bool) -> str:
    if info.category == DELETABLE and info.deletable:
        return "[deleted]" if apply else "[would delete]"
    if info.category == DELETABLE and info.open_pr:
        return "[skipped - open PR]"
    return "[deleted]" if apply and info.category == DELETABLE else "[keep]"


def print_report(
    infos: list[BranchInfo], *, apply: bool, prune_local: bool, list_all: bool
) -> None:
    order = {DELETABLE: 0, STALE: 1, ACTIVE: 2, PROTECTED: 3}
    rows = sorted(infos, key=lambda i: (order[i.category], i.name))

    mode = "apply" if apply else "dry-run"
    print(f"Branch report (mode={mode}, prune_local={prune_local}, stale_days filter on)")
    print(f"{'CLASS':<11}{'BRANCH':<46}{'LAST':<12}{'BEHIND':>7}{'AHEAD':>6}  ACTION")
    print("-" * 112)

    for info in rows:
        # 默认只突出 stale / deletable；--list-all 才展示 active / protected
        if info.category in (ACTIVE, PROTECTED) and not list_all:
            continue
        action = _action_label(info, apply)
        print(
            f"{info.category:<11}{info.name:<46}{info.last_commit_iso:<12}"
            f"{info.behind:>7}{info.ahead:>6}  {action}"
        )

    counts = Counter(i.category for i in infos)
    deletable = [i for i in infos if i.category == DELETABLE and i.deletable]
    pr_candidates = [i for i in infos if i.category == DELETABLE and i.open_pr]

    print("-" * 112)
    print(
        f"Summary: protected={counts[PROTECTED]} active={counts[ACTIVE]} "
        f"stale={counts[STALE]} deletable={len(deletable)}"
    )
    if pr_candidates:
        print(
            f"  note: {len(pr_candidates)} open-PR branches shown as candidates "
            "but will NOT be deleted"
        )
    print(
        f"  {'dry-run: would delete' if not apply else 'apply: deleted/deleting'} "
        f"{len(deletable)} remote branch(es)"
    )


def apply_deletions(
    infos: list[BranchInfo], *, prune_local: bool, cwd: Path = REPO_ROOT
) -> tuple[int, int]:
    """只删除 deletable（排除 open PR / protected / stale）。"""
    deleted = 0
    failed = 0
    for info in infos:
        if info.category != DELETABLE or not info.deletable:
            continue
        r = delete_remote(info.name, cwd=cwd)
        if r.returncode == 0:
            deleted += 1
            print(f"  [deleted] remote {info.name}")
        else:
            failed += 1
            print(f"  !! failed to delete remote {info.name}: {r.stderr.strip()}")
        if prune_local and local_branch_exists(info.name, cwd=cwd):
            rl = delete_local(info.name, cwd=cwd)
            if rl.returncode == 0:
                print(f"  [deleted] local {info.name}")
            else:
                print(f"  !! failed to delete local {info.name}: {rl.stderr.strip()}")
    return deleted, failed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="真正删除可删（deletable）的远端分支（默认 dry-run 仅报告）",
    )
    p.add_argument(
        "--prune-local",
        action="store_true",
        help="在 --apply 时追加清理本地对应分支（git branch -D）",
    )
    p.add_argument(
        "--list-all",
        action="store_true",
        help="输出全量清单（含 active/protected），默认只突出 stale/deletable",
    )
    p.add_argument(
        "--also-open-pr", action="store_true", help="把有开放 PR 的分支纳入候选提示（但绝不删除）"
    )
    p.add_argument(
        "--before",
        type=_parse_date,
        default=None,
        help="只处理该日期（YYYY-MM-DD）之前无提交的分支；更近的视为 active",
    )
    p.add_argument(
        "--behind",
        type=int,
        default=DEFAULT_BEHIND,
        help=f"deletable 的 behind main 阈值（默认 {DEFAULT_BEHIND}）",
    )
    p.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"陈旧天数阈值，超过该天数无提交视为 stale/deletable（默认 {DEFAULT_STALE_DAYS}）",
    )
    p.add_argument("--repo", type=Path, default=None, help="git 仓库根目录（默认自动探测为 FHD）")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = args.repo or REPO_ROOT
    infos = build_report(
        before=args.before,
        behind=args.behind,
        stale_days=args.stale_days,
        include_open_pr=args.also_open_pr,
        cwd=project_root,
    )
    print_report(
        infos,
        apply=args.apply,
        prune_local=args.prune_local,
        list_all=args.list_all,
    )
    if args.apply:
        print("\nRunning deletions...")
        deleted, failed = apply_deletions(infos, prune_local=args.prune_local, cwd=project_root)
        print(f"Deletion complete: deleted={deleted} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
