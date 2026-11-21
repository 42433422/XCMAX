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
    """A CLI attempt failed; partial output is evidence, never a success receipt."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        partial_output: str = "",
        started: bool = True,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.partial_output = partial_output
        self.started = started

    def payload(self) -> dict[str, Any]:
        return {
            "success": False,
            "error_code": "cli_execution_failed",
            "message": str(self),
            "returncode": self.returncode,
            "partial_output": self.partial_output,
            "retryable": False,
            "outcome": "unknown" if self.started else "failed",
            "reconciliation_required": self.started,
        }

    def reply_body(self) -> str:
        return str(self) + (
            f"\n\n未确认完成的输出：\n{self.partial_output}" if self.partial_output else ""
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
            if runner is not subprocess.run:
                try:
                    proc = runner(cmd, text=True, capture_output=True, cwd=cwd)
                except (OSError, subprocess.SubprocessError):
                    raise CliExecutionError(f"{self._p.display_tool} CLI 调用失败。") from None
                returncode = getattr(proc, "returncode", None)
                stdout = str(getattr(proc, "stdout", "") or "")
                killed_reason = ""
            else:
                try:
                    returncode, stdout, _stderr, killed_reason = self._ports.run_idle(
                        cmd, cwd, idle_timeout, hard_cap
                    )
                except (OSError, subprocess.SubprocessError):
                    raise CliExecutionError(f"{self._p.display_tool} CLI 调用失败。") from None
            body = ""
            if self._p.cli_stream_json:
                body = self._output.parse_claude_stream_json(stdout)
            elif self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
            if not body and not self._p.cli_stream_json:
                body = self._output.clean_cli_stdout(stdout.strip())
            failure = ""
            if killed_reason.startswith("idle"):
                failure = f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无输出，已停止；请先核对原任务。"
            elif killed_reason.startswith("hardcap"):
                failure = f"{self._p.display_tool} CLI 运行超过上限 {hard_cap:g} 秒，已停止；请先核对原任务。"
            elif type(returncode) is not int or returncode != 0:
                code = returncode if type(returncode) is int else "unknown"
                failure = f"{self._p.display_tool} CLI 返回失败（code {code}）；请先核对原任务。"
            if failure:
                raise CliExecutionError(
                    failure,
                    returncode=returncode if type(returncode) is int else None,
                    partial_output=body,
                )
            return body

    def run_cli_idle(
        self, cmd: list[str], cwd: str, idle_timeout: float, hard_cap: float
    ) -> tuple[int, str, str, str]:
        """跑 cmd，只在「持续 idle_timeout 秒无输出」(卡住)或超 hard_cap 时才 kill；
        只要还在产出就不杀。返回 (returncode, stdout, stderr, killed_reason)。"""
        import threading

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            text=True,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._ports.environment(),
        )
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
        return (
            proc.returncode if proc.returncode is not None else -1,
            "".join(out_parts),
            "".join(err_parts),
            killed_reason,
        )

    async def run_cli_streaming(
        self, cli_path: str, prompt: str, cwd: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """异步执行 CLI，逐行读取 stdout 并 yield 事件。

        - stream-json 工具（claude/cursor/trae）：每行是 JSON 事件，解析出 text token
        - 非 stream-json 工具（codex）：stdout 不是结果，读 output-last-message 文件
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
            except (OSError, FileNotFoundError):
                failure = CliExecutionError(f"{self._p.display_tool} CLI 启动失败。", started=False)
                yield {"type": "error", **failure.payload()}
                return
            idle_timeout = self._ports.idle_timeout()
            hard_cap = self._ports.hard_cap()
            started = time.monotonic()
            last_activity = time.monotonic()
            stream_json = self._p.cli_stream_json
            text_parts: list[str] = []
            stdout_prefix = ""

            def partial_output() -> str:
                if not stream_json and self._p.cli_reads_output_file and output_path.exists():
                    with suppress(OSError):
                        return output_path.read_text(encoding="utf-8", errors="replace").strip()
                return "".join(text_parts) if stream_json else stdout_prefix

            async def drain_stderr() -> None:
                nonlocal last_activity
                if proc.stderr is not None:
                    while await proc.stderr.read(8192):
                        last_activity = time.monotonic()
                        # Drain without returning CLI stderr, which may contain credentials.

            def timeout_message() -> str:
                now = time.monotonic()
                if idle_timeout > 0 and now - last_activity > idle_timeout:
                    return f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无输出，判定卡住。"
                if hard_cap > 0 and now - started > hard_cap:
                    return f"{self._p.display_tool} CLI 运行超过 {hard_cap:g} 秒，已停止。"
                return ""

            stderr_task = asyncio.create_task(drain_stderr())
            reaped = False
            try:
                while proc.stdout is not None:
                    if message := timeout_message():
                        failure = CliExecutionError(message, partial_output=partial_output())
                        yield {"type": "error", **failure.payload()}
                        return
                    try:
                        raw_line = await asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
                    except TimeoutError:
                        continue
                    if not raw_line:
                        break
                    last_activity = time.monotonic()
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    if not stream_json:
                        stdout_prefix += (line + "\n")[: max(0, 16_384 - len(stdout_prefix))]
                    if stream_json and line.startswith("{"):
                        token = self._output.parse_stream_json_line(line)
                        if token:
                            text_parts.append(token)
                            yield {"type": "token", "text": token}
                # EOF does not guarantee process exit. Retain the same time limits.
                while True:
                    if message := timeout_message():
                        failure = CliExecutionError(message, partial_output=partial_output())
                        yield {"type": "error", **failure.payload()}
                        return
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                        reaped = True
                        break
                    except TimeoutError:
                        continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(stderr_task, timeout=2.0)
                returncode = proc.returncode
                body = "".join(text_parts).strip() if stream_json else ""
                if not stream_json and self._p.cli_reads_output_file and output_path.exists():
                    body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if type(returncode) is int and returncode == 0:
                    yield {"type": "done", "text": body}
                else:
                    failure = CliExecutionError(
                        f"{self._p.display_tool} CLI 返回失败（code {returncode}）；请先核对原任务。",
                        returncode=returncode if type(returncode) is int else None,
                        partial_output=body or partial_output(),
                    )
                    yield {"type": "error", **failure.payload()}
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
