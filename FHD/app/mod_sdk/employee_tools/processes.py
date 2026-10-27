"""Own a command's child process through success, failure, timeout and cancellation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .employee_tool_ports import Payload


class SpawnProcess(Protocol):
    async def __call__(
        self,
        program: str,
        /,
        *args: str,
        cwd: str | None,
        stdout: int,
        stderr: int,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process: ...


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def _finish_owned_process(process: asyncio.subprocess.Process) -> None:
    """Repeated caller cancellation must not abandon the child while it is exiting."""
    cleanup = asyncio.create_task(_reap(process))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


class CommandRunner:
    def __init__(self, spawn: SpawnProcess, environment: Mapping[str, str]) -> None:
        self._spawn = spawn
        self._environment = environment

    async def run(
        self,
        args: list[str],
        *,
        cwd: str | Path | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> Payload:
        process: asyncio.subprocess.Process | None = None
        try:
            process = await self._spawn(
                *args,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**self._environment, **(env or {})},
            )
            communication = process.communicate()
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(communication, timeout=timeout)
            finally:
                # A patched wait_for can return without scheduling the coroutine.
                if inspect.iscoroutine(communication):
                    communication.close()
            return {
                "returncode": process.returncode,
                "stdout": stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "",
                "stderr": stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "",
                "ok": process.returncode == 0,
            }
        except TimeoutError:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
                "ok": False,
            }
        except FileNotFoundError as exc:
            return {"returncode": -1, "stdout": "", "stderr": str(exc), "ok": False}
        except RECOVERABLE_ERRORS as exc:
            return {"returncode": -1, "stdout": "", "stderr": repr(exc), "ok": False}
        finally:
            if process is not None and process.returncode is None:
                await _finish_owned_process(process)
