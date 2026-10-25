"""Persist tool sessions and resume conversation turns through explicit CLI and git ports."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .output import CliOutput
from .protocols import ConversationPorts
from .profiles import SuperEmployeeToolProfile

logger = logging.getLogger(__name__)


class ConversationSessions:
    def __init__(self, profile: SuperEmployeeToolProfile, ports: ConversationPorts) -> None:
        self._p, self._ports = profile, ports
        self._output = CliOutput(profile.tool_name)

    def session_store_path(self) -> Path:
        return self._ports.data_dir() / self._p.storage_subdir / "cli_sessions.json"

    def session_get(self, key: str) -> dict[str, Any]:
        try:
            data = json.loads(self.session_store_path().read_text(encoding="utf-8"))
            rec = data.get(key) if isinstance(data, dict) else None
            return rec if isinstance(rec, dict) else {}
        except RECOVERABLE_ERRORS:
            return {}

    def session_set(self, key: str, value: dict[str, Any]) -> None:
        p = self.session_store_path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            if not isinstance(data, dict):
                data = {}
        except RECOVERABLE_ERRORS:
            data = {}
        data[key] = value
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except RECOVERABLE_ERRORS:
            logger.warning("写 session store 失败", exc_info=True)

    def session_key(self, context: dict[str, Any]) -> str:
        """会话键：手机端是单一 pinned 会话，按工具名即可隔离 claude/codex 各自一条续接会话。"""
        conv = str((context or {}).get("conversation_id") or "").strip()
        return f"{self._p.tool_name}:{conv}" if conv else self._p.tool_name

    def ensure_session_workspace(self, key: str) -> tuple[str | None, str | None]:
        """持久隔离工作区：同一会话复用一个 git worktree（不碰 live checkout、不破坏运行中的 FHD）。"""
        rec = self._ports.get_session(key)
        wt = str(rec.get("workspace") or "")
        branch = str(rec.get("branch") or "")
        if wt and Path(wt).exists():
            return (wt, branch)
        base = self._ports.workspace({})
        if not self._ports.is_git_repo(base):
            return (None, None)
        slug = re.sub("[^a-z0-9]+", "-", key.lower()).strip("-") or "session"
        if not branch:
            branch = f"super-employee/{self._p.tool_name}/{slug}"
        wt = str(self._ports.data_dir() / self._p.storage_subdir / f"ws-{slug}")
        try:
            self._ports.git(base, "worktree", "remove", "--force", wt, timeout=30)
        except RECOVERABLE_ERRORS:
            pass
        has_branch = (
            self._ports.git(base, "rev-parse", "--verify", "--quiet", branch, timeout=15).returncode
            == 0
        )
        if has_branch:
            r = self._ports.git(base, "worktree", "add", "--force", wt, branch, timeout=180)
        else:
            r = self._ports.git(base, "worktree", "add", "-b", branch, wt, "HEAD", timeout=180)
        if r.returncode != 0:
            logger.warning("会话工作区创建失败: %s", (r.stderr or r.stdout)[:200])
            return (None, None)
        rec["workspace"] = wt
        rec["branch"] = branch
        self._ports.set_session(key, rec)
        return (wt, branch)

    def conversation_prompt(self, text: str, cwd: str, resuming: bool) -> str:
        if resuming:
            return text.strip()
        return f"你是 XCMAX 内的{self._p.employee_name}，像 Claude Code 一样在项目工作区里工作：可以读取/创建/修改文件、运行命令、用 git；用户让你改代码就直接动手，不要只解释。但普通对话直接回应即可、不要主动遍历整个项目（需要改代码时再读相关文件）；保持上下文连续，像和同事聊天那样自然。\n\n工作区：{cwd}\n\n用户：{text.strip()}"

    def conversation_perm(self) -> str:
        return (
            os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
        ).strip() or "acceptEdits"

    def conversation_cmd(
        self, cli_path: str, prompt: str, resume_session_id: str | None
    ) -> list[str]:
        cmd = [
            cli_path,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            self.conversation_perm(),
        ]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        cmd.append(prompt)
        return self._ports.apply_scope(cmd)

    def run_conversation_turn(self, cli_path: str, text: str, context: dict[str, Any]) -> str:
        key = self.session_key(context)
        cwd = self._ports.workspace(context)
        rec = self._ports.get_session(key)
        session_id = str(rec.get("session_id") or "").strip()
        idle_timeout = self._ports.idle_timeout()
        hard_cap = self._ports.hard_cap()

        def _run(prompt: str, resume: str | None) -> tuple[int, str, str, str]:
            cmd = self.conversation_cmd(cli_path, prompt, resume)
            return self._ports.run_idle(cmd, cwd, idle_timeout, hard_cap)

        try:
            returncode, stdout, stderr, killed = _run(
                self.conversation_prompt(text, cwd, bool(session_id)), session_id or None
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
        body, new_sid = self._output.parse_stream_json_full(stdout)
        if session_id and (not body) and (not killed):
            low = (stderr + stdout).lower()
            if "no conversation" in low or "session" in low or returncode != 0:
                rec["session_id"] = ""
                self._ports.set_session(key, rec)
                try:
                    returncode, stdout, stderr, killed = _run(
                        self.conversation_prompt(text, cwd, False), None
                    )
                    body, new_sid = self._output.parse_stream_json_full(stdout)
                except (OSError, subprocess.SubprocessError):
                    pass
        if killed.startswith("idle"):
            return f"{self._p.display_tool} 静默 {idle_timeout:g} 秒判定卡住已结束，请重试。"
        if killed.startswith("hardcap"):
            return f"{self._p.display_tool} 运行超过上限 {hard_cap:g} 秒已停止，请把任务拆小。"
        if new_sid and new_sid != session_id:
            rec["session_id"] = new_sid
            self._ports.set_session(key, rec)
        if body:
            return body
        if returncode != 0:
            return f"{self._p.display_tool} 本次返回失败（code {returncode}）：{(stderr.strip() or stdout.strip())[:400]}"
        return ""
