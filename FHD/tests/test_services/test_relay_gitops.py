"""Branch-coverage ramp for app.services.relay_gitops.

Targets the 45 missing branches in relay_gitops.py (51.1% → 70%+).
Mocks _git / subprocess / py_compile to drive each branch without touching
the real filesystem or git CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import relay_gitops


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# _repo_root
# ---------------------------------------------------------------------------


class TestRepoRoot:
    def test_finds_fhd_parent(self, tmp_path):
        # Construct a fake layout: <tmp>/FHD/app/services/relay_gitops.py
        fhd_dir = tmp_path / "FHD"
        svc_dir = fhd_dir / "app" / "services"
        svc_dir.mkdir(parents=True)
        fake_file = svc_dir / "relay_gitops.py"
        fake_file.write_text("# stub")
        with patch.object(relay_gitops.Path, "resolve", return_value=fake_file):
            with patch.object(relay_gitops, "__file__", str(fake_file)):
                root = relay_gitops._repo_root()
        assert root == str(tmp_path)

    def test_fallback_when_no_fhd_ancestor(self, tmp_path):
        # __file__ deep in a tree without "FHD" parent → fallback parents[3]
        deep = tmp_path / "a" / "b" / "c" / "d" / "relay_gitops.py"
        deep.parent.mkdir(parents=True)
        deep.write_text("# stub")
        with patch.object(relay_gitops.Path, "resolve", return_value=deep):
            with patch.object(relay_gitops, "__file__", str(deep)):
                root = relay_gitops._repo_root()
        # parents[3] of .../a/b/c/d/relay_gitops.py = .../a
        assert root.endswith("/a")


# ---------------------------------------------------------------------------
# _repo_root_from_payload
# ---------------------------------------------------------------------------


class TestRepoRootFromPayload:
    def test_payload_none_returns_repo_root(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value=""
        ):
            with patch.object(relay_gitops, "_repo_root", return_value="/fallback"):
                result = relay_gitops._repo_root_from_payload(None)
        assert result == "/fallback"

    def test_payload_not_dict_returns_repo_root(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value=""
        ):
            with patch.object(relay_gitops, "_repo_root", return_value="/fallback"):
                result = relay_gitops._repo_root_from_payload("not-a-dict")  # type: ignore[arg-type]
        assert result == "/fallback"

    def test_context_not_dict_ignored(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value=""
        ) as m_resolve:
            with patch.object(relay_gitops, "_repo_root", return_value="/fallback"):
                result = relay_gitops._repo_root_from_payload({"context": "not-a-dict"})
        assert result == "/fallback"
        # resolve receives {"workspace_root": None} because context wasn't a dict
        m_resolve.assert_called_once_with({"workspace_root": None})

    def test_workspace_root_from_payload_used(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value="/verified"
        ) as m_resolve:
            result = relay_gitops._repo_root_from_payload({"workspace_root": "/ws"})
        assert result == "/verified"
        m_resolve.assert_called_once_with({"workspace_root": "/ws"})

    def test_workspace_root_from_context_used_when_payload_empty(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value="/verified"
        ) as m_resolve:
            result = relay_gitops._repo_root_from_payload(
                {"context": {"workspace_root": "/ctx-ws"}}
            )
        assert result == "/verified"
        m_resolve.assert_called_once_with({"workspace_root": "/ctx-ws"})

    def test_empty_workspace_root_falls_back_to_context(self):
        with patch.object(
            relay_gitops, "resolve_verified_relay_workspace_root", return_value=""
        ) as m_resolve:
            with patch.object(relay_gitops, "_repo_root", return_value="/fallback"):
                result = relay_gitops._repo_root_from_payload(
                    {"workspace_root": "", "context": {"workspace_root": "/ctx-ws"}}
                )
        assert result == "/fallback"
        m_resolve.assert_called_once_with({"workspace_root": "/ctx-ws"})


# ---------------------------------------------------------------------------
# _merge_base_branch
# ---------------------------------------------------------------------------


class TestMergeBaseBranch:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("XCMAX_GIT_MERGE_BASE", "release/x")
        with patch.object(relay_gitops, "_git") as m_git:
            result = relay_gitops._merge_base_branch("/repo")
        assert result == "release/x"
        m_git.assert_not_called()

    def test_env_override_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("XCMAX_GIT_MERGE_BASE", "  dev/y  ")
        result = relay_gitops._merge_base_branch("/repo")
        assert result == "dev/y"

    def test_env_empty_falls_back_to_symbolic_ref(self, monkeypatch):
        monkeypatch.setenv("XCMAX_GIT_MERGE_BASE", "   ")
        with patch.object(
            relay_gitops, "_git", return_value=_cp(stdout="feature/z\n")
        ) as m_git:
            result = relay_gitops._merge_base_branch("/repo")
        assert result == "feature/z"
        m_git.assert_called_once_with("/repo", "symbolic-ref", "--short", "HEAD", timeout=15)

    def test_symbolic_ref_empty_falls_back_to_main(self, monkeypatch):
        monkeypatch.delenv("XCMAX_GIT_MERGE_BASE", raising=False)
        with patch.object(relay_gitops, "_git", return_value=_cp(stdout="")):
            result = relay_gitops._merge_base_branch("/repo")
        assert result == "main"


# ---------------------------------------------------------------------------
# _branch_from_payload
# ---------------------------------------------------------------------------


class TestBranchFromPayload:
    def test_none_payload_returns_empty(self):
        assert relay_gitops._branch_from_payload(None) == ""

    def test_missing_branch_returns_empty(self):
        assert relay_gitops._branch_from_payload({}) == ""

    def test_plain_branch(self):
        assert relay_gitops._branch_from_payload({"branch": "feat/x"}) == "feat/x"

    def test_origin_prefix_stripped(self):
        assert relay_gitops._branch_from_payload({"branch": "origin/feat/y"}) == "feat/y"

    def test_branch_whitespace_stripped(self):
        assert relay_gitops._branch_from_payload({"branch": "  feat/z  "}) == "feat/z"

    def test_non_origin_prefix_kept(self):
        assert relay_gitops._branch_from_payload({"branch": "upstream/feat"}) == "upstream/feat"


# ---------------------------------------------------------------------------
# _verify_merged
# ---------------------------------------------------------------------------


class TestVerifyMerged:
    def test_custom_cmd_success(self, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "echo ok")
        with patch.object(
            relay_gitops.subprocess, "run", return_value=_cp(returncode=0, stdout="ok")
        ) as m_run:
            ok, msg = relay_gitops._verify_merged("/wt", "main")
        assert ok is True
        assert "自定义验证通过" in msg
        m_run.assert_called_once()

    def test_custom_cmd_failure_returns_stderr(self, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "false")
        with patch.object(
            relay_gitops.subprocess, "run", return_value=_cp(returncode=1, stderr="boom")
        ):
            ok, msg = relay_gitops._verify_merged("/wt", "main")
        assert ok is False
        assert "boom" in msg

    def test_custom_cmd_failure_falls_back_to_stdout(self, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "false")
        with patch.object(
            relay_gitops.subprocess, "run", return_value=_cp(returncode=1, stdout="only-stdout")
        ):
            ok, msg = relay_gitops._verify_merged("/wt", "main")
        assert ok is False
        assert "only-stdout" in msg

    def test_custom_cmd_exception(self, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "bad-cmd")

        def _raise(*a, **kw):
            raise OSError("spawn fail")

        with patch.object(relay_gitops.subprocess, "run", side_effect=_raise):
            ok, msg = relay_gitops._verify_merged("/wt", "main")
        assert ok is False
        assert "验证命令异常" in msg

    def test_default_no_py_changes(self, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        with patch.object(relay_gitops, "_git", return_value=_cp(stdout="")) as m_git:
            ok, msg = relay_gitops._verify_merged("/wt", "main")
        assert ok is True
        assert "无 .py 改动" in msg
        m_git.assert_called_once_with("/wt", "diff", "--name-only", "main..HEAD", timeout=30)

    def test_default_py_files_compile_ok(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        py_file = tmp_path / "a.py"
        py_file.write_text("x = 1")
        with patch.object(relay_gitops, "_git", return_value=_cp(stdout="a.py")):
            with patch.object(relay_gitops.py_compile, "compile") as m_compile:
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
        assert ok is True
        assert "1 个 .py" in msg
        m_compile.assert_called_once()

    def test_default_py_files_missing_skipped(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        # diff lists missing.py but file does not exist → continue (skip compile)
        # Note: py list still counts the missing file, so message says "1 个 .py"
        with patch.object(relay_gitops, "_git", return_value=_cp(stdout="missing.py")):
            with patch.object(relay_gitops.py_compile, "compile") as m_compile:
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
        assert ok is True
        assert "1 个 .py" in msg
        m_compile.assert_not_called()

    def test_default_py_compile_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        py_file = tmp_path / "bad.py"
        py_file.write_text("syntax error")
        compile_err = relay_gitops.py_compile.PyCompileError(
            SyntaxError, SyntaxError("bad"), "bad.py"
        )
        with patch.object(relay_gitops, "_git", return_value=_cp(stdout="bad.py")):
            with patch.object(
                relay_gitops.py_compile,
                "compile",
                side_effect=compile_err,
            ):
                ok, msg = relay_gitops._verify_merged(str(tmp_path), "main")
        assert ok is False
        assert "Python 语法错误" in msg


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------


class TestGitDiff:
    def test_missing_branch_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            result = relay_gitops.git_diff({})
        assert result["ok"] is False
        assert result["_relay_status"] == "failed"
        assert "缺少分支名" in result["reply"]

    def test_no_diff_text_returns_no_changes(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="abc123\n"),  # merge-base origin
                        _cp(stdout=""),  # diff
                        _cp(stdout=""),  # diff --stat
                    ],
                ):
                    result = relay_gitops.git_diff({"branch": "feat/x"})
        assert result["ok"] is True
        assert "没有差异" in result["reply"]

    def test_diff_text_returned(self):
        diff_text = "diff content here"
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="abc123\n"),  # merge-base
                        _cp(stdout=diff_text),  # diff
                        _cp(stdout="stat"),  # diff --stat
                    ],
                ):
                    result = relay_gitops.git_diff({"branch": "feat/x"})
        assert result["ok"] is True
        assert "stat" in result["reply"]
        assert "diff content here" in result["reply"]

    def test_diff_text_truncated_when_over_6000(self):
        big = "x" * 7000
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="abc123\n"),  # merge-base
                        _cp(stdout=big),  # diff
                        _cp(stdout="stat"),  # diff --stat
                    ],
                ):
                    result = relay_gitops.git_diff({"branch": "feat/x"})
        assert result["ok"] is True
        assert "已截断" in result["reply"]

    def test_no_merge_base_falls_back_to_local_branch(self):
        """origin fetch returned no merge-base → ref falls back to local branch."""
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch origin
                        _cp(stdout=""),  # merge-base origin/branch (empty)
                        _cp(stdout="local-mb\n"),  # merge-base local branch
                        _cp(stdout=""),  # diff
                        _cp(stdout=""),  # diff --stat
                    ],
                ) as m_git:
                    result = relay_gitops.git_diff({"branch": "feat/x"})
        assert result["ok"] is True
        # The 3rd call (index 2) is the fallback merge-base using local branch ref
        fallback_call = m_git.call_args_list[2]
        assert fallback_call.args[1] == "merge-base"
        assert fallback_call.args[2] == "feat/x"  # ref=branch (not origin/branch)

    def test_no_merge_base_at_all_uses_base_as_start(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout=""),  # merge-base origin (empty)
                        _cp(stdout=""),  # merge-base local (empty)
                        _cp(stdout=""),  # diff (start=base)
                        _cp(stdout=""),  # diff --stat
                    ],
                ):
                    result = relay_gitops.git_diff({"branch": "feat/x"})
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# _parse_unified_diff
# ---------------------------------------------------------------------------


class TestParseUnifiedDiff:
    def test_empty_text(self):
        assert relay_gitops._parse_unified_diff("") == []

    def test_single_file_with_add_del_context(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " ctx line\n"
            "-old line\n"
            "+new line\n"
        )
        files = relay_gitops._parse_unified_diff(diff)
        assert len(files) == 1
        f = files[0]
        assert f["path"] == "foo.py"
        assert f["additions"] == 1
        assert f["deletions"] == 1
        assert len(f["hunks"]) == 1
        assert len(f["hunks"][0]["lines"]) == 3
        types = [ln["type"] for ln in f["hunks"][0]["lines"]]
        assert types == ["context", "del", "add"]

    def test_multiple_files_and_hunks(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+a\n"
            "@@ -2,1 +2,1 @@\n"
            "+b\n"
            "diff --git a/b.py b/b.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+c\n"
        )
        files = relay_gitops._parse_unified_diff(diff)
        assert len(files) == 2
        assert files[0]["path"] == "a.py"
        assert len(files[0]["hunks"]) == 2
        assert files[1]["path"] == "b.py"
        assert files[1]["additions"] == 1

    def test_hunk_header_without_cur_file_is_skipped(self):
        """@@ header before any 'diff --git' line → cur is None, skipped."""
        diff = "@@ -1,1 +1,1 @@\n+orphan\n"
        files = relay_gitops._parse_unified_diff(diff)
        assert files == []

    def test_diff_line_without_b_prefix(self):
        """diff --git line without ' b/' separator → path empty."""
        diff = "diff --git weird line\n@@ -1,1 +1,1 @@\n+x\n"
        files = relay_gitops._parse_unified_diff(diff)
        assert len(files) == 1
        assert files[0]["path"] == ""

    def test_line_outside_hunk_ignored(self):
        """Lines before any @@ hunk header are ignored (cur_hunk is None)."""
        diff = "diff --git a/x.py b/x.py\norphan line\n@@ -1,1 +1,1 @@\n+real\n"
        files = relay_gitops._parse_unified_diff(diff)
        assert len(files) == 1
        assert len(files[0]["hunks"]) == 1
        assert files[0]["additions"] == 1


# ---------------------------------------------------------------------------
# git_diff_structured
# ---------------------------------------------------------------------------


class TestGitDiffStructured:
    def test_missing_branch_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            result = relay_gitops.git_diff_structured({})
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_no_files_returns_no_diff(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="mb\n"),  # merge-base
                        _cp(stdout=""),  # diff (empty)
                    ],
                ):
                    result = relay_gitops.git_diff_structured({"branch": "feat/x"})
        assert result["ok"] is True
        assert "没有差异" in result["reply"]
        assert result["structured"]["files"] == []

    def test_files_returned_with_totals(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1,1 +1,2 @@\n"
            "+x\n"
            "+y\n"
            "diff --git a/b.py b/b.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-z\n"
        )
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="mb\n"),  # merge-base
                        _cp(stdout=diff),  # diff
                    ],
                ):
                    result = relay_gitops.git_diff_structured({"branch": "feat/x"})
        assert result["ok"] is True
        assert result["structured"]["total_additions"] == 2
        assert result["structured"]["total_deletions"] == 1
        assert len(result["structured"]["files"]) == 2

    def test_no_origin_merge_base_falls_back_to_local(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout=""),  # merge-base origin (empty)
                        _cp(stdout="mb\n"),  # merge-base local
                        _cp(stdout=""),  # diff (empty)
                    ],
                ):
                    result = relay_gitops.git_diff_structured({"branch": "feat/x"})
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


class TestGitLog:
    def test_missing_branch_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            result = relay_gitops.git_log({})
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_log_returns_commits(self):
        log_output = "abc12345|2026-01-01|Alice|fix bug\n"
        show_output = "file.py | 10 +-\n"
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="mb\n"),  # merge-base
                        _cp(stdout=log_output),  # log
                        _cp(stdout=show_output),  # show for commit
                    ],
                ):
                    result = relay_gitops.git_log({"branch": "feat/x", "limit": 5})
        assert result["ok"] is True
        assert len(result["commits"]) == 1
        c = result["commits"][0]
        assert c["hash"] == "abc12345"
        assert c["author"] == "Alice"
        assert c["files_changed"] == 1

    def test_log_skips_malformed_lines(self):
        # Lines with <4 parts get skipped
        log_output = "badline\nabc12345|2026-01-01|Alice|fix bug\n"
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="mb\n"),  # merge-base
                        _cp(stdout=log_output),  # log
                        _cp(stdout=""),  # show for the one valid commit
                    ],
                ):
                    result = relay_gitops.git_log({"branch": "feat/x"})
        assert result["ok"] is True
        assert len(result["commits"]) == 1

    def test_limit_clamped_to_range(self):
        """limit > 20 clamped to 20; < 1 clamped to 1."""
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),  # fetch
                        _cp(stdout="mb\n"),  # merge-base
                        _cp(stdout=""),  # log
                    ],
                ) as m_git:
                    relay_gitops.git_log({"branch": "feat/x", "limit": 100})
        # The log call (index 2) should have "-20" as last arg
        log_call = m_git.call_args_list[2]
        assert log_call.args[-1] == "-20"

    def test_limit_below_one_clamped_to_one(self):
        # limit=-5 is truthy so `or 10` keeps it; min(20,-5)=-5; max(1,-5)=1
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),
                        _cp(stdout="mb\n"),
                        _cp(stdout=""),
                    ],
                ) as m_git:
                    relay_gitops.git_log({"branch": "feat/x", "limit": -5})
        log_call = m_git.call_args_list[2]
        assert log_call.args[-1] == "-1"

    def test_limit_default_when_missing(self):
        # No limit key → `or 10` default applies
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),
                        _cp(stdout="mb\n"),
                        _cp(stdout=""),
                    ],
                ) as m_git:
                    relay_gitops.git_log({"branch": "feat/x"})
        log_call = m_git.call_args_list[2]
        assert log_call.args[-1] == "-10"

    def test_no_origin_merge_base_falls_back_to_local(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops,
                    "_git",
                    side_effect=[
                        _cp(),
                        _cp(stdout=""),  # origin merge-base empty
                        _cp(stdout="mb\n"),  # local merge-base
                        _cp(stdout=""),  # log
                    ],
                ):
                    result = relay_gitops.git_log({"branch": "feat/x"})
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# git_cancel
# ---------------------------------------------------------------------------


class TestGitCancel:
    def test_returns_ok(self):
        result = relay_gitops.git_cancel({})
        assert result["ok"] is True
        assert "已请求取消" in result["reply"]


# ---------------------------------------------------------------------------
# git_discard
# ---------------------------------------------------------------------------


class TestGitDiscard:
    def test_missing_branch_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            result = relay_gitops.git_discard({})
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_discard_success(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(
                relay_gitops,
                "_git",
                side_effect=[_cp(returncode=0), _cp(returncode=0)],
            ):
                result = relay_gitops.git_discard({"branch": "feat/x"})
        assert result["ok"] is True
        assert "已丢弃分支" in result["reply"]

    def test_discard_remote_ref_already_gone_succeeds(self):
        """push --delete fails but stderr mentions 'remote ref does not exist' → ok."""
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(
                relay_gitops,
                "_git",
                side_effect=[
                    _cp(returncode=1, stderr="error: remote ref does not exist"),
                    _cp(returncode=0),
                ],
            ):
                result = relay_gitops.git_discard({"branch": "feat/x"})
        assert result["ok"] is True

    def test_discard_remote_ref_already_gone_in_stdout_succeeds(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(
                relay_gitops,
                "_git",
                side_effect=[
                    _cp(returncode=1, stdout="remote ref does not exist"),
                    _cp(returncode=0),
                ],
            ):
                result = relay_gitops.git_discard({"branch": "feat/x"})
        assert result["ok"] is True

    def test_discard_push_failure_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(
                relay_gitops,
                "_git",
                side_effect=[
                    _cp(returncode=1, stderr="network error"),
                    _cp(returncode=0),
                ],
            ):
                result = relay_gitops.git_discard({"branch": "feat/x"})
        assert result["ok"] is False
        assert "丢弃失败" in result["reply"]


# ---------------------------------------------------------------------------
# git_merge
# ---------------------------------------------------------------------------


class TestGitMerge:
    def test_missing_branch_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            result = relay_gitops.git_merge({})
        assert result["ok"] is False
        assert "缺少分支名" in result["reply"]

    def test_worktree_add_failure_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(relay_gitops, "_git", return_value=_cp(returncode=0)) as m_git:
                    with patch.object(
                        relay_gitops,
                        "tempfile",
                        MagicMock(gettempdir=lambda: "/tmp"),
                    ):
                        # worktree add fails
                        m_git.side_effect = [
                            _cp(returncode=0),  # fetch origin
                            _cp(returncode=1, stderr="worktree busy"),  # worktree add
                            _cp(returncode=0),  # worktree remove (finally)
                        ]
                        result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is False
        assert "准备合并环境失败" in result["reply"]

    def test_merge_conflict_aborts_and_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops, "tempfile", MagicMock(gettempdir=lambda: "/tmp")
                ):
                    with patch.object(
                        relay_gitops,
                        "_git",
                        side_effect=[
                            _cp(returncode=0),  # fetch origin
                            _cp(returncode=0),  # worktree add ok
                            _cp(returncode=1, stdout="conflict"),  # merge fails
                            _cp(returncode=0),  # merge --abort
                            _cp(returncode=0),  # worktree remove (finally)
                        ],
                    ):
                        result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is False
        assert "合并有冲突" in result["reply"]

    def test_verify_failure_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops, "tempfile", MagicMock(gettempdir=lambda: "/tmp")
                ):
                    with patch.object(
                        relay_gitops,
                        "_git",
                        side_effect=[
                            _cp(returncode=0),  # fetch origin
                            _cp(returncode=0),  # worktree add ok
                            _cp(returncode=0),  # merge ok
                            _cp(returncode=0),  # worktree remove (finally)
                        ],
                    ):
                        with patch.object(
                            relay_gitops, "_verify_merged", return_value=(False, "syntax bad")
                        ):
                            result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is False
        assert "合并后验证未通过" in result["reply"]

    def test_push_failure_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops, "tempfile", MagicMock(gettempdir=lambda: "/tmp")
                ):
                    with patch.object(
                        relay_gitops,
                        "_git",
                        side_effect=[
                            _cp(returncode=0),  # fetch origin
                            _cp(returncode=0),  # worktree add ok
                            _cp(returncode=0),  # merge ok
                            _cp(returncode=1, stderr="push rejected"),  # push fails
                            _cp(returncode=0),  # worktree remove (finally)
                        ],
                    ):
                        with patch.object(
                            relay_gitops, "_verify_merged", return_value=(True, "ok")
                        ):
                            result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is False
        assert "验证通过但推送" in result["reply"]

    def test_merge_success(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops, "tempfile", MagicMock(gettempdir=lambda: "/tmp")
                ):
                    with patch.object(
                        relay_gitops,
                        "_git",
                        side_effect=[
                            _cp(returncode=0),  # fetch origin
                            _cp(returncode=0),  # worktree add ok
                            _cp(returncode=0),  # merge ok
                            _cp(returncode=0),  # push ok
                            _cp(returncode=0),  # worktree remove (finally)
                        ],
                    ):
                        with patch.object(
                            relay_gitops,
                            "_verify_merged",
                            return_value=(True, "已对 2 个 .py 通过语法编译"),
                        ):
                            result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is True
        assert "已合并" in result["reply"]

    def test_merge_exception_returns_failed(self):
        with patch.object(relay_gitops, "_repo_root_from_payload", return_value="/repo"):
            with patch.object(relay_gitops, "_merge_base_branch", return_value="main"):
                with patch.object(
                    relay_gitops, "tempfile", MagicMock(gettempdir=lambda: "/tmp")
                ):
                    with patch.object(
                        relay_gitops,
                        "_git",
                        side_effect=[
                            _cp(returncode=0),  # fetch origin
                            RuntimeError("unexpected"),  # worktree add raises
                            _cp(returncode=0),  # worktree remove (finally)
                        ],
                    ):
                        result = relay_gitops.git_merge({"branch": "feat/x"})
        assert result["ok"] is False
        assert "合并异常" in result["reply"]


# ---------------------------------------------------------------------------
# handle_git_op
# ---------------------------------------------------------------------------


class TestHandleGitOp:
    def test_dispatches_to_git_diff(self):
        with patch.object(relay_gitops, "git_diff", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.diff", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_dispatches_to_git_diff_structured(self):
        with patch.object(relay_gitops, "git_diff_structured", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.diff.structured", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_dispatches_to_git_log(self):
        with patch.object(relay_gitops, "git_log", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.log", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_dispatches_to_git_cancel(self):
        with patch.object(relay_gitops, "git_cancel", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.cancel", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_dispatches_to_git_discard(self):
        with patch.object(relay_gitops, "git_discard", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.discard", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_dispatches_to_git_merge(self):
        with patch.object(relay_gitops, "git_merge", return_value={"ok": True}) as m:
            result = relay_gitops.handle_git_op("git.merge", {"branch": "x"})
        m.assert_called_once_with({"branch": "x"})
        assert result == {"ok": True}

    def test_unknown_kind_returns_failed(self):
        result = relay_gitops.handle_git_op("git.unknown", {"branch": "x"})
        assert result["ok"] is False
        assert "未知 git 操作" in result["reply"]
        assert result["_relay_status"] == "failed"

    def test_git_op_kinds_constant_complete(self):
        assert relay_gitops.GIT_OP_KINDS == (
            "git.merge",
            "git.diff",
            "git.diff.structured",
            "git.discard",
            "git.log",
            "git.cancel",
        )


# ---------------------------------------------------------------------------
# _git (smoke test of the real wrapper)
# ---------------------------------------------------------------------------


class TestGitWrapper:
    def test_git_invokes_subprocess_run(self):
        fake_cp = _cp(returncode=0, stdout="ok")
        with patch.object(relay_gitops.subprocess, "run", return_value=fake_cp) as m_run:
            cp = relay_gitops._git("/repo", "status", timeout=10)
        assert cp.returncode == 0
        m_run.assert_called_once()
        args, kwargs = m_run.call_args
        assert args[0] == ["git", "-C", "/repo", "status"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 10

    def test_git_default_timeout(self):
        with patch.object(relay_gitops.subprocess, "run", return_value=_cp()) as m_run:
            relay_gitops._git("/repo", "status")
        assert m_run.call_args.kwargs["timeout"] == 120.0
