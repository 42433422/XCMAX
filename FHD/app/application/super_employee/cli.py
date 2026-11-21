"""Own CLI processes, bounded waits, stream drainage, and final output selection."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path
from typing import Any, TextIO

from .output import CliOutput
from .profiles import SuperEmployeeToolProfile
from .protocols import CliPorts


class CliExecutionError(RuntimeError):
    """A failed CLI attempt whose partial text is evidence, never a success result."""

    def __init__(
        self,
        tool: str,
        reason: str,
        *,
        exit_code: int | None = None,
        partial_text: str = "",
        stderr: str = "",
        started: bool = True,
        stage: str = "cli",
    ) -> None:
        if stage != "cli":
            detail = {
                "workspace": "工作区准备失败",
                "verification": "验证未通过",
                "publication": "发布失败",
            }.get(stage, "执行失败")
            code = f"development_{reason}"
        elif reason.startswith("idle:"):
            detail, code = "静默超时，执行已中止", "cli_timeout"
        elif reason.startswith(("hardcap:", "timeout:")):
            detail, code = "运行超过上限，执行已中止", "cli_timeout"
        elif reason == "nonzero_exit":
            detail, code = f"返回失败（code {exit_code}）", "cli_nonzero_exit"
        elif reason == "empty_response":
            detail, code = "没有返回最终内容", "cli_empty_response"
        elif reason == "unavailable":
            detail, code = "不可用或未启用", "cli_unavailable"
        else:
            detail, code = "调用失败，未取得成功退出回执", "cli_execution_failed"
        if not started and reason != "unavailable" and stage == "cli":
            detail = "启动失败"
            code = "cli_launch_failed"
        diagnostic = stderr[:4096] + ("\n[stderr truncated]" if len(stderr) > 4096 else "")
        message = f"{tool}{' CLI' if stage == 'cli' else ''} {detail}。"
        if started:
            message += "任务效果尚未确认，请核对已有变更；不会自动重放。"
        if diagnostic:
            message += "\n" + diagnostic
        super().__init__(message)
        self.receipt: dict[str, Any] = {
            "success": False,
            "status": "failed",
            "outcome": "unknown" if started else "failed",
            "error_code": code,
            "error": message,
            "message": message,
            "execution_started": started,
            "execution_state": "failed" if started else "not_started",
            "stage": stage,
            "exit_code": exit_code,
            "termination_reason": reason,
            "partial_text": partial_text,
            "stderr": diagnostic,
            "retryable": False,
            "reconciliation_required": started,
        }

    @property
    def body(self) -> str:
        partial = self.receipt["partial_text"]
        return str(self) + (f"\n\n未确认的部分输出：\n{partial}" if partial else "")

    def event(self) -> dict[str, Any]:
        return {"type": "error", **self.receipt}


def require_cli_success(
    tool: str, returncode: int | None, text: str, stderr: str = "", killed_reason: str = ""
) -> str:
    reason = killed_reason or (
        "exit_unknown"
        if returncode is None
        else "nonzero_exit"
        if returncode != 0
        else "empty_response"
        if not text.strip()
        else ""
    )
    if reason:
        raise CliExecutionError(
            tool, reason, exit_code=returncode, partial_text=text, stderr=stderr
        )
    return text


def cli_exception(
    tool: str, exc: OSError | subprocess.SubprocessError, *, partial_text: str = "", started: bool
) -> CliExecutionError:
    if isinstance(exc, subprocess.TimeoutExpired):
        reason, started = f"timeout:{exc.timeout:g}", True
    elif isinstance(exc, subprocess.CalledProcessError):
        reason, started = "nonzero_exit", True
    else:
        reason = "process_error" if started else "launch_failed"
    stderr = getattr(exc, "stderr", "") or (str(exc) if isinstance(exc, OSError) else "")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    return CliExecutionError(
        tool,
        reason,
        exit_code=getattr(exc, "returncode", None),
        partial_text=partial_text,
        stderr=stderr,
        started=started,
    )


class CliExecutor:
    def __init__(self, profile: SuperEmployeeToolProfile, ports: CliPorts) -> None:
        self._p, self._ports = profile, ports
        self._output = CliOutput(profile.tool_name)

    def run_cli_once(self, cli_path: str, prompt: str, cwd: str) -> str:
        """运行一次 CLI 取最终回复文本（coding/闲聊共用；含测试注入与 idle-timeout 两路）。"""
        idle_timeout = self._ports.idle_timeout()
        hard_cap = self._ports.hard_cap()
        with tempfile.TemporaryDirectory(prefix=f"xcagi-{self._p.tool_name}-cli-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = self._ports.apply_scope(
                self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            )
            runner = self._ports.runner()
            stdout = ""
            execution_started = False
            try:
                if runner is not subprocess.run:
                    proc = runner(cmd, text=True, capture_output=True, cwd=cwd)
                    execution_started = True
                    returncode = getattr(proc, "returncode", None)
                    stdout = str(getattr(proc, "stdout", "") or "")
                    stderr = str(getattr(proc, "stderr", "") or "")
                    killed_reason = ""
                else:
                    returncode, stdout, stderr, killed_reason = self._ports.run_idle(
                        cmd, cwd, idle_timeout, hard_cap
                    )
                    execution_started = True
                body = self._reply_text(
                    output_path, stdout, best_effort=bool(killed_reason) or returncode != 0
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raw = getattr(exc, "stdout", "") or stdout
                stdout = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                raise cli_exception(
                    self._p.display_tool,
                    exc,
                    partial_text=self._reply_text(output_path, stdout, best_effort=True),
                    started=execution_started or runner is subprocess.run,
                ) from exc
            return require_cli_success(
                self._p.display_tool,
                returncode,
                body,
                stderr,
                killed_reason,
            )

    def _reply_text(self, output_path: Path, stdout: str, *, best_effort: bool = False) -> str:
        if self._p.cli_stream_json:
            return self._output.parse_claude_stream_json(stdout)
        if self._p.cli_reads_output_file and output_path.exists():
            try:
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    return body
            except OSError:
                if not best_effort:
                    raise
        return self._output.clean_cli_stdout(stdout.strip())

    def run_cli_idle(
        self, cmd: list[str], cwd: str, idle_timeout: float, hard_cap: float
    ) -> tuple[int | None, str, str, str]:
        """跑 cmd，只在「持续 idle_timeout 秒无输出」(卡住)或超 hard_cap 时才 kill；
        只要还在产出就不杀。返回 (returncode, stdout, stderr, killed_reason)。"""
        import threading

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                text=True,
                bufsize=1,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._ports.environment(),
            )
        except OSError as exc:
            raise cli_exception(self._p.display_tool, exc, started=False) from exc
        out_parts: list[str] = []
        err_parts: list[str] = []
        last_activity = [time.monotonic()]
        lock = threading.Lock()

        def _pump(stream: TextIO, sink: list[str]) -> None:
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
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            with lock:
                idle = now - last_activity[0]
            if idle_timeout > 0 and idle > idle_timeout:
                killed_reason = f"idle:{idle_timeout:g}"
            elif hard_cap > 0 and now - started > hard_cap:
                killed_reason = f"hardcap:{hard_cap:g}"
            if killed_reason:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                break
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        return (proc.returncode, "".join(out_parts), "".join(err_parts), killed_reason)

    async def run_cli_streaming(
        self, cli_path: str, prompt: str, cwd: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """异步执行 CLI，逐行读取 stdout 并 yield 事件。

        - stream-json 工具（claude/cursor/trae）：每行是 JSON 事件，解析出 text token
        - 非 stream-json 工具（codex）：优先 output-last-message，再沿用同步的 stdout 兜底
        """
        with tempfile.TemporaryDirectory(prefix=f"xcagi-{self._p.tool_name}-stream-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = self._ports.apply_scope(
                self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            )
            env = self._ports.environment()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except OSError as exc:
                yield cli_exception(self._p.display_tool, exc, started=False).event()
                return
            idle_timeout = self._ports.idle_timeout()
            hard_cap = self._ports.hard_cap()
            started = time.monotonic()
            last_activity = time.monotonic()
            stream_json = self._p.cli_stream_json
            text_parts: list[str] = []

            stderr_prefix = bytearray()

            async def drain_stderr() -> None:
                nonlocal last_activity
                if proc.stderr is not None:
                    while data := await proc.stderr.read(8192):
                        last_activity = time.monotonic()
                        # Drain the entire pipe, retaining only bounded error context.
                        stderr_prefix.extend(data[: max(0, 4096 - len(stderr_prefix))])

            def timeout_reason() -> str:
                now = time.monotonic()
                if idle_timeout > 0 and now - last_activity > idle_timeout:
                    return f"idle:{idle_timeout:g}"
                if hard_cap > 0 and now - started > hard_cap:
                    return f"hardcap:{hard_cap:g}"
                return ""

            def partial_text(*, best_effort: bool = False) -> str:
                text = "".join(text_parts).strip()
                return (
                    text
                    if stream_json
                    else self._reply_text(output_path, text, best_effort=best_effort)
                )

            def timeout_event(reason: str) -> dict[str, Any]:
                return CliExecutionError(
                    self._p.display_tool,
                    reason,
                    exit_code=proc.returncode,
                    partial_text=partial_text(best_effort=True),
                    stderr=stderr_prefix.decode("utf-8", errors="replace"),
                ).event()

            stderr_task = asyncio.create_task(drain_stderr())
            reaped = False
            try:
                while proc.stdout is not None:
                    if reason := timeout_reason():
                        yield timeout_event(reason)
                        return
                    try:
                        raw_line = await asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
                    except TimeoutError:
                        continue
                    if not raw_line:
                        break
                    last_activity = time.monotonic()
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    if stream_json and line.startswith("{"):
                        token = self._output.parse_stream_json_line(line)
                        if token:
                            text_parts.append(token)
                            yield {"type": "token", "text": token}
                    elif not stream_json:
                        text_parts.append(line + "\n")
                # EOF does not guarantee process exit. Retain the same time limits.
                while True:
                    if reason := timeout_reason():
                        yield timeout_event(reason)
                        return
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                        reaped = True
                        break
                    except TimeoutError:
                        continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(stderr_task, timeout=2.0)
                body = partial_text(best_effort=proc.returncode != 0)
                try:
                    require_cli_success(
                        self._p.display_tool,
                        proc.returncode,
                        body,
                        stderr_prefix.decode("utf-8", errors="replace"),
                    )
                except CliExecutionError as exc:
                    yield exc.event()
                else:
                    yield {"type": "done", "text": body}
            except (OSError, subprocess.SubprocessError) as exc:
                failure = cli_exception(
                    self._p.display_tool,
                    exc,
                    partial_text=partial_text(best_effort=True),
                    started=True,
                )
                failure.receipt["exit_code"] = proc.returncode
                yield failure.event()
            finally:
                # Closing/cancelling the async iterator also owns process cleanup.
                if not reaped:
                    if proc.returncode is None:
                        with suppress(ProcessLookupError):
                            proc.kill()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                if not stderr_task.done():
                    stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
