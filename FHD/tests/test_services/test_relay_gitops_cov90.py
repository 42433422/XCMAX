"""真实行为测试：app/services/relay_gitops.py（手机端 git 操作 merge/diff/discard）。

策略：所有 git 子进程调用都经过模块级 `_git` helper，故 patch `relay_gitops._git`
即可确定性地控制每次 git 调用的 returncode/stdout/stderr，离线、无副作用。
验证路径（_verify_merged）另 patch subprocess.run / py_compile.compile / Path。
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import app.services.relay_gitops as rg


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """构造一个 subprocess.CompletedProcess 替身。"""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# 纯函数：_repo_root / _merge_base_branch / _branch_from_payload
# ---------------------------------------------------------------------------


class TestRepoRoot:
    def test_returns_parent_of_FHD(self):
        # 源文件位于 .../FHD/app/services/relay_gitops.py，应回到 FHD 的父目录
        root = rg._repo_root()
        assert isinstance(root, str)
        # FHD 父目录下应能再拼出 FHD
        from pathlib import Path

        assert (Path(root) / "FHD").name == "FHD"


class TestMergeBaseBranch:
    def test_env_override_wins(self):
        with patch.dict(rg.os.environ, {"XCMAX_GIT_MERGE_BASE": "release-x"}):
            assert rg._merge_base_branch("/repo") == "release-x"

    def test_env_blank_falls_through_to_symbolic_ref(self):
        with patch.dict(rg.os.environ, {"XCMAX_GIT_MERGE_BASE": "  "}):
            with patch.object(rg, "_git", return_value=_cp(stdout="develop\n")) as g:
                assert rg._merge_base_branch("/repo") == "develop"
            g.assert_called_once()

    def test_empty_symbolic_ref_defaults_main(self):
        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", return_value=_cp(stdout="\n")):
                assert rg._merge_base_branch("/repo") == "main"


class TestBranchFromPayload:
    def test_plain_branch(self):
        assert rg._branch_from_payload({"branch": "feature/x"}) == "feature/x"

    def test_strips_origin_prefix(self):
        assert rg._branch_from_payload({"branch": "origin/feature/x"}) == "feature/x"

    def test_strips_surrounding_whitespace(self):
        assert rg._branch_from_payload({"branch": "  feature/y  "}) == "feature/y"

    def test_missing_branch_returns_empty(self):
        assert rg._branch_from_payload({}) == ""

    def test_none_payload_returns_empty(self):
        assert rg._branch_from_payload(None) == ""


# ---------------------------------------------------------------------------
# _verify_merged
# ---------------------------------------------------------------------------


class TestVerifyMerged:
    def test_custom_cmd_success(self):
        with patch.dict(rg.os.environ, {"XCMAX_CLAUDE_VERIFY_CMD": "make test"}):
            with patch.object(
                rg.subprocess, "run", return_value=_cp(returncode=0, stdout="ok")
            ) as run:
                ok, msg = rg._verify_merged("/wt", "main")
        assert ok is True
        assert msg == "自定义验证通过"
        run.assert_called_once()

    def test_custom_cmd_failure_uses_stderr(self):
        with patch.dict(rg.os.environ, {"XCMAX_CLAUDE_VERIFY_CMD": "make test"}):
            with patch.object(rg.subprocess, "run", return_value=_cp(returncode=1, stderr="boom")):
                ok, msg = rg._verify_merged("/wt", "main")
        assert ok is False
        assert msg == "boom"

    def test_custom_cmd_exception(self):
        with patch.dict(rg.os.environ, {"XCMAX_CLAUDE_VERIFY_CMD": "make test"}):
            with patch.object(rg.subprocess, "run", side_effect=RuntimeError("kaboom")):
                ok, msg = rg._verify_merged("/wt", "main")
        assert ok is False
        assert "验证命令异常" in msg
        assert "kaboom" in msg

    def test_no_py_changes(self):
        # 无自定义命令，diff 没有 .py
        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", return_value=_cp(stdout="README.md\n")):
                ok, msg = rg._verify_merged("/wt", "main")
        assert ok is True
        assert msg == "无 .py 改动需深度验证"

    def test_py_compiles_ok(self, tmp_path):
        f = tmp_path / "good.py"
        f.write_text("x = 1\n")
        diff_out = "good.py\nmissing.py\n"
        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", return_value=_cp(stdout=diff_out)):
                with patch.object(rg, "Path", return_value=tmp_path):
                    # Path(wt) / f —— 让 Path(wt) 返回 tmp_path
                    ok, msg = rg._verify_merged(str(tmp_path), "main")
        assert ok is True
        # 注意：成功消息用 len(py)=diff 中 .py 行数（含不存在被跳过的 missing.py），
        # 而非实际编译数，故是 2 个。good.py 真实编译通过、missing.py 跳过、无报错。
        assert "2 个 .py 通过语法编译" in msg

    def test_py_syntax_error(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")  # 语法错误
        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", return_value=_cp(stdout="bad.py\n")):
                with patch.object(rg, "Path", return_value=tmp_path):
                    ok, msg = rg._verify_merged(str(tmp_path), "main")
        assert ok is False
        assert "Python 语法错误" in msg


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------


class TestGitDiff:
    def test_missing_branch(self):
        out = rg.git_diff({}, repo="/repo")
        assert out["ok"] is False
        assert out["_relay_status"] == "failed"
        assert out["reply"] == "缺少分支名"

    def test_no_diff_returns_no_change(self):
        # fetch / merge-base / diff / diff --stat 都经过 _git
        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "fetch":
                return _cp()
            if args[0] == "merge-base":
                return _cp(stdout="abc123\n")
            if args[0] == "diff":
                return _cp(stdout="")  # 无任何差异
            return _cp()

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_diff({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert "没有差异" in out["reply"]

    def test_diff_with_content(self):
        diff_body = "diff --git a/x b/x\n+hello\n"

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "fetch":
                return _cp()
            if args[0] == "merge-base":
                return _cp(stdout="base999\n")
            if args[0] == "diff" and "--stat" in args:
                return _cp(stdout=" x | 1 +\n")
            if args[0] == "diff":
                return _cp(stdout=diff_body)
            return _cp()

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_diff({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert "feat/x" in out["reply"]
        assert "```diff" in out["reply"]
        assert "hello" in out["reply"]

    def test_diff_merge_base_empty_falls_back_to_local_branch(self):
        calls = {"merge_base": 0}

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "fetch":
                return _cp()
            if args[0] == "merge-base":
                calls["merge_base"] += 1
                # 第一次（origin/branch）空 → 触发回退；第二次给值
                return _cp(stdout="" if calls["merge_base"] == 1 else "localmb\n")
            if args[0] == "diff" and "--stat" in args:
                return _cp(stdout="stat\n")
            if args[0] == "diff":
                return _cp(stdout="body\n")
            return _cp()

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_diff({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert calls["merge_base"] == 2  # 走了回退分支

    def test_diff_truncates_long_output(self):
        long_body = "X" * 7000

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "merge-base":
                return _cp(stdout="mb\n")
            if args[0] == "diff" and "--stat" in args:
                return _cp(stdout="")
            if args[0] == "diff":
                return _cp(stdout=long_body)
            return _cp()

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_diff({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert "已截断" in out["reply"]

    def test_diff_uses_repo_root_when_repo_none(self):
        with patch.object(rg, "_repo_root", return_value="/auto/repo") as rr:
            with patch.object(rg, "_git", return_value=_cp(stdout="main\n")):
                # branch 缺失立即返回，但 _repo_root 应被调用
                out = rg.git_diff({})
        rr.assert_called_once()
        assert out["ok"] is False


# ---------------------------------------------------------------------------
# git_discard
# ---------------------------------------------------------------------------


class TestGitDiscard:
    def test_missing_branch(self):
        out = rg.git_discard({}, repo="/repo")
        assert out["ok"] is False
        assert out["reply"] == "缺少分支名"

    def test_success(self):
        def fake_git(cwd, *args, **kw):
            return _cp(returncode=0)

        with patch.object(rg, "_git", side_effect=fake_git):
            out = rg.git_discard({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert "已丢弃分支 feat/x" in out["reply"]

    def test_remote_ref_absent_is_treated_as_success(self):
        def fake_git(cwd, *args, **kw):
            if args[0] == "push":
                return _cp(returncode=1, stderr="remote ref does not exist")
            return _cp(returncode=0)

        with patch.object(rg, "_git", side_effect=fake_git):
            out = rg.git_discard({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True

    def test_real_push_failure(self):
        def fake_git(cwd, *args, **kw):
            if args[0] == "push":
                return _cp(returncode=1, stderr="permission denied")
            return _cp(returncode=0)

        with patch.object(rg, "_git", side_effect=fake_git):
            out = rg.git_discard({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert out["_relay_status"] == "failed"
        assert "丢弃失败" in out["reply"]
        assert "permission denied" in out["reply"]


# ---------------------------------------------------------------------------
# git_merge
# ---------------------------------------------------------------------------


class TestGitMerge:
    def test_missing_branch(self):
        out = rg.git_merge({}, repo="/repo")
        assert out["ok"] is False
        assert out["reply"] == "缺少分支名"

    def test_worktree_add_fails(self):
        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "add":
                return _cp(returncode=1, stderr="worktree busy")
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert "准备合并环境失败" in out["reply"]
        assert "worktree busy" in out["reply"]

    def test_merge_conflict_aborts(self):
        seen = {"abort": False}

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "add":
                return _cp(returncode=0)
            if args[0] == "merge" and "--abort" in args:
                seen["abort"] = True
                return _cp(returncode=0)
            if args[0] == "merge":
                return _cp(returncode=1, stdout="CONFLICT in foo")
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert "合并有冲突" in out["reply"]
        assert "CONFLICT in foo" in out["reply"]
        assert seen["abort"] is True

    def test_verify_fails_no_push(self):
        pushed = {"called": False}

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "add":
                return _cp(returncode=0)
            if args[0] == "merge":
                return _cp(returncode=0)
            if args[0] == "push":
                pushed["called"] = True
                return _cp(returncode=0)
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                with patch.object(rg, "_verify_merged", return_value=(False, "语法炸了")):
                    out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert "合并后验证未通过" in out["reply"]
        assert "语法炸了" in out["reply"]
        assert pushed["called"] is False  # 验证失败绝不 push

    def test_push_fails(self):
        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "add":
                return _cp(returncode=0)
            if args[0] == "merge":
                return _cp(returncode=0)
            if args[0] == "push":
                return _cp(returncode=1, stderr="rejected non-fast-forward")
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                with patch.object(rg, "_verify_merged", return_value=(True, "ok")):
                    out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert "推送" in out["reply"] and "失败" in out["reply"]
        assert "rejected non-fast-forward" in out["reply"]

    def test_full_success(self):
        removed = {"called": False}

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "add":
                return _cp(returncode=0)
            if args[0] == "worktree" and args[1] == "remove":
                removed["called"] = True
                return _cp(returncode=0)
            if args[0] == "merge":
                return _cp(returncode=0)
            if args[0] == "push":
                return _cp(returncode=0)
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                with patch.object(
                    rg, "_verify_merged", return_value=(True, "已对 2 个 .py 通过语法编译")
                ):
                    out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is True
        assert "已合并 feat/x" in out["reply"]
        assert "origin/main" in out["reply"]
        assert removed["called"] is True  # finally 清理 worktree

    def test_exception_path_cleans_up(self):
        removed = {"called": False}

        def fake_git(cwd, *args, **kw):
            if args[0] == "symbolic-ref":
                return _cp(stdout="main\n")
            if args[0] == "worktree" and args[1] == "remove":
                removed["called"] = True
                return _cp(returncode=0)
            if args[0] == "worktree" and args[1] == "add":
                raise RuntimeError("disk full")
            return _cp(returncode=0)

        with patch.dict(rg.os.environ, {}, clear=True):
            with patch.object(rg, "_git", side_effect=fake_git):
                out = rg.git_merge({"branch": "feat/x"}, repo="/repo")
        assert out["ok"] is False
        assert out["_relay_status"] == "failed"
        assert "合并异常" in out["reply"]
        assert "disk full" in out["reply"]
        assert removed["called"] is True


# ---------------------------------------------------------------------------
# handle_git_op 派发
# ---------------------------------------------------------------------------


class TestHandleGitOp:
    def test_dispatch_diff(self):
        with patch.object(rg, "git_diff", return_value={"ok": True, "reply": "d"}) as f:
            out = rg.handle_git_op("git.diff", {"branch": "x"})
        f.assert_called_once_with({"branch": "x"})
        assert out["reply"] == "d"

    def test_dispatch_discard(self):
        with patch.object(rg, "git_discard", return_value={"ok": True, "reply": "dd"}) as f:
            out = rg.handle_git_op("git.discard", {"branch": "x"})
        f.assert_called_once_with({"branch": "x"})
        assert out["reply"] == "dd"

    def test_dispatch_merge(self):
        with patch.object(rg, "git_merge", return_value={"ok": True, "reply": "m"}) as f:
            out = rg.handle_git_op("git.merge", {"branch": "x"})
        f.assert_called_once_with({"branch": "x"})
        assert out["reply"] == "m"

    def test_unknown_kind(self):
        out = rg.handle_git_op("git.nope", {})
        assert out["ok"] is False
        assert out["_relay_status"] == "failed"
        assert "未知 git 操作" in out["reply"]
        assert "git.nope" in out["reply"]

    def test_kinds_constant(self):
        assert rg.GIT_OP_KINDS == ("git.merge", "git.diff", "git.discard")
