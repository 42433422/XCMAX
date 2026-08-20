# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart02MixinPart02Mixin:
    def _upgrade_legacy_dispatcher_row(self, row: dict[str, _facade().Any]) -> bool:
        if str(row.get("kind") or "") == _facade().DISPATCHER_MESSAGE_KIND:
            return False
        if str(row.get("role") or "") != "assistant":
            return False
        body = str(row.get("body") or "")
        if not self._is_dispatcher_ack_body(body):
            return False
        row["role"] = "system"
        row["kind"] = _facade().DISPATCHER_MESSAGE_KIND
        task_id = self._extract_task_id_from_body(body)
        if task_id and (not row.get("task_id")):
            row["task_id"] = task_id
        return True

    def _is_dispatcher_ack_body(self, body: str) -> bool:
        markers = (
            "多设备调度器",
            "调用队列",
            "调度通道",
            f"未发现在线可用 {self._p.display_tool} 设备",
            "任务已派发到",
            f"Para/{self._p.display_tool}",
        )
        return any(marker in body for marker in markers)

    def _extract_task_id_from_body(self, body: str) -> str:
        match = _facade().TASK_ID_RE.search(body)
        return match.group(1).strip() if match else ""

    def _should_reply_with_cli(self, text: str, context: dict[str, _facade().Any]) -> bool:
        force_direct = (
            (
                _facade().os.environ.get(f"{self._p.env_tool_prefix}_FORCE_CLI_DIRECT")
                or _facade().os.environ.get("XCMAX_FORCE_CLI_DIRECT")
                or ""
            )
            .strip()
            .lower()
        )
        if force_direct in {"1", "true", "yes", "on"}:
            return True
        if context.get("force_cli_direct") is True:
            return True
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return True
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return False
        normalized = _facade().re.sub("\\s+", "", text.strip().lower())
        if not normalized:
            return False
        return not any(marker in normalized for marker in _facade()._TASK_MARKERS)

    def _cli_reply_body(self, text: str, context: dict[str, _facade().Any]) -> str:
        if str(
            _facade().os.environ.get(f"{self._p.env_tool_prefix}_CLI_CHAT_ENABLED") or "1"
        ).strip().lower() in {"0", "false", "off", "disabled"}:
            return ""
        cli_path = self._cli_path()
        if not cli_path:
            return ""
        if (
            self._p.cli_stream_json
            and self._cli_runner is _facade().subprocess.run
            and self._conversation_mode_enabled()
            and (not context.get("force_cli_direct"))
        ):
            return self._run_conversation_turn(cli_path, text, context)
        base_cwd = self._cli_workspace(context)
        if not self._is_task_intent(text, context):
            return self._run_cli_once(cli_path, self._cli_prompt(text), base_cwd)
        if self._cli_runner is not _facade().subprocess.run or not self._dev_loop_enabled():
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        return self._run_dev_task_loop(cli_path, text, base_cwd, context)

    def _conversation_mode_enabled(self) -> bool:
        raw = (
            str(
                _facade().os.environ.get(f"{self._p.env_tool_prefix}_CONVERSATION")
                or _facade().os.environ.get("XCMAX_CLAUDE_CONVERSATION")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def _session_store_path(self) -> _facade().Path:
        return (
            _facade().Path(_facade().get_app_data_dir())
            / self._p.storage_subdir
            / "cli_sessions.json"
        )

    def _session_get(self, key: str) -> dict[str, _facade().Any]:
        try:
            data = _facade().json.loads(self._session_store_path().read_text(encoding="utf-8"))
            rec = data.get(key) if isinstance(data, dict) else None
            return rec if isinstance(rec, dict) else {}
        except _facade().RECOVERABLE_ERRORS:
            return {}

    def _session_set(self, key: str, value: dict[str, _facade().Any]) -> None:
        p = self._session_store_path()
        try:
            data = _facade().json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            if not isinstance(data, dict):
                data = {}
        except _facade().RECOVERABLE_ERRORS:
            data = {}
        data[key] = value
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_facade().json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning("写 session store 失败", exc_info=True)

    def _session_key(self, context: dict[str, _facade().Any]) -> str:
        """会话键：手机端是单一 pinned 会话，按工具名即可隔离 claude/codex 各自一条续接会话。"""
        conv = str((context or {}).get("conversation_id") or "").strip()
        return f"{self._p.tool_name}:{conv}" if conv else self._p.tool_name

    def _ensure_session_workspace(self, key: str) -> tuple[str | None, str | None]:
        """持久隔离工作区：同一会话复用一个 git worktree（不碰 live checkout、不破坏运行中的 FHD）。"""
        rec = self._session_get(key)
        wt = str(rec.get("workspace") or "")
        branch = str(rec.get("branch") or "")
        if wt and _facade().Path(wt).exists():
            return (wt, branch)
        base = self._cli_workspace({})
        if not self._is_git_repo(base):
            return (None, None)
        slug = _facade().re.sub("[^a-z0-9]+", "-", key.lower()).strip("-") or "session"
        if not branch:
            branch = f"super-employee/{self._p.tool_name}/{slug}"
        wt = str(
            _facade().Path(_facade().get_app_data_dir()) / self._p.storage_subdir / f"ws-{slug}"
        )
        try:
            self._git(base, "worktree", "remove", "--force", wt, timeout=30)
        except _facade().RECOVERABLE_ERRORS:
            pass
        has_branch = (
            self._git(base, "rev-parse", "--verify", "--quiet", branch, timeout=15).returncode == 0
        )
        if has_branch:
            r = self._git(base, "worktree", "add", "--force", wt, branch, timeout=180)
        else:
            r = self._git(base, "worktree", "add", "-b", branch, wt, "HEAD", timeout=180)
        if r.returncode != 0:
            _facade().logger.warning("会话工作区创建失败: %s", (r.stderr or r.stdout)[:200])
            return (None, None)
        rec["workspace"] = wt
        rec["branch"] = branch
        self._session_set(key, rec)
        return (wt, branch)

    def _conversation_prompt(self, text: str, cwd: str, resuming: bool) -> str:
        if resuming:
            return text.strip()
        return f"你是 XCMAX 内的{self._p.employee_name}，像 Claude Code 一样在项目工作区里工作：可以读取/创建/修改文件、运行命令、用 git；用户让你改代码就直接动手，不要只解释。但普通对话直接回应即可、不要主动遍历整个项目（需要改代码时再读相关文件）；保持上下文连续，像和同事聊天那样自然。\n\n工作区：{cwd}\n\n用户：{text.strip()}"

    def _parse_stream_json_full(self, out: str) -> tuple[str, str]:
        """从 stream-json 取 (最终回复, session_id)。session_id 取最后出现的(result 事件含)。"""
        text = self._parse_claude_stream_json(out)
        sid = ""
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = _facade().json.loads(s)
            except _facade().json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("session_id"):
                sid = str(ev.get("session_id") or "")
        return (text, sid)

    def _conversation_perm(self) -> str:
        return (
            _facade().os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
        ).strip() or "acceptEdits"

    def _apply_scope_to_cmd(self, cmd: list[str]) -> list[str]:
        """信任墙第 4 层（纵深防御）：产品域收紧 claude 的工具面。

        把 ``--permission-mode`` 降到 ``default`` 并显式禁用写/执行类工具，使被注入的产品域
        会话即便被诱导喊 git/shell，那些工具也压根没注册 → 硬失败而非软拒绝。工厂域不动；
        codex 命令构造默认已是 ``--sandbox workspace-write``，此处不改。
        """
        if not cmd:
            return cmd
        if (
            self._grant.is_factory
            or getattr(self, "_relay_cli_trusted", False)
            or self._p.cli_binary != "claude"
        ):
            return cmd
        out: list[str] = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "--permission-mode" and i + 1 < len(cmd):
                out += ["--permission-mode", "default"]
                i += 2
                continue
            out.append(cmd[i])
            i += 1
        if "--disallowedTools" not in out:
            prompt = out.pop()
            out += ["--disallowedTools", "Bash,Edit,Write,MultiEdit,NotebookEdit", prompt]
        return out

    def _conversation_cmd(
        self, cli_path: str, prompt: str, resume_session_id: str | None
    ) -> list[str]:
        cmd = [
            cli_path,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            self._conversation_perm(),
        ]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        cmd.append(prompt)
        return self._apply_scope_to_cmd(cmd)

    def _run_conversation_turn(
        self, cli_path: str, text: str, context: dict[str, _facade().Any]
    ) -> str:
        key = self._session_key(context)
        cwd = self._cli_workspace(context)
        rec = self._session_get(key)
        session_id = str(rec.get("session_id") or "").strip()
        idle_timeout = self._cli_idle_timeout_seconds()
        hard_cap = self._cli_hard_cap_seconds()

        def _run(prompt: str, resume: str | None) -> tuple[int, str, str, str]:
            cmd = self._conversation_cmd(cli_path, prompt, resume)
            return self._run_cli_idle(cmd, cwd, idle_timeout, hard_cap)

        try:
            returncode, stdout, stderr, killed = _run(
                self._conversation_prompt(text, cwd, bool(session_id)), session_id or None
            )
        except (OSError, _facade().subprocess.SubprocessError) as exc:
            return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
        body, new_sid = self._parse_stream_json_full(stdout)
        if session_id and (not body) and (not killed):
            low = (stderr + stdout).lower()
            if "no conversation" in low or "session" in low or returncode != 0:
                rec["session_id"] = ""
                self._session_set(key, rec)
                try:
                    returncode, stdout, stderr, killed = _run(
                        self._conversation_prompt(text, cwd, False), None
                    )
                    body, new_sid = self._parse_stream_json_full(stdout)
                except (OSError, _facade().subprocess.SubprocessError):
                    pass
        if killed.startswith("idle"):
            return f"{self._p.display_tool} 静默 {idle_timeout:g} 秒判定卡住已结束，请重试。"
        if killed.startswith("hardcap"):
            return f"{self._p.display_tool} 运行超过上限 {hard_cap:g} 秒已停止，请把任务拆小。"
        if new_sid and new_sid != session_id:
            rec["session_id"] = new_sid
            self._session_set(key, rec)
        if body:
            return body
        if returncode != 0:
            return f"{self._p.display_tool} 本次返回失败（code {returncode}）：{(stderr.strip() or stdout.strip())[:400]}"
        return ""
