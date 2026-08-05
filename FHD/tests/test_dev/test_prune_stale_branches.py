"""test_prune_stale_branches.py — scripts/dev/prune_stale_branches.py 单元测试。

覆盖：
- 分类纯函数（classify）：active / stale / deletable / protected 边界
- 保护规则（is_protected_branch / resolve_protection）：main/develop/release/*/当前分支/开放 PR
- --before / --behind / --stale-days 阈值
- 开放 PR 分支永不 deletable（即使 --also-open-pr 纳入候选也只提示不删除）
- apply_deletions：dry-run 不删、仅 deletable 才会调用 git push --delete
- parse_args 默认值
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev import prune_stale_branches as psb

TODAY = dt.date(2026, 8, 5)
OLD = "2025-01-01"  # 远早于 stale_days
RECENT = "2026-07-20"  # 距 TODAY(2026-08-05) 16 天，在 stale_days=30 内 → active


def _mk(
    name: str,
    date: str = OLD,
    ahead: int = 0,
    behind: int = 10,
    merged: bool = True,
    open_pr: bool = False,
    protected: bool = False,
) -> psb.BranchInfo:
    return psb.BranchInfo(
        name=name,
        last_commit_iso=date,
        ahead=ahead,
        behind=behind,
        merged=merged,
        open_pr=open_pr,
        protected=protected,
    )


def _classify(info: psb.BranchInfo, **kw) -> psb.BranchInfo:
    return psb.classify(
        info,
        today=TODAY,
        stale_days=kw.pop("stale_days", 30),
        behind_threshold=kw.pop("behind_threshold", 0),
        only_before=kw.pop("only_before", None),
    )


# --------------------------------------------------------------------------- #
# 保护规则
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["main", "develop", "release/1.0", "release/v2.0.1"])
def test_is_protected_reserved(name: str):
    assert psb.is_protected_branch(name, current_branch="feat/desktop-native-capabilities")


def test_is_protected_current_branch():
    assert psb.is_protected_branch(
        "feat/desktop-native-capabilities", "feat/desktop-native-capabilities"
    )


def test_is_protected_not_for_feature():
    assert not psb.is_protected_branch("feat/foo", "feat/desktop-native-capabilities")


def test_resolve_protection_open_pr_default_protected():
    # 默认：开放 PR 分支受保护（跳过）
    assert psb.resolve_protection("feat/foo", "cur", open_pr=True, include_open_pr=False)


def test_resolve_protection_open_pr_included_when_flag():
    # --also-open-pr：开放 PR 分支不再因 open PR 受保护，进入候选
    assert not psb.resolve_protection("feat/foo", "cur", open_pr=True, include_open_pr=True)


def test_resolve_protection_non_pr_feature():
    assert not psb.resolve_protection("feat/foo", "cur", open_pr=False, include_open_pr=False)


# --------------------------------------------------------------------------- #
# 分类
# --------------------------------------------------------------------------- #


def test_classify_protected_never_deletable():
    info = _mk("main", protected=True, merged=True)
    _classify(info)
    assert info.category == psb.PROTECTED
    assert info.deletable is False


def test_classify_recent_is_active():
    info = _mk("feat/recent", date=RECENT)
    _classify(info)
    assert info.category == psb.ACTIVE
    assert info.deletable is False


def test_classify_stale_not_merged():
    info = _mk("feat/stale-unmerged", merged=False)
    _classify(info)
    assert info.category == psb.STALE
    assert info.deletable is False


def test_classify_stale_merged_but_behind_below_threshold():
    # behind(10) < 阈值(50) → 仅 stale，不可删
    info = _mk("feat/behind-low", behind=10, merged=True)
    _classify(info, behind_threshold=50)
    assert info.category == psb.STALE
    assert info.deletable is False


def test_classify_deletable():
    info = _mk("feat/merged-stale", behind=121, merged=True)
    _classify(info)
    assert info.category == psb.DELETABLE
    assert info.deletable is True


def test_classify_stale_days_threshold():
    # 13 天前提交，stale_days=30 → 不陈旧 → active
    recent = (TODAY - dt.timedelta(days=13)).isoformat()
    info = _mk("feat/13-days", date=recent)
    _classify(info, stale_days=30)
    assert info.category == psb.ACTIVE
    # 但 stale_days=7 → 陈旧且已合并 → deletable
    info2 = _mk("feat/13-days-7", date=recent)
    _classify(info2, stale_days=7)
    assert info2.category == psb.DELETABLE


def test_classify_before_filter_recent_branch_excluded():
    # only_before=2025-06-01，但分支 2026-07-01 有提交 → active（不纳入清理）
    info = _mk("feat/after-before", date="2026-07-01", merged=True)
    _classify(info, only_before=dt.date(2025, 6, 1))
    assert info.category == psb.ACTIVE
    assert info.deletable is False


def test_classify_before_filter_old_branch_eligible():
    info = _mk("feat/before-cutoff", date="2025-01-01", merged=True)
    _classify(info, only_before=dt.date(2025, 6, 1))
    assert info.category == psb.DELETABLE


def test_classify_open_pr_keeps_category_but_never_deletable():
    # 开放 PR + 已合并 + 陈旧 + behind 足够 → 落入 deletable 分类，但 deletable=False
    info = _mk("feat/open-pr", open_pr=True, behind=200, merged=True)
    _classify(info)
    assert info.category == psb.DELETABLE
    assert info.deletable is False


# --------------------------------------------------------------------------- #
# 删除执行
# --------------------------------------------------------------------------- #


def test_apply_deletions_only_deletes_deletable(tmp_path: Path):
    deletable = _mk("feat/to-delete", behind=100, merged=True)
    _classify(deletable)
    open_pr_candidate = _mk("feat/open-pr-candidate", behind=100, merged=True, open_pr=True)
    _classify(open_pr_candidate)
    stale = _mk("feat/stale-keep", merged=False)
    _classify(stale)
    protected = _mk("release/1.0", protected=True)
    _classify(protected)

    deleted_remote: list[str] = []
    deleted_local: list[str] = []

    class _R:
        returncode = 0
        stderr = ""

    with (
        patch.object(
            psb,
            "delete_remote",
            side_effect=lambda n, cwd=None: (_R(), deleted_remote.append(n))[0],
        ),
        patch.object(
            psb, "delete_local", side_effect=lambda n, cwd=None: (_R(), deleted_local.append(n))[0]
        ),
        patch.object(psb, "local_branch_exists", return_value=True),
    ):
        deleted, failed = psb.apply_deletions(
            [deletable, open_pr_candidate, stale, protected],
            prune_local=True,
            cwd=tmp_path,
        )

    assert deleted == 1
    assert failed == 0
    assert deleted_remote == ["feat/to-delete"]
    assert deleted_local == ["feat/to-delete"]
    # 开放 PR / stale / protected 不会被删除
    assert "feat/open-pr-candidate" not in deleted_remote
    assert "feat/stale-keep" not in deleted_remote
    assert "release/1.0" not in deleted_remote


def test_apply_deletions_does_not_touch_local_without_prune_local(tmp_path: Path):
    deletable = _mk("feat/to-delete-remote-only", behind=50, merged=True)
    _classify(deletable)

    class _R:
        returncode = 0
        stderr = ""

    with (
        patch.object(psb, "delete_remote", return_value=_R()),
        patch.object(psb, "delete_local") as dl,
        patch.object(psb, "local_branch_exists", return_value=True),
    ):
        psb.apply_deletions([deletable], prune_local=False, cwd=tmp_path)

    dl.assert_not_called()


def test_dry_run_defaults_do_not_delete():
    ns = psb.parse_args([])
    assert ns.apply is False
    assert ns.list_all is False
    assert ns.prune_local is False
    assert ns.also_open_pr is False
    assert ns.before is None
    assert ns.behind == psb.DEFAULT_BEHIND
    assert ns.stale_days == psb.DEFAULT_STALE_DAYS


def test_parse_args_apply_flag():
    ns = psb.parse_args(
        [
            "--apply",
            "--prune-local",
            "--before",
            "2025-01-01",
            "--behind",
            "50",
            "--stale-days",
            "60",
        ]
    )
    assert ns.apply is True
    assert ns.prune_local is True
    assert ns.before == dt.date(2025, 1, 1)
    assert ns.behind == 50
    assert ns.stale_days == 60


def test_parse_args_invalid_date():
    with pytest.raises(SystemExit):
        psb.parse_args(["--before", "not-a-date"])


def test_main_dry_run_does_not_call_apply_deletions(tmp_path: Path):
    # dry-run（无 --apply）：apply_deletions 绝不被调用
    with (
        patch.object(psb, "build_report", return_value=[]),
        patch.object(psb, "print_report"),
        patch.object(psb, "apply_deletions") as app,
    ):
        rc = psb.main(["--repo", str(tmp_path)])
    assert rc == 0
    app.assert_not_called()


def test_main_apply_calls_apply_deletions(tmp_path: Path):
    with (
        patch.object(psb, "build_report", return_value=[]),
        patch.object(psb, "print_report"),
        patch.object(psb, "apply_deletions", return_value=(0, 0)) as app,
    ):
        rc = psb.main(["--apply", "--repo", str(tmp_path)])
    assert rc == 0
    app.assert_called_once()
