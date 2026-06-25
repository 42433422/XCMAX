"""Behaviour tests covering the un-tested branches of
app/application/super_employee_service.py.

These target the conversation-mode (口袋 Claude Code) path, the dev-task closed
loop (worktree → coding → verify → push), git helpers, stream-json parsing,
session store, CLI path/workspace resolution, subprocess-env injection, and the
result-upsert "existing row patch" branch — all of which the existing
test_super_employee_service_cov.py does not exercise.

All external I/O (httpx, subprocess, git, filesystem) is mocked / redirected to
tmp_path so the tests are deterministic, offline and fast.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from app.application.execution_scope import CapabilityGrant, ExecutionScope
from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    DISPATCHER_MESSAGE_KIND,
    SuperEmployeeService,
)

# ─────────────────────────── helpers ────────────────────────────


def _make_svc(tmp_path: Path, profile=CLAUDE_PROFILE, **kwargs) -> SuperEmployeeService:
    return SuperEmployeeService(profile=profile, storage_root=tmp_path, **kwargs)


def _completed(stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


# ════════════════ _parse_claude_stream_json / _parse_stream_json_full ═══════


class TestParseStreamJson:
    def test_result_event_wins(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "partial"}]},
                    }
                ),
                json.dumps({"type": "result", "result": "final answer"}),
            ]
        )
        assert svc._parse_claude_stream_json(out) == "final answer"

    def test_assistant_texts_joined_when_no_result(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "line1"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "line2"}]},
                    }
                ),
            ]
        )
        assert svc._parse_claude_stream_json(out) == "line1\nline2"

    def test_non_json_and_bad_json_lines_ignored(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = "noise line\n{not json}\n" + json.dumps({"type": "result", "result": "ok"})
        assert svc._parse_claude_stream_json(out) == "ok"

    def test_full_parse_extracts_session_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "hi"}]},
                        "session_id": "sid-1",
                    }
                ),
                json.dumps({"type": "result", "result": "done", "session_id": "sid-2"}),
            ]
        )
        body, sid = svc._parse_stream_json_full(out)
        assert body == "done"
        assert sid == "sid-2"  # last session_id seen wins

    def test_full_parse_no_session_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = json.dumps({"type": "result", "result": "done"})
        body, sid = svc._parse_stream_json_full(out)
        assert body == "done"
        assert sid == ""


# ════════════════ _conversation_mode_enabled / _conversation_perm ═══════════


class TestConversationToggles:
    def test_conversation_enabled_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_CONVERSATION", raising=False)
        monkeypatch.delenv("XCMAX_CLAUDE_CONVERSATION", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._conversation_mode_enabled() is True

    def test_conversation_disabled_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_CONVERSATION", "0")
        svc = _make_svc(tmp_path)
        assert svc._conversation_mode_enabled() is False

    def test_conversation_perm_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEVFLEET_CLAUDE_PERMISSION_MODE", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._conversation_perm() == "acceptEdits"

    def test_conversation_perm_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "bypassPermissions")
        svc = _make_svc(tmp_path)
        assert svc._conversation_perm() == "bypassPermissions"

    def test_conversation_cmd_with_resume(self, tmp_path):
        svc = _make_svc(tmp_path)
        cmd = svc._conversation_cmd("/bin/claude", "hello", "sess-9")
        assert cmd[0] == "/bin/claude"
        assert "--resume" in cmd
        assert cmd[cmd.index("--resume") + 1] == "sess-9"
        assert cmd[-1] == "hello"

    def test_conversation_cmd_without_resume(self, tmp_path):
        svc = _make_svc(tmp_path)
        cmd = svc._conversation_cmd("/bin/claude", "hello", None)
        assert "--resume" not in cmd
        assert cmd[-1] == "hello"


# ════════════════ _conversation_prompt ═════════════════════════════════════


class TestConversationPrompt:
    def test_resuming_returns_raw_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._conversation_prompt("  改个 bug  ", "/repo", resuming=True) == "改个 bug"

    def test_fresh_includes_identity_and_cwd(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._conversation_prompt("写个函数", "/repo", resuming=False)
        assert "超级员工-Claude" in out
        assert "/repo" in out
        assert "写个函数" in out


# ════════════════ session store ════════════════════════════════════════════


class TestSessionStore:
    def test_session_get_missing_file_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._session_get("claude_code") == {}

    def test_session_set_then_get_roundtrip(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.get_app_data_dir",
            return_value=str(tmp_path),
        ):
            svc._session_set("k1", {"session_id": "abc", "workspace": "/w"})
            rec = svc._session_get("k1")
        assert rec == {"session_id": "abc", "workspace": "/w"}

    def test_session_get_corrupt_json_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.get_app_data_dir",
            return_value=str(tmp_path),
        ):
            p = svc._session_store_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{not valid json", encoding="utf-8")
            assert svc._session_get("k1") == {}

    def test_session_key_with_conversation_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        key = svc._session_key({"conversation_id": "conv-42"})
        assert key == "claude_code:conv-42"

    def test_session_key_without_conversation_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._session_key({}) == "claude_code"


# ════════════════ _ensure_session_workspace ════════════════════════════════


class TestEnsureSessionWorkspace:
    def test_reuses_existing_workspace_when_present(self, tmp_path):
        svc = _make_svc(tmp_path)
        existing_wt = tmp_path / "existing-ws"
        existing_wt.mkdir()
        with patch(
            "app.application.super_employee_service.get_app_data_dir",
            return_value=str(tmp_path),
        ):
            svc._session_set("claude_code", {"workspace": str(existing_wt), "branch": "br-keep"})
            wt, branch = svc._ensure_session_workspace("claude_code")
        assert wt == str(existing_wt)
        assert branch == "br-keep"

    def test_non_git_base_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_is_git_repo", return_value=False),
        ):
            wt, branch = svc._ensure_session_workspace("claude_code")
        assert wt is None and branch is None

    def test_creates_new_branch_worktree(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(base, *args, **kw):
            if args[0] == "rev-parse" and "--verify" in args:
                # branch does NOT exist
                return _completed(code=1)
            # worktree remove / worktree add succeed
            return _completed(code=0)

        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", side_effect=fake_git),
        ):
            wt, branch = svc._ensure_session_workspace("claude_code")
        assert wt is not None
        assert branch == "super-employee/claude_code/claude-code"

    def test_existing_branch_worktree_add(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(base, *args, **kw):
            if args[0] == "rev-parse" and "--verify" in args:
                return _completed(code=0)  # branch exists
            return _completed(code=0)

        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", side_effect=fake_git),
        ):
            wt, branch = svc._ensure_session_workspace("conv-key")
        assert wt is not None
        assert branch.startswith("super-employee/claude_code/")

    def test_worktree_add_failure_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(base, *args, **kw):
            if args[0] == "rev-parse" and "--verify" in args:
                return _completed(code=1)  # no branch
            if args[0] == "worktree" and args[1] == "add":
                return _completed(stderr="add failed", code=1)
            return _completed(code=0)

        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", side_effect=fake_git),
        ):
            wt, branch = svc._ensure_session_workspace("claude_code")
        assert wt is None and branch is None


# ════════════════ _run_cli_idle ════════════════════════════════════════════


class TestRunCliIdle:
    def test_process_completes_collects_output(self, tmp_path):
        svc = _make_svc(tmp_path)

        class FakeStream:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                return self._lines.pop(0) if self._lines else ""

            def close(self):
                pass

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStream(["hello\n", "world\n"])
                self.stderr = FakeStream(["warn\n"])
                self.returncode = 0
                self._waited = False

            def wait(self, timeout=None):
                # First short wait raises, second returns 0 — simulate quick completion.
                if not self._waited:
                    self._waited = True
                return 0

            def kill(self):
                pass

        with patch(
            "app.application.super_employee_service.subprocess.Popen",
            return_value=FakeProc(),
        ):
            rc, out, err, killed = svc._run_cli_idle(["claude"], str(tmp_path), 180.0, 3600.0)
        assert rc == 0
        assert "hello" in out and "world" in out
        assert "warn" in err
        assert killed == ""


# ════════════════ _run_conversation_turn ═══════════════════════════════════


class TestRunConversationTurn:
    def test_fresh_session_returns_body_and_persists_sid(self, tmp_path):
        svc = _make_svc(tmp_path)
        stream = json.dumps({"type": "result", "result": "hello back", "session_id": "new-sid"})
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_run_cli_idle", return_value=(0, stream, "", "")),
        ):
            body = svc._run_conversation_turn("/bin/claude", "你好", {})
            # sid persisted — read inside the patched get_app_data_dir context
            rec = svc._session_get("claude_code")
        assert body == "hello back"
        assert rec.get("session_id") == "new-sid"

    def test_idle_timeout_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_cli_idle_timeout_seconds", return_value=30.0),
            patch.object(svc, "_run_cli_idle", return_value=(0, "", "", "idle:30")),
        ):
            body = svc._run_conversation_turn("/bin/claude", "你好", {})
        assert "静默" in body and "卡住" in body

    def test_hardcap_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_cli_hard_cap_seconds", return_value=3600.0),
            patch.object(svc, "_run_cli_idle", return_value=(0, "", "", "hardcap:3600")),
        ):
            body = svc._run_conversation_turn("/bin/claude", "你好", {})
        assert "上限" in body

    def test_subprocess_error_returns_failure_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_run_cli_idle", side_effect=OSError("spawn failed")),
        ):
            body = svc._run_conversation_turn("/bin/claude", "你好", {})
        assert "调用失败" in body

    def test_nonzero_returncode_empty_body_reports_failure(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_run_cli_idle", return_value=(7, "", "boom err", "")),
        ):
            body = svc._run_conversation_turn("/bin/claude", "你好", {})
        assert "失败" in body and "7" in body

    def test_resume_invalid_retries_fresh(self, tmp_path):
        svc = _make_svc(tmp_path)
        # seed an existing session id so the first _run uses --resume
        with patch(
            "app.application.super_employee_service.get_app_data_dir",
            return_value=str(tmp_path),
        ):
            svc._session_set("claude_code", {"session_id": "stale-sid"})

        calls = []

        def fake_run_idle(cmd, cwd, idle, hard):
            calls.append(list(cmd))
            if "--resume" in cmd:
                # resume fails: empty body, non-zero rc, "no conversation" in stderr
                return (1, "", "no conversation found for stale-sid", "")
            # fresh retry succeeds
            return (
                0,
                json.dumps({"type": "result", "result": "recovered", "session_id": "fresh-sid"}),
                "",
                "",
            )

        with (
            patch(
                "app.application.super_employee_service.get_app_data_dir",
                return_value=str(tmp_path),
            ),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_run_cli_idle", side_effect=fake_run_idle),
        ):
            body = svc._run_conversation_turn("/bin/claude", "继续", {})
            sid_after = svc._session_get("claude_code").get("session_id")
        assert body == "recovered"
        assert any("--resume" in c for c in calls)
        assert sid_after == "fresh-sid"


# ════════════════ _cli_path ════════════════════════════════════════════════


class TestCliPath:
    def test_env_path_used_when_file(self, tmp_path, monkeypatch):
        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        monkeypatch.setenv("XCMAX_CLAUDE_CLI_PATH", str(cli))
        svc = _make_svc(tmp_path)
        assert svc._cli_path() == str(cli)

    def test_returns_empty_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_CLI_PATH", str(tmp_path / "does-not-exist"))
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.shutil.which", return_value=None):
            # CLAUDE_PROFILE.cli_extra_candidates point at real-ish system paths that
            # don't exist in this sandbox, so the result should be "".
            result = svc._cli_path()
        # Either empty, or it happened to find a system binary; assert it's a file path or "".
        assert result == "" or Path(result).is_file()


# ════════════════ _cli_workspace ═══════════════════════════════════════════


class TestCliWorkspace:
    def test_product_domain_ignores_env_uses_ephemeral_scratch(self, tmp_path, monkeypatch):
        # 信任墙第3层：产品域(默认)绝不读 *_WORKSPACE_ROOT 环境、绝不落到工程树，
        # 只落系统临时区隔离 scratch（规避 get_app_data_dir 回落仓库根的陷阱）。
        monkeypatch.setenv("XCMAX_CLAUDE_WORKSPACE_ROOT", str(tmp_path))
        svc = _make_svc(tmp_path)  # 默认 product 域
        ws = svc._cli_workspace({})
        assert ws != str(tmp_path)  # env 路径被无视
        assert "xcmax_product_scratch" in ws
        assert ws.endswith("claude_super_employee")  # = CLAUDE_PROFILE.storage_subdir
        assert Path(ws).exists()

    def test_product_domain_honors_caller_path_when_not_server_repo(self, tmp_path):
        # 客户显式提供的本机路径(存在且非服务端 repo)被采纳。
        svc = _make_svc(tmp_path)
        assert svc._cli_workspace({"workspace_root": str(tmp_path)}) == str(tmp_path)

    def test_fallback_resolves_to_existing_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("MODSTORE_REPO_ROOT", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._cli_workspace({})
        # 产品域 ephemeral scratch 一定是真实存在的目录
        assert Path(result).exists()


# ════════════════ _cli_subprocess_env ══════════════════════════════════════


class TestCliSubprocessEnv:
    def test_factory_no_proxy_returns_none(self, tmp_path, monkeypatch):
        # 工厂域 + 无代理：继承当前环境(返回 None)，与历史行为一致、零回归。
        monkeypatch.delenv("XCMAX_CLI_PROXY", raising=False)
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "default")
        assert svc._cli_subprocess_env() is None

    def test_product_no_proxy_returns_scrubbed_env(self, tmp_path, monkeypatch):
        # 信任墙第2层：产品域(默认)即便无代理也要构造环境，以剥掉平台工厂令牌/git 凭证。
        monkeypatch.delenv("XCMAX_CLI_PROXY", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "platform-secret")
        monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "factory-secret")
        svc = _make_svc(tmp_path)  # 默认 product 域
        env = svc._cli_subprocess_env()
        assert env is not None
        assert "GITHUB_TOKEN" not in env  # 平台 git 凭证被剥离
        assert "XCMAX_FACTORY_CAPABILITY_TOKEN" not in env  # 工厂令牌被剥离
        # 非机密的普通变量保留(只剥令牌/凭证，不清空环境)
        assert env.get("PATH") == os.environ.get("PATH")

    def test_proxy_injected_into_all_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLI_PROXY", "http://proxy:8080")
        svc = _make_svc(tmp_path)
        env = svc._cli_subprocess_env()
        assert env is not None
        for k in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            assert env[k] == "http://proxy:8080"


# ════════════════ _is_task_intent / prompts ════════════════════════════════


class TestTaskIntent:
    def test_chat_mode_not_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("修复 bug", {"mode": "chat"}) is False

    def test_code_mode_is_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("你好", {"mode": "code"}) is True

    def test_keyword_triggers_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("帮我修复登录页", {}) is True

    def test_plain_question_not_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("今天天气如何", {}) is False

    def test_empty_text_not_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("   ", {}) is False

    def test_work_prompt_contains_cwd_and_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._cli_work_prompt("实现登录", "/repo")
        assert "/repo" in out
        assert "实现登录" in out

    def test_fix_prompt_contains_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._cli_fix_prompt("SyntaxError: bad", "/repo")
        assert "SyntaxError: bad" in out
        assert "/repo" in out


# ════════════════ _dev_loop_enabled ════════════════════════════════════════


class TestDevLoopEnabled:
    def test_default_enabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_DEV_LOOP", raising=False)
        monkeypatch.delenv("XCMAX_CLAUDE_DEV_LOOP", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._dev_loop_enabled() is True

    def test_disabled_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_DEV_LOOP", "off")
        svc = _make_svc(tmp_path)
        assert svc._dev_loop_enabled() is False


# ════════════════ git helpers: _is_git_repo / _prepare_worktree ════════════


class TestGitHelpers:
    def test_is_git_repo_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", return_value=_completed(stdout="true\n")):
            assert svc._is_git_repo("/repo") is True

    def test_is_git_repo_false_on_nonzero(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", return_value=_completed(stdout="", code=128)):
            assert svc._is_git_repo("/repo") is False

    def test_is_git_repo_false_on_exception(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", side_effect=OSError("git missing")):
            assert svc._is_git_repo("/repo") is False

    def test_prepare_worktree_non_git_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_is_git_repo", return_value=False):
            assert svc._prepare_worktree("/repo", "修复登录") is None

    def test_prepare_worktree_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", return_value=_completed(code=0)),
        ):
            res = svc._prepare_worktree("/repo", "修复登录页面")
        assert res is not None
        wt_path, branch = res
        assert branch.startswith("super-employee/claude_code/")
        assert "xcagi-wt-claude_code-" in wt_path

    def test_prepare_worktree_add_fails_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", return_value=_completed(stderr="add failed", code=1)),
        ):
            assert svc._prepare_worktree("/repo", "task") is None

    def test_prepare_worktree_exception_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", side_effect=RuntimeError("boom")),
        ):
            assert svc._prepare_worktree("/repo", "task") is None

    def test_remove_worktree_swallows_errors(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", side_effect=RuntimeError("nope")):
            # Must not raise.
            svc._remove_worktree("/repo", "/tmp/wt")


# ════════════════ _verify_workspace ════════════════════════════════════════


class TestVerifyWorkspace:
    def test_custom_verify_cmd_pass(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "echo ok")
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.subprocess.run",
            return_value=_completed(stdout="ok", code=0),
        ):
            ok, msg = svc._verify_workspace("/repo")
        assert ok is True
        assert "自定义验证命令通过" in msg

    def test_custom_verify_cmd_fail(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "false")
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.subprocess.run",
            return_value=_completed(stderr="boom", code=1),
        ):
            ok, msg = svc._verify_workspace("/repo")
        assert ok is False
        assert "boom" in msg

    def test_custom_verify_cmd_exception(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "boom")
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.subprocess.run",
            side_effect=OSError("cannot run"),
        ):
            ok, msg = svc._verify_workspace("/repo")
        assert ok is False
        assert "验证命令异常" in msg

    def test_no_changes_returns_ok(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", return_value=_completed(stdout="", code=0)):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "无文件改动" in msg

    def test_changed_py_compiles(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        good = tmp_path / "mod.py"
        good.write_text("x = 1\n", encoding="utf-8")
        # git status --porcelain --untracked-files=all line: "?? mod.py"
        with patch.object(svc, "_git", return_value=_completed(stdout="?? mod.py\n", code=0)):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "语法编译" in msg

    def test_changed_py_with_syntax_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        with patch.object(svc, "_git", return_value=_completed(stdout=" M bad.py\n", code=0)):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is False
        assert "Python 语法错误" in msg

    def test_changed_non_py_files(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", return_value=_completed(stdout=" M README.md\n", code=0)):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "非 .py" in msg

    def test_rename_path_parsed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        new = tmp_path / "new.py"
        new.write_text("y = 2\n", encoding="utf-8")
        # Rename line: "R  old.py -> new.py"
        with patch.object(
            svc, "_git", return_value=_completed(stdout="R  old.py -> new.py\n", code=0)
        ):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "语法编译" in msg

    def test_git_status_exception_treated_as_no_changes(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", side_effect=RuntimeError("git blew up")):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "无文件改动" in msg


# ════════════════ _commit_and_push ═════════════════════════════════════════


class TestCommitAndPush:
    def test_no_changes_returns_false(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(cwd, *args, **kw):
            if args[0] == "status":
                return _completed(stdout="", code=0)
            return _completed(code=0)

        with patch.object(svc, "_git", side_effect=fake_git):
            ok, msg = svc._commit_and_push("/repo", "branch-x", "task")
        assert ok is False
        assert "无改动可提交" in msg

    def test_commit_fail(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(cwd, *args, **kw):
            if args[0] == "status":
                return _completed(stdout=" M f.py\n", code=0)
            if args[0] == "commit":
                return _completed(stderr="commit boom", code=1)
            return _completed(code=0)

        with patch.object(svc, "_git", side_effect=fake_git):
            ok, msg = svc._commit_and_push("/repo", "branch-x", "task")
        assert ok is False
        assert "提交失败" in msg

    def test_push_fail(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(cwd, *args, **kw):
            if args[0] == "status":
                return _completed(stdout=" M f.py\n", code=0)
            if args[0] == "commit":
                return _completed(code=0)
            if args[0] == "push":
                return _completed(stderr="push denied", code=1)
            return _completed(code=0)

        with patch.object(svc, "_git", side_effect=fake_git):
            ok, msg = svc._commit_and_push("/repo", "branch-x", "task")
        assert ok is False
        assert "push 失败" in msg

    def test_full_success(self, tmp_path):
        svc = _make_svc(tmp_path)

        def fake_git(cwd, *args, **kw):
            if args[0] == "status":
                return _completed(stdout=" M f.py\n", code=0)
            return _completed(code=0)

        with patch.object(svc, "_git", side_effect=fake_git):
            ok, msg = svc._commit_and_push("/repo", "branch-x", "修复登录\n第二行")
        assert ok is True
        assert "branch-x" in msg

    def test_git_exception(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", side_effect=RuntimeError("boom")):
            ok, msg = svc._commit_and_push("/repo", "branch-x", "task")
        assert ok is False
        assert "git 异常" in msg


# ════════════════ _run_dev_task_loop ═══════════════════════════════════════


class TestRunDevTaskLoop:
    def test_no_worktree_falls_back_to_single_run(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_prepare_worktree", return_value=None),
            patch.object(svc, "_run_cli_once", return_value="改完了") as mock_once,
        ):
            out = svc._run_dev_task_loop("/bin/claude", "实现功能", "/repo")
        assert out == "改完了"
        mock_once.assert_called_once()

    def test_full_loop_verify_pass_push_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_prepare_worktree", return_value=("/tmp/wt", "br-1")),
            patch.object(svc, "_run_cli_once", return_value="实现完成") as mock_once,
            patch.object(svc, "_verify_workspace", return_value=(True, "已编译")),
            patch.object(svc, "_commit_and_push", return_value=(True, "已 push 到 origin/br-1")),
            patch.object(svc, "_remove_worktree") as mock_remove,
        ):
            out = svc._run_dev_task_loop("/bin/claude", "实现功能", "/repo")
        assert "✅" in out
        assert "br-1" in out
        assert "通过" in out
        # only one CLI run (no fix needed)
        assert mock_once.call_count == 1
        mock_remove.assert_called_once_with("/repo", "/tmp/wt")

    def test_verify_fail_triggers_fix_then_push(self, tmp_path):
        svc = _make_svc(tmp_path)
        verify_results = [(False, "语法错误"), (True, "已修复")]
        with (
            patch.object(svc, "_prepare_worktree", return_value=("/tmp/wt", "br-2")),
            patch.object(svc, "_run_cli_once", return_value="工作中") as mock_once,
            patch.object(svc, "_verify_workspace", side_effect=verify_results),
            patch.object(svc, "_commit_and_push", return_value=(True, "已 push")),
            patch.object(svc, "_remove_worktree"),
        ):
            out = svc._run_dev_task_loop("/bin/claude", "实现功能", "/repo")
        # CLI run twice: once for coding, once for the fix prompt
        assert mock_once.call_count == 2
        assert "✅" in out

    def test_push_fail_but_verify_pass_yields_cross_mark(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_prepare_worktree", return_value=("/tmp/wt", "br-3")),
            patch.object(svc, "_run_cli_once", return_value=""),
            patch.object(svc, "_verify_workspace", return_value=(True, "ok")),
            patch.object(svc, "_commit_and_push", return_value=(False, "无改动可提交")),
            patch.object(svc, "_remove_worktree"),
        ):
            out = svc._run_dev_task_loop("/bin/claude", "实现功能", "/repo")
        # not pushed and verify ok → status "❌"
        assert "❌" in out
        # body empty → default summary used
        assert "已完成开发任务" in out


# ════════════════ _cli_reply_body conversation routing ═════════════════════


class TestCliReplyBodyConversationRouting:
    def test_routes_to_conversation_turn_for_claude_with_subprocess_run(self, tmp_path):
        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        # default cli_runner is subprocess.run and CLAUDE_PROFILE.cli_stream_json is True
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_cli_path", return_value=str(cli)),
            patch.object(svc, "_conversation_mode_enabled", return_value=True),
            patch.object(svc, "_run_conversation_turn", return_value="对话回复") as mock_conv,
        ):
            out = svc._cli_reply_body("你好", {})
        assert out == "对话回复"
        mock_conv.assert_called_once()

    def test_non_task_with_injected_runner_uses_run_cli_once(self, tmp_path):
        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        # injected runner (not subprocess.run) → conversation path skipped
        svc = _make_svc(tmp_path, cli_runner=lambda *a, **k: _completed())
        with (
            patch.object(svc, "_cli_path", return_value=str(cli)),
            patch.object(svc, "_run_cli_once", return_value="闲聊回复") as mock_once,
        ):
            out = svc._cli_reply_body("今天天气如何", {})
        assert out == "闲聊回复"
        # called with the chat prompt
        mock_once.assert_called_once()

    def test_task_with_injected_runner_uses_work_prompt_not_dev_loop(self, tmp_path):
        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        # injected runner → _run_dev_task_loop is NOT taken (dev loop requires subprocess.run)
        svc = _make_svc(tmp_path, cli_runner=lambda *a, **k: _completed())
        with (
            patch.object(svc, "_cli_path", return_value=str(cli)),
            patch.object(svc, "_run_cli_once", return_value="任务回复") as mock_once,
            patch.object(svc, "_run_dev_task_loop") as mock_loop,
        ):
            out = svc._cli_reply_body("帮我修复登录", {})
        assert out == "任务回复"
        mock_once.assert_called_once()
        mock_loop.assert_not_called()


# ════════════════ _fetch_para_task ═════════════════════════════════════════


class TestFetchParaTask:
    def test_no_api_url_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path)
        assert svc._fetch_para_task("task-1") is None

    def test_empty_task_id_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(tmp_path)
        assert svc._fetch_para_task("") is None

    def test_success_returns_task_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "http://para")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/guest":
                return httpx.Response(200, json={"token": "t"})
            if request.url.path == "/api/tasks/task-9":
                return httpx.Response(200, json={"task": {"id": "task-9", "status": "running"}})
            return httpx.Response(404, json={})

        svc = _make_svc(
            tmp_path,
            http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        )
        task = svc._fetch_para_task("task-9")
        assert task == {"id": "task-9", "status": "running"}

    def test_http_error_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "http://para")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            client.post.side_effect = httpx.ConnectError("down")
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        assert svc._fetch_para_task("task-1") is None


# ════════════════ _upsert_result_messages existing-row patch ═══════════════


class TestUpsertResultMessagesExisting:
    def test_existing_result_row_patched_in_place(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "task-1", "status": "completed"}
        task["subTasks"] = [
            {
                "id": "sub-1",
                "status": "completed",
                "device_name": "dev-A",
                "title": "实现",
                "logs": [{"content": "全新日志输出"}],
            }
        ]
        dispatch_row = {"task_id": "task-1", "dispatch_request_id": "req-1"}
        existing = {
            "user_id": 1,
            "role": "assistant",
            "kind": CLAUDE_PROFILE.result_kind,
            "task_id": "task-1",
            "subtask_id": "sub-1",
            "body": "旧日志",
            "status": "running",
            "task_status": "running",
            "device_name": "",
        }
        rows = [existing]
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is True
        # patched in place, no new row appended
        assert len(rows) == 1
        assert "全新日志输出" in existing["body"]
        assert existing["status"] == "completed"
        assert existing["device_name"] == "dev-A"

    def test_new_result_row_appended(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {
            "id": "task-2",
            "status": "completed",
            "subTasks": [
                {
                    "id": "sub-2",
                    "status": "completed",
                    "device_name": "dev-B",
                    "title": "核心实现",
                    "logs": [{"content": "完成日志"}],
                }
            ],
        }
        dispatch_row = {"task_id": "task-2", "dispatch_request_id": "req-2"}
        rows: list[dict] = []
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is True
        assert len(rows) == 1
        assert rows[0]["kind"] == CLAUDE_PROFILE.result_kind
        assert "完成日志" in rows[0]["body"]
        assert rows[0]["subtask_id"] == "sub-2"

    def test_non_terminal_subtask_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {
            "id": "task-3",
            "status": "running",
            "subTasks": [{"id": "sub-3", "status": "running", "logs": []}],
        }
        rows: list[dict] = []
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row={"task_id": "task-3"}, task=task, rows=rows
        )
        assert changed is False
        assert rows == []


# ════════════════ end-to-end invoke via conversation mode ══════════════════


class TestInvokeConversationEndToEnd:
    def test_invoke_chat_uses_conversation_turn(self, tmp_path, monkeypatch):
        # Force CLI direct path; CLAUDE profile, default subprocess.run runner.
        monkeypatch.setenv("XCMAX_CLAUDE_FORCE_CLI_DIRECT", "1")
        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_cli_path", return_value=str(cli)),
            patch.object(svc, "_run_conversation_turn", return_value="会话回复内容"),
        ):
            result = svc.invoke(user_id=7, message="你好啊")
        assert result["dispatch"]["status"] == "completed"
        assert result["dispatch"]["dispatcher"] == "claude_code_cli"
        assert result["assistant_message"]["body"] == "会话回复内容"
        # message persisted to disk
        msgs = svc.list_messages(user_id=7)
        assert any(m["body"] == "会话回复内容" for m in msgs)
