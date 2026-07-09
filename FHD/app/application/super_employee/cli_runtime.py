"""CLI streaming / conversation runtime mixin."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.application.execution_scope import (
    FACTORY_TOKEN_ENV,
)
from app.application.relay_workspace import resolve_verified_relay_workspace_root
from app.application.workspaces import WorkspaceError, get_workspace_registry
from app.utils.path_utils import get_app_data_dir

from .profiles import (  # noqa: F401
    _PARA_TOKEN_CACHE,
    _PARA_TOKEN_TTL,
    _RELAY_WT_LOCKS,
    _RELAY_WT_LOCKS_GUARD,
    _SUBTASK_LABELS,
    _TASK_MARKERS,
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DEFAULT_PARA_API_URL,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    TASK_ID_RE,
    TRAE_PROFILE,
    SuperEmployeeToolProfile,
    _chunk_text,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _facade_attr,
    _relay_wt_lock,
    _safe_json_line,
    _trae_cli_command,
    _utc_now,
)

logger = logging.getLogger(__name__)


class SuperEmployeeCliRuntimeMixin:
    async def _run_cli_streaming(
        self,
        cli_path: str,
        prompt: str,
        cwd: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """异步执行 CLI，逐行读取 stdout 并 yield 事件。

        - stream-json 工具（claude/cursor/trae）：每行是 JSON 事件，解析出 text token
        - 非 stream-json 工具（codex）：stdout 不是结果，读 output-last-message 文件
        """
        with tempfile.TemporaryDirectory(prefix=f"xcagi-{self._p.tool_name}-stream-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = self._apply_scope_to_cmd(
                self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            )
            env = self._cli_subprocess_env()
            # Trae/Claude stream-json 单行常超过 asyncio 默认 64KiB，readline 会抛
            # LimitOverrunError → 整段 SSE 失败，手机误报「连接不到电脑工具」。
            stream_limit = int(os.environ.get("XCMAX_CLI_STREAM_LINE_LIMIT") or (8 * 1024 * 1024))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    limit=max(stream_limit, 64 * 1024),
                )
            except (OSError, FileNotFoundError) as exc:
                yield {
                    "type": "error",
                    "message": f"{self._p.display_tool} CLI 启动失败：{exc}",
                }
                return

            idle_timeout = self._cli_idle_timeout_seconds()
            hard_cap = self._cli_hard_cap_seconds()
            started = time.monotonic()
            last_activity = time.monotonic()
            stream_json = self._p.cli_stream_json
            text_parts: list[str] = []

            async def _read_stderr() -> str:
                if proc.stderr is None:
                    return ""
                try:
                    data = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                    return data.decode("utf-8", errors="replace")
                except TimeoutError:
                    return ""

            async def _readline_stdout() -> bytes:
                """readline；超长行时降级分块，避免 LimitOverrun 打断整段流。"""
                assert proc.stdout is not None
                try:
                    return await asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
                except ValueError as exc:
                    msg = str(exc)
                    if "limit" not in msg.lower() and "Separator is found" not in msg:
                        raise
                    logger.warning(
                        "%s CLI stdout line exceeded stream limit; draining remainder",
                        self._p.display_tool,
                    )
                    try:
                        chunk = await asyncio.wait_for(proc.stdout.read(1024 * 1024), timeout=3.0)
                    except TimeoutError:
                        return b"\n"
                    if not chunk:
                        return b""
                    nl = chunk.find(b"\n")
                    if nl >= 0:
                        return chunk[: nl + 1]
                    return chunk + b"\n"

            while True:
                if proc.stdout is None:
                    break
                try:
                    raw_line = await _readline_stdout()
                except TimeoutError:
                    # 检查 idle/hardcap 超时
                    now = time.monotonic()
                    if idle_timeout > 0 and (now - last_activity) > idle_timeout:
                        proc.kill()
                        yield {
                            "type": "error",
                            "message": f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无输出，判定卡住。",
                        }
                        return
                    if hard_cap > 0 and (now - started) > hard_cap:
                        proc.kill()
                        yield {
                            "type": "error",
                            "message": f"{self._p.display_tool} CLI 运行超过 {hard_cap:g} 秒，已停止。",
                        }
                        return
                    continue
                if not raw_line:
                    # EOF — 进程结束
                    break
                last_activity = time.monotonic()
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                if stream_json and line.startswith("{"):
                    token = self._parse_stream_json_line(line)
                    if token:
                        text_parts.append(token)
                        yield {"type": "token", "text": token}
                # 非 stream-json 的 stdout 行不 yield（codex 的 stdout 是日志，不是回复）

            # 等待进程退出
            await proc.wait()
            returncode = int(proc.returncode or 0)

            # stream-json：text_parts 已收集
            if stream_json:
                body = "".join(text_parts).strip()
                if body:
                    yield {"type": "done", "text": body}
                    return
                # 没拿到文本 → 尝试 stderr
                if returncode != 0:
                    stderr_text = await _read_stderr()
                    yield {
                        "type": "error",
                        "message": f"{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}",
                    }
                    return
                yield {"type": "done", "text": ""}
                return

            # 非 stream-json（codex）：读 output-last-message 文件
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    yield {"type": "done", "text": body}
                    return
            if returncode != 0:
                stderr_text = await _read_stderr()
                yield {
                    "type": "error",
                    "message": f"{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}",
                }
                return
            yield {"type": "done", "text": ""}

    def _parse_stream_json_line(self, line: str) -> str:
        """解析单行 stream-json 事件，返回文本 token（无文本则空串）。"""
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(ev, dict):
            return ""
        # Claude Code 事件格式
        ev_type = ev.get("type")
        if ev_type == "assistant":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            for blk in msg.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    t = str(blk.get("text") or "")
                    if t:
                        return t
        elif ev_type == "result":
            r = ev.get("result")
            if isinstance(r, str) and r.strip():
                return r
        # Cursor / Trae 事件格式（stream-json，含 content 数组）
        elif ev_type == "content_block_delta":
            delta = ev.get("delta") if isinstance(ev.get("delta"), dict) else {}
            t = str(delta.get("text") or "")
            if t:
                return t
        elif ev_type == "message_delta":
            # 部分工具在 message_delta 里带 text
            t = str(ev.get("text") or "")
            if t:
                return t
        return ""
    def _should_reply_with_cli(self, text: str, context: dict[str, Any]) -> bool:
        # 全局开关：所有 claude.invoke/codex.invoke 都走 FHD 进程内 CLI 直答，
        # 绕开 Para 派工（watchdog token 不可用时的兜底路径）。FHD 进程继承
        # 用户 Terminal 的 claude/codex 鉴权，无需额外配置。env: XCMAX_<TOOL>_FORCE_CLI_DIRECT=1。
        force_direct = (
            (
                os.environ.get(f"{self._p.env_tool_prefix}_FORCE_CLI_DIRECT")
                or os.environ.get("XCMAX_FORCE_CLI_DIRECT")
                or ""
            )
            .strip()
            .lower()
        )
        if force_direct in {"1", "true", "yes", "on"}:
            return True
        # 桌面云中继本身就是执行端：它派来的任务必须在本地 CLI 真跑，绝不能再转发 Para
        # 多设备（Para 在执行端不可用 → 任务一律 blocked）。中继在 context 打这个标记，
        # 与 mode 解耦——这样既能本地 CLI 执行，又能让 _is_task_intent 按 mode=code 判为开发任务。
        if context.get("force_cli_direct") is True:
            return True
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return True
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return False
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        return not any(marker in normalized for marker in _TASK_MARKERS)

    def _cli_reply_body(self, text: str, context: dict[str, Any]) -> str:
        if str(
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_CHAT_ENABLED") or "1"
        ).strip().lower() in {
            "0",
            "false",
            "off",
            "disabled",
        }:
            return ""
        cli_path = self._cli_path()
        if not cli_path:
            return ""
        # 口袋 Claude Code：claude 生产路径走"持久会话续接 + 隔离工作区"——有上下文、能动手、
        # 体验接近直接和 Claude Code 交互。codex / 测试注入仍走原"闲聊 or dev-loop"逻辑。
        # 但中继工单(force_cli_direct)要的是"真交付"：必须走 dev-loop(用各工具自己的命令
        # 构造器 → 真改文件→提交→推分支)，绝不能落进 claude 式 --resume 会话(对 cursor/trae
        # 命令不对、且不产出分支)。这是 Trae/Cursor 也能真执行的关键。
        if (
            self._p.cli_stream_json
            and self._cli_runner is _facade_attr("subprocess", subprocess).run
            and self._conversation_mode_enabled()
            and not context.get("force_cli_direct")
        ):
            return self._run_conversation_turn(cli_path, text, context)
        base_cwd = self._cli_workspace(context)
        # 闲聊→只答不改；开发任务→生产环境走 coding→view→push 闭环(隔离 worktree)，
        # 测试注入或显式关闭(_DEV_LOOP=0)时退回"只改不推"的简单路径。
        if not self._is_task_intent(text, context):
            return self._run_cli_once(cli_path, self._cli_prompt(text), base_cwd)
        if self._cli_runner is not _facade_attr("subprocess", subprocess).run or not self._dev_loop_enabled():
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        return self._run_dev_task_loop(cli_path, text, base_cwd, context)

    # ===== 口袋 Claude Code：持久会话续接 + 隔离工作区 =====

    def _conversation_mode_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_CONVERSATION")
                or os.environ.get("XCMAX_CLAUDE_CONVERSATION")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def _session_store_path(self) -> Path:
        return Path(_facade_attr("get_app_data_dir", get_app_data_dir)()) / self._p.storage_subdir / "cli_sessions.json"

    def _session_get(self, key: str) -> dict[str, Any]:
        try:
            data = json.loads(self._session_store_path().read_text(encoding="utf-8"))
            rec = data.get(key) if isinstance(data, dict) else None
            return rec if isinstance(rec, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _session_set(self, key: str, value: dict[str, Any]) -> None:
        p = self._session_store_path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            data = {}
        data[key] = value
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("写 session store 失败", exc_info=True)

    def _session_key(self, context: dict[str, Any]) -> str:
        """会话键：手机端是单一 pinned 会话，按工具名即可隔离 claude/codex 各自一条续接会话。"""
        conv = str((context or {}).get("conversation_id") or "").strip()
        return f"{self._p.tool_name}:{conv}" if conv else self._p.tool_name

    def _ensure_session_workspace(self, key: str) -> tuple[str | None, str | None]:
        """持久隔离工作区：同一会话复用一个 git worktree（不碰 live checkout、不破坏运行中的 FHD）。"""
        rec = self._session_get(key)
        wt = str(rec.get("workspace") or "")
        branch = str(rec.get("branch") or "")
        if wt and Path(wt).exists():
            return wt, branch
        base = self._cli_workspace({})
        if not self._is_git_repo(base):
            return None, None
        slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-") or "session"
        if not branch:
            branch = f"super-employee/{self._p.tool_name}/{slug}"
        wt = str(Path(_facade_attr("get_app_data_dir", get_app_data_dir)()) / self._p.storage_subdir / f"ws-{slug}")
        try:
            self._git(base, "worktree", "remove", "--force", wt, timeout=30)
        except Exception:  # noqa: BLE001
            pass
        has_branch = (
            self._git(base, "rev-parse", "--verify", "--quiet", branch, timeout=15).returncode == 0
        )
        if has_branch:
            r = self._git(base, "worktree", "add", "--force", wt, branch, timeout=180)
        else:
            r = self._git(base, "worktree", "add", "-b", branch, wt, "HEAD", timeout=180)
        if r.returncode != 0:
            logger.warning("会话工作区创建失败: %s", (r.stderr or r.stdout)[:200])
            return None, None
        rec["workspace"] = wt
        rec["branch"] = branch
        self._session_set(key, rec)
        return wt, branch

    def _conversation_prompt(self, text: str, cwd: str, resuming: bool) -> str:
        if resuming:
            # 续接：claude 已有完整上下文 + 身份，直接发用户原话（像和同事接着聊）。
            return text.strip()
        return (
            f"你是 XCMAX 内的{self._p.employee_name}，像 Claude Code 一样在项目工作区里工作："
            "可以读取/创建/修改文件、运行命令、用 git；用户让你改代码就直接动手，不要只解释。"
            "但普通对话直接回应即可、不要主动遍历整个项目（需要改代码时再读相关文件）；"
            "保持上下文连续，像和同事聊天那样自然。"
            f"\n\n工作区：{cwd}\n\n用户：{text.strip()}"
        )

    def _parse_stream_json_full(self, out: str) -> tuple[str, str]:
        """从 stream-json 取 (最终回复, session_id)。session_id 取最后出现的(result 事件含)。"""
        text = self._parse_claude_stream_json(out)
        sid = ""
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("session_id"):
                sid = str(ev.get("session_id") or "")
        return text, sid

    def _conversation_perm(self) -> str:
        # 默认 acceptEdits：可对话+读写改文件(覆盖大部分 Claude Code 用法)，但不自动跑任意命令，
        # 避免在工程根误伤运行中的 FHD。要全自动(跑命令/git)可 env 切 bypassPermissions。
        return (
            os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
        ).strip() or "acceptEdits"

    def _apply_scope_to_cmd(self, cmd: list[str]) -> list[str]:
        """信任墙第 4 层（纵深防御）：产品域收紧 claude 的工具面。

        把 ``--permission-mode`` 降到 ``default`` 并显式禁用写/执行类工具，使被注入的产品域
        会话即便被诱导喊 git/shell，那些工具也压根没注册 → 硬失败而非软拒绝。工厂域不动；
        codex 命令构造默认已是 ``--sandbox workspace-write``，此处不改。
        """
        if not cmd:
            return cmd
        # 工厂域 / 中继工单(操作者自己派工，force_cli_direct)/ 非 claude 工具 → 不收紧工具面。
        # 中继工单是操作者本人在自己机器上派给本机 CLI 的活，等同工厂域信任：放开全权限，
        # 否则 --disallowedTools 这种变长参数会把末位的 prompt 也吞掉(Claude 报权限拒绝)。
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
            prompt = out.pop()  # prompt 恒为末位参数
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

    def _run_conversation_turn(self, cli_path: str, text: str, context: dict[str, Any]) -> str:
        key = self._session_key(context)
        # 像 Claude Code 一样直接在工程根工作：零额外磁盘(不建 536M/会话的 worktree)、
        # 改动你审了再落地(底部 git 键)。上下文靠 claude session 续接，不靠工作区隔离。
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
                self._conversation_prompt(text, cwd, bool(session_id)),
                session_id or None,
            )
        except (OSError, _facade_attr("subprocess", subprocess).SubprocessError) as exc:
            return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
        body, new_sid = self._parse_stream_json_full(stdout)
        # resume 失效(会话被清/找不到)兜底：清掉 session_id，按新会话重来一次。
        if session_id and not body and not killed:
            low = (stderr + stdout).lower()
            if "no conversation" in low or "session" in low or returncode != 0:
                rec["session_id"] = ""
                self._session_set(key, rec)
                try:
                    returncode, stdout, stderr, killed = _run(
                        self._conversation_prompt(text, cwd, False), None
                    )
                    body, new_sid = self._parse_stream_json_full(stdout)
                except (OSError, _facade_attr("subprocess", subprocess).SubprocessError):
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
            return (
                f"{self._p.display_tool} 本次返回失败（code {returncode}）："
                f"{(stderr.strip() or stdout.strip())[:400]}"
            )
        return ""

    def _run_cli_once(self, cli_path: str, prompt: str, cwd: str) -> str:
        """运行一次 CLI 取最终回复文本（coding/闲聊共用；含测试注入与 idle-timeout 两路）。"""
        idle_timeout = self._cli_idle_timeout_seconds()
        hard_cap = self._cli_hard_cap_seconds()
        with tempfile.TemporaryDirectory(prefix=f"xcagi-{self._p.tool_name}-cli-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = self._apply_scope_to_cmd(
                self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            )
            # 注入式 runner(测试)走简单路径；生产用 idle-timeout：只要还在产出就不杀，
            # 仅"持续静默"(卡死/挂起)或超绝对上限才结束。
            if self._cli_runner is not _facade_attr("subprocess", subprocess).run:
                try:
                    proc = self._cli_runner(cmd, text=True, capture_output=True, cwd=cwd)
                except (OSError, _facade_attr("subprocess", subprocess).SubprocessError) as exc:
                    return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
                returncode = int(getattr(proc, "returncode", 0) or 0)
                stdout = str(getattr(proc, "stdout", "") or "")
                stderr = str(getattr(proc, "stderr", "") or "")
                killed_reason = ""
            else:
                try:
                    returncode, stdout, stderr, killed_reason = self._run_cli_idle(
                        cmd, cwd, idle_timeout, hard_cap
                    )
                except (OSError, _facade_attr("subprocess", subprocess).SubprocessError) as exc:
                    return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
            if killed_reason.startswith("idle"):
                return (
                    f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无任何输出，判定卡住已结束。"
                    "可能是网络或工具挂起，请重试。"
                )
            if killed_reason.startswith("hardcap"):
                return (
                    f"{self._p.display_tool} CLI 运行超过上限 {hard_cap:g} 秒仍未结束，已停止。"
                    "请把任务拆小一点再试。"
                )
            # stream-json(claude)：从事件流解析最终回复。
            if self._p.cli_stream_json:
                body = self._parse_claude_stream_json(stdout)
                if body:
                    return body
                if returncode != 0:
                    detail = (stderr.strip() or stdout.strip())[:500]
                    diagnosed = self._empty_cli_user_message(ran=True, stderr=detail)
                    if "额度" in diagnosed or "鉴权" in diagnosed or "限流" in diagnosed:
                        return diagnosed
                    return (
                        f"{self._p.display_tool} CLI 已接入，但本次返回失败"
                        f"（code {returncode}）：{detail}"
                    )
                return self._empty_cli_user_message(
                    ran=True, stderr=(stderr.strip() or stdout.strip())[:500]
                )
            # 非 stream(codex)：先读 last-message 文件，再退 stdout。
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    return body
            cleaned = self._clean_cli_stdout(stdout.strip())
            if cleaned:
                return cleaned
            if returncode != 0:
                detail = stderr.strip()[:500]
                diagnosed = self._empty_cli_user_message(ran=True, stderr=detail)
                if "额度" in diagnosed or "鉴权" in diagnosed or "限流" in diagnosed:
                    return diagnosed
                return (
                    f"{self._p.display_tool} CLI 已接入，但本次返回失败"
                    f"（code {returncode}）：{detail}"
                )
            return self._empty_cli_user_message(ran=True, stderr=stderr.strip()[:500])
        return self._empty_cli_user_message(ran=False)

    def _cli_path(self) -> str:
        candidates = [
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_PATH", ""),
            _facade_attr("shutil", shutil).which(self._p.cli_binary) or "",
            *self._p.cli_extra_candidates,
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value and _facade_attr("Path", Path)(value).is_file():
                return value
        return ""

    def _cli_workspace(self, context: dict[str, Any]) -> str:
        """解析本地 CLI 的工作目录，按执行域分流（信任墙第 3 层：工作区层）。

        - 工厂域：经 Workspace 注册表解析（含 P2 的 worktree 隔离）。
        - 产品域：**绝不采信客户提供的宿主路径**（防 path-injection / 越权读盘），一律用本档
          隔离的临时区。客户请求体里的 ``workspace_root`` 对产品域完全无效。
        """
        if self._grant.is_factory:
            try:
                reg = get_workspace_registry()
                ws = reg.get(self._grant.workspace_id)
                return str(reg.checkout(ws, task_id=str(context.get("request_id") or "task")))
            except WorkspaceError:
                return str(get_workspace_registry().get(None).root)
        # 中继工单（操作者自己桌面派给超级员工的开发任务）允许在**真实仓库**里跑 dev-loop，
        # 真改文件→提交→推分支，产出可合并的真东西（而非临时区里建完即被 GC 的占位文件）。
        # 仅在移动中继/本机操作者显式给出真实 git 仓库时生效；路径必须能在本机验证为 git
        # repo，普通产品域请求不会进入这里，不破坏「不采信客户提供宿主路径」的安全约束。
        relay_repo = self._relay_real_workspace(context)
        if relay_repo:
            return relay_repo
        return self._product_ephemeral_workspace()

    def _relay_real_workspace(self, context: dict[str, Any]) -> str:
        ctx = context if isinstance(context, dict) else {}
        source = str(ctx.get("source") or "").strip().lower()
        # 手机局域网直连(mobile_im)与云中继(mobile_relay)都是操作者本机执行端：
        # 允许使用已校验的真实仓库根，否则进度/上线类问答只能落在临时 scratch。
        is_operator_desktop = ctx.get("force_cli_direct") is True or source in {
            "mobile_relay",
            "mobile_im",
        }
        if not is_operator_desktop:
            return ""
        return _facade_attr("resolve_verified_relay_workspace_root", resolve_verified_relay_workspace_root)(ctx)

    def _factory_workspace_root(self) -> str:
        """工厂派工请求里写给远端设备的工作区根路径（不含 worktree 隔离，远端自理）。"""
        try:
            return str(get_workspace_registry().get(self._grant.workspace_id).root)
        except WorkspaceError:
            return ""

    def _product_ephemeral_workspace(self) -> str:
        """产品域 CLI 的隔离临时工作目录。

        放在系统临时区（而非 app data / 存储根），保证开发态与生产态都**在任何工程树之外**
        —— 规避 ``_facade_attr("get_app_data_dir", get_app_data_dir)()`` 在源码运行时回落到 FHD 仓库根的已知陷阱。
        """
        base = Path(tempfile.gettempdir()) / "xcmax_product_scratch" / self._p.storage_subdir
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _cli_timeout_seconds(self) -> float:
        """Backward-compat alias for _cli_idle_timeout_seconds (used by tests)."""
        return self._cli_idle_timeout_seconds()

    def _cli_idle_timeout_seconds(self) -> float:
        # 活性检测：持续静默(无任何 stdout/stderr 输出)超过此值 → 判定卡住。
        # 只要 CLI 还在产出(stream-json 事件/进度行)就一直等，不因总时长被杀。
        raw = (
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_IDLE_TIMEOUT_SEC")
            or os.environ.get(f"{self._p.env_tool_prefix}_CLI_TIMEOUT_SEC")  # 兼容旧变量
            or "180"
        )
        try:
            return max(15.0, float(raw))
        except (TypeError, ValueError):
            return 180.0

    def _cli_hard_cap_seconds(self) -> float:
        # 绝对兜底(防真死循环)；<=0 表示无上限。默认 1 小时。
        raw = os.environ.get(f"{self._p.env_tool_prefix}_CLI_HARD_CAP_SEC") or "3600"
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 3600.0

    def _cli_subprocess_env(self) -> dict[str, str] | None:
        """构造 CLI 子进程环境。两件事：

        1. 差异化代理：FHD 直连自有云端 xiu-ci.com（代理会断 SSL），但 claude/codex 调
           api.anthropic.com 等需走代理（直连被 403）。仅当 XCMAX_CLI_PROXY 设了才注入。
        2. 信任墙第 2 层：**产品域**剥掉平台工厂令牌与 git 凭证，客户驱动的子进程永远拿不到
           平台机密（防被注入后偷令牌/推代码）。

        工厂域且无代理：返回 None（继承当前环境，与历史行为一致，零回归）。
        """
        proxy = str(os.environ.get("XCMAX_CLI_PROXY") or "").strip()
        product = not (self._grant.is_factory or getattr(self, "_relay_cli_trusted", False))
        if not proxy and not product:
            return None
        env = os.environ.copy()
        if proxy:
            for k in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env[k] = proxy
        if product:
            for k in list(env.keys()):
                if (
                    k == FACTORY_TOKEN_ENV
                    or k.startswith("XCMAX_FACTORY")
                    or k in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_ASKPASS", "GIT_TOKEN")
                ):
                    env.pop(k, None)
        return env

    def _run_cli_idle(
        self,
        cmd: list[str],
        cwd: str,
        idle_timeout: float,
        hard_cap: float,
    ) -> tuple[int, str, str, str]:
        """跑 cmd，只在「持续 idle_timeout 秒无输出」(卡住)或超 hard_cap 时才 kill；
        只要还在产出就不杀。返回 (returncode, stdout, stderr, killed_reason)。"""

        proc = _facade_attr("subprocess", subprocess).Popen(
            cmd,
            cwd=cwd,
            text=True,
            bufsize=1,
            stdout=_facade_attr("subprocess", subprocess).PIPE,
            stderr=_facade_attr("subprocess", subprocess).PIPE,
            env=self._cli_subprocess_env(),
        )
        out_parts: list[str] = []
        err_parts: list[str] = []
        last_activity = [time.monotonic()]
        lock = threading.Lock()

        def _pump(stream, sink: list[str]) -> None:
            try:
                for line in iter(stream.readline, ""):
                    with lock:
                        sink.append(line)
                        last_activity[0] = time.monotonic()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        t_out = threading.Thread(target=_pump, args=(proc.stdout, out_parts), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, err_parts), daemon=True)
        t_out.start()
        t_err.start()
        started = time.monotonic()
        killed_reason = ""
        while True:
            try:
                proc.wait(timeout=3)
                break
            except _facade_attr("subprocess", subprocess).TimeoutExpired:
                pass
            now = time.monotonic()
            with lock:
                idle = now - last_activity[0]
            if idle_timeout > 0 and idle > idle_timeout:
                killed_reason = f"idle:{idle_timeout:g}"
            elif hard_cap > 0 and (now - started) > hard_cap:
                killed_reason = f"hardcap:{hard_cap:g}"
            if killed_reason:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except _facade_attr("subprocess", subprocess).TimeoutExpired:
                    pass
                break
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        return int(proc.returncode or 0), "".join(out_parts), "".join(err_parts), killed_reason

    def _parse_claude_stream_json(self, out: str) -> str:
        """从 claude --output-format stream-json 的事件流里取最终回复。"""
        result = ""
        texts: list[str] = []
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "result":
                r = ev.get("result")
                if isinstance(r, str) and r.strip():
                    result = r.strip()
            elif ev.get("type") == "assistant":
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
                for blk in msg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        t = str(blk.get("text") or "").strip()
                        if t:
                            texts.append(t)
        return result or "\n".join(texts).strip()

    def _cli_prompt(self, text: str) -> str:
        return (
            f"你是 XCMAX 软件内的{self._p.employee_name}，当前工作区就是本机项目仓库。"
            "请直接回答用户的问题。"
            "这是只读问答通道：可以读取仓库文件、git 状态、CHANGELOG、VERSION、待办与测试结果来回答进度/上线差距类问题；"
            "不要修改文件、不要提交、不要推送、不要安装依赖。"
            "如果确实读不到真实数据，请说明缺什么，不要编造数字。"
            "如果用户询问额度、账户余额、订阅或实时账户状态，而你无法从当前会话读取真实账户数据，"
            "请明确说明不能查看，不要编造数字。"
            "\n\n用户问题："
            f"{text.strip()}"
        )

    def _is_task_intent(self, text: str, context: dict[str, Any]) -> bool:
        """是否为开发任务（需要真改代码），与 force-direct 无关，仅看 mode/关键词。"""
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return False
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return True
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        return any(marker in normalized for marker in _TASK_MARKERS)

    def _cli_work_prompt(self, text: str, cwd: str) -> str:
        """开发任务 prompt：授权 Claude 真正读写/修改工作区文件（配合 --permission-mode acceptEdits）。"""
        return (
            f"你是 XCMAX 软件内的{self._p.employee_name}，运行在项目工作区，"
            "拥有完整的文件读写与代码修改能力。请直接动手完成下面的开发任务："
            "按需读取、创建、修改工作区内的文件来实现需求；不要只给建议或只解释，要真正改代码。"
            "完成后用一两句话总结你改了哪些文件、做了什么。"
            f"\n\n工作区根目录：{cwd}"
            "\n\n开发任务：\n"
            f"{text.strip()}"
        )

    # ===== coding → view → push 闭环（开发任务）=====
    def _clean_cli_stdout(self, stdout: str) -> str:
        lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {self._p.tool_name, "codex", "tokens used"}:
                continue
            if re.fullmatch(r"[\d,]+", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _is_cli_unavailable_message(self, body: str) -> bool:
        text = (body or "").strip()
        if not text:
            return True
        tool = self._p.display_tool
        markers = (
            f"{tool} CLI 暂时没有返回内容",
            f"本机未找到 {tool} CLI",
            f"{tool} CLI 已运行但没有返回内容",
            f"{tool} 暂时无法回复",
            f"{tool} 当前没有可用额度",
            f"{tool} CLI 已启动但鉴权失败",
        )
        return any(text.startswith(m) or m in text[:80] for m in markers)

    def _empty_cli_user_message(self, *, ran: bool, stderr: str = "") -> str:
        """区分「本机没通 / CLI 未装 / 额度或鉴权」——勿一律说「请确认已登录」。

        超级员工走本机 CLI，不走平台钱包扣费；钱包不足会出现在小 C / 普通 AI 对话，
        不应与本通道混淆。
        """
        tool = self._p.display_tool
        detail = (stderr or "").strip()
        lowered = detail.lower()
        quota_markers = (
            "quota",
            "rate limit",
            "ratelimit",
            "usage limit",
            "insufficient",
            "billing",
            "payment required",
            "余额",
            "额度",
            "次数用尽",
            "超出限额",
        )
        auth_markers = (
            "login",
            "log in",
            "sign in",
            "unauthorized",
            "unauthenticated",
            "not logged",
            "api key",
            "auth",
            "token expired",
            "未登录",
            "鉴权",
            "请先登录",
        )
        if any(m in lowered or m in detail for m in quota_markers):
            snippet = detail[:220] if detail else "工具返回额度/限流相关错误"
            return (
                f"{tool} 当前没有可用额度或触发限流（与 XCAGI 钱包余额无关）。"
                f"请在本机检查 {tool} 账号套餐/用量后重试。详情：{snippet}"
            )
        if ran and any(m in lowered or m in detail for m in auth_markers):
            snippet = detail[:220] if detail else "工具返回鉴权相关错误"
            return f"{tool} CLI 已启动但鉴权失败，请在本机重新登录 {tool} 后重试。详情：{snippet}"
        if not self._cli_path():
            return (
                f"本机未找到 {tool} CLI，超级员工无法在此服务器进程内执行。"
                "请用手机扫码绑定已安装并登录该工具的电脑执行端，"
                "或同一 WiFi 下开启局域网直连后再试。"
                "（这与钱包额度无关。）"
            )
        if ran:
            hint = f" 详情：{detail[:220]}" if detail else ""
            return (
                f"{tool} CLI 已运行但没有返回内容，常见原因是本机未登录或会话失效。"
                f"请在电脑端确认 {tool} 已登录后重试。{hint}"
            )
        return (
            f"{tool} 暂时无法回复。请确认电脑执行端在线、已绑定，"
            f"且本机已安装并登录 {tool}。（与钱包额度无关。）"
        )

    def _compose_direct_chat_reply(
        self,
        text: str,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        """普通对话直答：FAQ → CLI → 明确不可用提示。"""
        canned = self._direct_reply_body(text)
        if canned:
            return canned, f"{self._p.tool_name}_direct"
        cli_path = self._cli_path()
        if not cli_path:
            return self._empty_cli_user_message(ran=False), f"{self._p.tool_name}_cli_missing"
        cli_body = self._cli_reply_body(text, context)
        if cli_body:
            return cli_body, f"{self._p.tool_name}_cli"
        return (
            self._empty_cli_user_message(ran=True),
            f"{self._p.tool_name}_cli",
        )

    def _direct_reply_body(self, text: str) -> str:
        normalized = re.sub(r"[\s，。！？!?、,.]+", "", text.strip().lower())
        if not normalized:
            return ""
        tool = self._p.display_tool
        name = self._p.employee_name
        identity_prompts = {
            "你是谁",
            "你是誰",
            "你谁",
            "你是哪个",
            "你是什么",
            "whoareyou",
            "whatareyou",
        }
        help_prompts = {
            "你能做什么",
            "你能干什么",
            "你会什么",
            "怎么用",
            "如何使用",
            "帮助",
            "help",
        }
        greeting_prompts = {"你好", "在吗", "在不在", "hello", "hi"}
        ping_prompts = {"ping", "pingpong", "ping-pong"}
        slow_prompts = {"为什么这么慢", "为啥这么慢", "为什么出不来", "怎么出不来"}

        if normalized in ping_prompts:
            return (
                f"pong，我是 XCMAX {name}，当前已就绪。"
                f"可直接发开发/排查任务；普通问答也会在此通道回复。"
            )
        if normalized in identity_prompts:
            return (
                f"我是{name}。你在软件里发普通问题时，我会直接回复；"
                f"你发开发、测试、打包、提交、跨设备协作这类任务时，我会调用可用的 {tool} 工作设备完成。"
            )
        if normalized in help_prompts:
            return (
                "你可以直接给我派开发任务，例如修复某个页面、跑测试、打包移动端、提交代码。"
                "如果只是问身份、用法或状态，我会在这里直接回复，不进入多设备派工。"
            )
        if normalized in greeting_prompts:
            return "我在。需要改代码、跑验证或跨设备协作时，直接把任务发给我。"
        if normalized in slow_prompts:
            return (
                "慢是因为这类消息之前被误当成开发任务派到多设备队列，必须等工作设备回传才显示结果。"
                "现在身份、帮助和问候类消息会直接回复；真正的开发任务才进入派工。"
            )
        return ""
