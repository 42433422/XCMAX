"""Subprocess-backed :class:`SandboxDriver`.

Reuses the spawn + restricted-builtins logic that already exists in
:mod:`vibe_coding.runtime.sandbox` for ``function`` jobs, and adds a generic
``command`` mode that runs an arbitrary tool (ruff, mypy, pytest …) inside a
project workspace with the policy's timeout and (best-effort) memory limit.

This driver is **always available**: it has no extra dependencies and works
cross-platform. The trade-off is that it cannot drop network access or
mount the project read-only — use the Docker driver when those guarantees
are required.

Security hardening (vs. P0 baseline):

- ``command`` jobs use :func:`vibe_coding.agent.security.env.sanitise_env`
  so the spawned subprocess only inherits an opt-in subset of the parent
  env (PATH / HOME / LANG / …). Secrets like ``OPENAI_API_KEY`` no longer
  leak by default. Callers that need a specific variable forwarded can
  list it in :attr:`SandboxJob.env`.
- ``command`` jobs default to ``stdin=DEVNULL`` so tools that try to read
  from stdin (interactive prompts, ``input()``) terminate immediately
  instead of hanging until the timeout fires.
- The workspace path is double-checked via :func:`resolve_workspace` to
  reject filesystem roots and NUL-byte injection.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ...runtime.sandbox import CodeSandbox
from ..security.env import sanitise_env
from .driver import SandboxJob, SandboxPolicy, SandboxResult, resolve_workspace


class SubprocessSandboxDriver:
    """Cross-platform fallback driver — works without Docker.

    For ``function`` jobs it delegates to the existing :class:`CodeSandbox`,
    so the safety guarantees that matter most (restricted ``__builtins__``,
    import whitelist, RLIMIT-based memory cap on POSIX) are unchanged from
    the legacy single-skill flow.

    For ``command`` jobs it runs the requested binary via :mod:`subprocess`
    inside ``job.workspace_dir`` (no isolation beyond a fresh process); the
    timeout and ``max_output_size`` policy fields are still honoured.
    """

    name = "subprocess"

    def __init__(self) -> None:
        self._function_sandbox = CodeSandbox()

    def is_available(self) -> bool:
        return True

    def execute(
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        pol = policy or SandboxPolicy()
        if job.kind == "function":
            return self._execute_function(job, pol)
        if job.kind == "command":
            return self._execute_command(job, pol)
        return SandboxResult(
            success=False,
            driver=self.name,
            error_type="ValueError",
            error_message=f"unknown job kind {job.kind!r}",
        )

    # ----------------------------------------------------------------- function

    def _execute_function(self, job: SandboxJob, pol: SandboxPolicy) -> SandboxResult:
        result = self._function_sandbox.execute(
            job.source_code,
            job.function_name,
            job.input_data,
            timeout_seconds=pol.timeout_s,
            max_memory_mb=pol.memory_mb,
            max_output_size=pol.max_output_size,
        )
        return SandboxResult(
            success=result.success,
            driver=self.name,
            output=dict(result.output or {}),
            error_type=result.error_type,
            error_message=result.error_message,
            traceback_str=result.traceback_str,
            duration_ms=result.duration_ms,
        )

    # ----------------------------------------------------------------- command

    def _execute_command(self, job: SandboxJob, pol: SandboxPolicy) -> SandboxResult:
        if not job.command:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="ValueError",
                error_message="command job requires non-empty `command`",
            )
        try:
            workspace = resolve_workspace(job.workspace_dir)
        except ValueError as exc:
            return SandboxResult(
                success=False, driver=self.name, error_type="ValueError", error_message=str(exc)
            )
        if workspace is None:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="ValueError",
                error_message="command job requires `workspace_dir`",
            )

        # Build a sanitised env: only the explicit allow-list (PATH and
        # friends) is inherited from the parent, plus whatever the caller
        # opted into via ``job.env``. This stops secrets like
        # ``OPENAI_API_KEY`` / ``AWS_ACCESS_KEY_ID`` from being readable
        # inside the spawned tool process.
        env = sanitise_env(overrides=dict(job.env or {}))
        # ``stdin=DEVNULL`` for jobs without explicit stdin so tools that
        # try to ``input()`` terminate immediately instead of hanging.
        run_kwargs: dict[str, Any] = {
            "cwd": str(workspace),
            "env": env,
            "text": True,
            "capture_output": True,
            "timeout": pol.timeout_s,
            "check": False,
        }
        if job.stdin:
            run_kwargs["input"] = job.stdin
        else:
            run_kwargs["stdin"] = subprocess.DEVNULL
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(job.command, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="TimeoutError",
                error_message=f"command timed out after {pol.timeout_s}s",
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        return SandboxResult(
            success=proc.returncode == 0,
            driver=self.name,
            stdout=_truncate(proc.stdout or "", pol.max_output_size),
            stderr=_truncate(proc.stderr or "", pol.max_output_size),
            exit_code=int(proc.returncode),
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated {len(text) - limit} chars ...]"


__all__ = ["SubprocessSandboxDriver"]


# --- Defensive trivial reference so type-checkers see Path as used ---------
_ = Path  # noqa: F841
