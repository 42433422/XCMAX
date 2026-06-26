"""测试 app.services.relay_gitops 的分支覆盖。

覆盖目标：
- _git / _repo_root / _merge_base_branch / _branch_from_payload
- _verify_merged（自定义验证命令 / py 编译 / 无 py / 语法错误）
- git_diff（缺分支名 / 无差异 / 截断 / origin 未抓到退回本地）
- git_discard（缺分支名 / 推送失败 / 远端 ref 不存在容错）
- git_merge（缺分支名 / worktree 失败 / 合并冲突 / 验证失败 / 推送失败 / 异常）
- handle_git_op（diff / discard / merge / 未知 kind）
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_relay_gitops_module():
    path = Path(__file__).resolve().parents[2] / "app" / "services" / "relay_gitops.py"
    spec = importlib.util.spec_from_file_location("relay_gitops_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay_gitops = _load_relay_gitops_module()


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestGitHelper:
    """_git / _repo_root / _merge_base_branch / _branch_from_payload 分支。"""

    def test_git_runs_subprocess_with_args(self) -> None:
        with patch.object(relay_gitops.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(stdout="ok")
            result = relay_gitops._git("/tmp/repo", "status", timeout=10)
            assert result.stdout == "ok"
            mock_run.assert_called_once()

    def test_repo_root_finds_fhd_parent(self) -> None:
        with patch.object(
            Path, "resolve", return_value=Path("/x/FHD/app/services/relay_gitops.py")
        ):
            root = relay_gitops._repo_root()
            assert root == "/x"

    def test_repo_root_fallback_no_fhd(self) -> None:
        fake_path = MagicMock()
        fake_path.parents = [Path("/a"), Path("/a/b"), Path("/a/b/c"), Path("/a/b/c/d")]
        with patch.object(Path, "resolve", return_value=fake_path):
            root = relay_gitops._repo_root()
            assert root == "/a/b/c/d"

    def test_merge_base_branch_uses_env_var(self) -> None:
        with patch.dict("os.environ", {"XCMAX_GIT_MERGE_BASE": "develop"}):
            assert relay_gitops._merge_base_branch("/repo") == "develop"

    def test_merge_base_branch_uses_symbolic_ref(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(
                relay_gitops, "_git", return_value=_completed(stdout="main\n")
            ) as mock_git,
        ):
            assert relay_gitops._merge_base_branch("/repo") == "main"
            mock_git.assert_called_once()

    def test_merge_base_branch_fallback_when_empty(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_gitops, "_git", return_value=_completed(stdout="")),
        ):
            assert relay_gitops._merge_base_branch("/repo") == "main"

    def test_branch_from_payload_strips_origin_prefix(self) -> None:
        assert relay_gitops._branch_from_payload({"branch": "origin/feature/x"}) == "feature/x"

    def test_branch_from_payload_handles_none_payload(self) -> None:
        assert relay_gitops._branch_from_payload(None) == ""

    def test_branch_from_payload_handles_empty_branch(self) -> None:
        assert relay_gitops._branch_from_payload({"branch": ""}) == ""
        assert relay_gitops._branch_from_payload({"branch": "  "}) == ""


class TestVerifyMerged:
    """_verify_merged 分支覆盖。"""

    def test_custom_verify_command_success(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_CLAUDE_VERIFY_CMD": "true"}):
            with patch.object(relay_gitops.subprocess, "run") as mock_run:
                mock_run.return_value = _completed(returncode=0)
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
                assert ok is True
                assert "通过" in msg

    def test_custom_verify_command_failure(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_CLAUDE_VERIFY_CMD": "false"}):
            with patch.object(relay_gitops.subprocess, "run") as mock_run:
                mock_run.return_value = _completed(stderr="boom", returncode=1)
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
                assert ok is False
                assert "boom" in msg

    def test_custom_verify_command_exception(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_CLAUDE_VERIFY_CMD": "true"}):
            with patch.object(relay_gitops.subprocess, "run", side_effect=Exception("oops")):
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
                assert ok is False
                assert "异常" in msg

    def test_verify_no_py_changes(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_gitops, "_git", return_value=_completed(stdout="readme.md\n")),
        ):
            ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
            assert ok is True
            assert "无 .py" in msg

    def test_verify_py_compile_success(self, tmp_path: Path) -> None:
        py_file = tmp_path / "ok.py"
        py_file.write_text("x = 1\n")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_gitops, "_git", return_value=_completed(stdout="ok.py\n")),
        ):
            ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
            assert ok is True
            assert "1 个 .py" in msg

    def test_verify_py_compile_error(self, tmp_path: Path) -> None:
        py_file = tmp_path / "bad.py"
        py_file.write_text("def (\n")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_gitops, "_git", return_value=_completed(stdout="bad.py\n")),
        ):
            ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
            assert ok is False
            assert "语法错误" in msg

    def test_verify_skips_missing_py_file(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(relay_gitops, "_git", return_value=_completed(stdout="missing.py\n")),
        ):
            ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
            assert ok is True
            # missing.py 在 py 列表中但文件不存在被跳过，仍计为 1 个 .py
            assert "1 个 .py" in msg


class TestGitDiff:
    """git_diff 分支覆盖。"""

    def test_diff_missing_branch_returns_failed(self) -> None:
        result = relay_gitops.git_diff({"branch": ""}, repo="/repo")
        assert result["ok"] is False
        assert result["_relay_status"] == "failed"
        assert "缺少分支名" in result["reply"]

    def test_diff_no_changes_returns_ok(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(stdout="main"),  # symbolic-ref
                _completed(returncode=0),  # fetch
                _completed(stdout="abc123\n"),  # merge-base origin
                _completed(stdout=""),  # diff
                _completed(stdout=""),  # diff --stat
            ]
            result = relay_gitops.git_diff({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True
            assert "没有差异" in result["reply"]

    def test_diff_with_changes_returns_ok(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(stdout="main"),
                _completed(returncode=0),  # fetch
                _completed(stdout="abc123\n"),
                _completed(stdout="diff content"),
                _completed(stdout="stat line"),
            ]
            result = relay_gitops.git_diff({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True
            assert "diff" in result["reply"]

    def test_diff_truncates_long_output(self) -> None:
        long_text = "x" * 7000
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(stdout="main"),
                _completed(returncode=0),  # fetch
                _completed(stdout="abc123\n"),
                _completed(stdout=long_text),
                _completed(stdout="stat"),
            ]
            result = relay_gitops.git_diff({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True
            assert "已截断" in result["reply"]

    def test_diff_fallback_to_local_branch_when_origin_missing(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(stdout="main"),
                _completed(returncode=0),  # fetch
                _completed(stdout=""),  # merge-base origin empty
                _completed(stdout="localbase\n"),  # merge-base local
                _completed(stdout="diff"),
                _completed(stdout="stat"),
            ]
            result = relay_gitops.git_diff({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True


class TestGitDiscard:
    """git_discard 分支覆盖。"""

    def test_discard_missing_branch_returns_failed(self) -> None:
        result = relay_gitops.git_discard({"branch": ""}, repo="/repo")
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_discard_success(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(returncode=0),  # push delete
                _completed(returncode=0),  # branch -D
            ]
            result = relay_gitops.git_discard({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True
            assert "已丢弃" in result["reply"]

    def test_discard_remote_ref_not_exist_is_ok(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(returncode=1, stderr="error: remote ref does not exist"),
                _completed(returncode=0),
            ]
            result = relay_gitops.git_discard({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True

    def test_discard_push_failure_returns_failed(self) -> None:
        with patch.object(relay_gitops, "_git") as mock_git:
            mock_git.side_effect = [
                _completed(returncode=1, stderr="push failed"),
                _completed(returncode=0),
            ]
            result = relay_gitops.git_discard({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "丢弃失败" in result["reply"]


class TestGitMerge:
    """git_merge 分支覆盖。"""

    def test_merge_missing_branch_returns_failed(self) -> None:
        result = relay_gitops.git_merge({"branch": ""}, repo="/repo")
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_merge_worktree_add_failure(self) -> None:
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_verify_merged"),
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch
                _completed(returncode=1, stderr="worktree add failed"),  # worktree add
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "准备合并环境失败" in result["reply"]

    def test_merge_conflict_aborts(self) -> None:
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_verify_merged"),
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch
                _completed(returncode=0),  # worktree add
                _completed(returncode=1, stdout="conflict"),  # merge
                _completed(returncode=0),  # merge --abort
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "冲突" in result["reply"]

    def test_merge_verify_failure(self) -> None:
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_verify_merged", return_value=(False, "verify failed")),
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch
                _completed(returncode=0),  # worktree add
                _completed(returncode=0),  # merge
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "验证未通过" in result["reply"]

    def test_merge_push_failure(self) -> None:
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_verify_merged", return_value=(True, "ok")),
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch
                _completed(returncode=0),  # worktree add
                _completed(returncode=0),  # merge
                _completed(returncode=1, stderr="push failed"),  # push
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "推送" in result["reply"] and "失败" in result["reply"]

    def test_merge_success(self) -> None:
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_verify_merged", return_value=(True, "ok")),
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch
                _completed(returncode=0),  # worktree add
                _completed(returncode=0),  # merge
                _completed(returncode=0),  # push
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is True
            assert "已合并" in result["reply"]

    def test_merge_exception_returns_failed(self) -> None:
        # fetch 在 try 块外，必须成功；worktree add 在 try 块内，抛异常触发 except
        with (
            patch.object(relay_gitops, "_git") as mock_git,
            patch.object(relay_gitops, "_merge_base_branch", return_value="main"),
        ):
            mock_git.side_effect = [
                _completed(returncode=0),  # fetch (outside try, must succeed)
                Exception("boom"),  # worktree add (inside try, triggers except)
                _completed(returncode=0),  # worktree remove (finally)
            ]
            result = relay_gitops.git_merge({"branch": "feature"}, repo="/repo")
            assert result["ok"] is False
            assert "合并异常" in result["reply"]


class TestHandleGitOp:
    """handle_git_op 分支覆盖。"""

    def test_handle_diff(self) -> None:
        with patch.object(relay_gitops, "git_diff", return_value={"ok": True}) as mock_diff:
            result = relay_gitops.handle_git_op("git.diff", {"branch": "x"})
            assert result == {"ok": True}
            mock_diff.assert_called_once()

    def test_handle_discard(self) -> None:
        with patch.object(relay_gitops, "git_discard", return_value={"ok": True}) as mock_d:
            result = relay_gitops.handle_git_op("git.discard", {"branch": "x"})
            assert result == {"ok": True}
            mock_d.assert_called_once()

    def test_handle_merge(self) -> None:
        with patch.object(relay_gitops, "git_merge", return_value={"ok": True}) as mock_m:
            result = relay_gitops.handle_git_op("git.merge", {"branch": "x"})
            assert result == {"ok": True}
            mock_m.assert_called_once()

    def test_handle_unknown_kind(self) -> None:
        result = relay_gitops.handle_git_op("git.unknown", {})
        assert result["ok"] is False
        assert "未知 git 操作" in result["reply"]
