"""WebContainer-backed :class:`SandboxDriver`.

WebContainers (https://webcontainers.io) run a full Node.js stack inside
the user's browser via WebAssembly. They are ideal for **front-end**
sandboxing because:

- They speak a real Node API (npm install, vite dev, etc.) so the same
  ``vitest`` / ``tsc`` / ``eslint`` adapters work without spinning up a
  Docker image.
- The host page can mount them into an iframe so the user *sees* the dev
  server running while the agent edits files.

Because WebContainers live in the browser, this driver is a **bridge**:
it talks to a small HTTP server (the Web UI in :mod:`vibe_coding.agent.web`)
that proxies requests to the WebContainer instance over a websocket. The
shape of the request / response is intentionally simple so the bridge
can be implemented in any language.

Bridge contract (JSON over POST ``/exec``):

::

    request:
      {
        "kind": "command" | "function",
        "workspace_id": "vc-...",
        "command": ["vitest", "run"] | null,
        "source_code": "...",                # function jobs only
        "function_name": "run",              # function jobs only
        "input_data": {...},                 # function jobs only
        "env": {...},
        "timeout_s": 30,
        "max_output_size": 100000
      }

    response:
      {
        "success": true,
        "stdout": "...",
        "stderr": "...",
        "exit_code": 0,
        "duration_ms": 12.3,
        "output": {...}                      # function jobs only
      }

This driver is a **stub-with-graceful-fallback**: if the bridge URL is
not reachable, jobs return a "driver unavailable" :class:`SandboxResult`
rather than raising — the same heal loop that decides whether to skip a
tool also decides whether to skip the WebContainer driver.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .driver import SandboxJob, SandboxPolicy, SandboxResult


@dataclass(slots=True)
class WebContainerBridge:
    """Endpoint the driver talks to. Defaults match the bundled Web UI."""

    base_url: str = "http://127.0.0.1:8765/api/sandbox"
    auth_token: str = ""
    workspace_id: str = "default"
    request_timeout_s: float = 30.0


class WebContainerSandboxDriver:
    """Proxy driver that delegates to a browser-side WebContainer.

    Construction is cheap and never contacts the bridge — that happens
    lazily on the first :meth:`execute`. Use :meth:`is_available` (which
    pings ``GET /health`` on the bridge) when the caller needs a fast
    yes/no without paying a full job.
    """

    name = "webcontainer"

    def __init__(self, bridge: WebContainerBridge | None = None) -> None:
        self.bridge = bridge or WebContainerBridge()
        self._availability_cache: bool | None = None

    def is_available(self) -> bool:
        if self._availability_cache is not None:
            return self._availability_cache
        url = self.bridge.base_url.rstrip("/") + "/health"
        req = urllib.request.Request(url=url, method="GET")
        if self.bridge.auth_token:
            req.add_header("Authorization", f"Bearer {self.bridge.auth_token}")
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                self._availability_cache = resp.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            self._availability_cache = False
        return self._availability_cache

    def execute(
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        pol = policy or SandboxPolicy()
        if not self.is_available():
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="DriverUnavailable",
                error_message=f"WebContainer bridge {self.bridge.base_url!r} unreachable",
            )
        body = json.dumps(_serialise_job(job, pol, self.bridge.workspace_id)).encode("utf-8")
        url = self.bridge.base_url.rstrip("/") + "/exec"
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.bridge.auth_token:
            req.add_header("Authorization", f"Bearer {self.bridge.auth_token}")
        t0 = time.perf_counter()
        try:
            timeout = max(pol.timeout_s + 5.0, self.bridge.request_timeout_s)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type=f"HTTP{exc.code}",
                error_message=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        except (urllib.error.URLError, OSError) as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="NetworkError",
                error_message=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type="DecodeError",
                error_message=f"non-JSON bridge response: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        return SandboxResult(
            success=bool(payload.get("success", False)),
            driver=self.name,
            output=dict(payload.get("output") or {}),
            stdout=str(payload.get("stdout") or "")[: pol.max_output_size],
            stderr=str(payload.get("stderr") or "")[: pol.max_output_size],
            exit_code=int(payload.get("exit_code") or 0),
            error_type=str(payload.get("error_type") or ""),
            error_message=str(payload.get("error_message") or ""),
            traceback_str=str(payload.get("traceback_str") or ""),
            duration_ms=float(
                payload.get("duration_ms")
                or round((time.perf_counter() - t0) * 1000, 3)
            ),
        )


def _serialise_job(
    job: SandboxJob,
    policy: SandboxPolicy,
    workspace_id: str,
) -> dict[str, Any]:
    return {
        "kind": job.kind,
        "workspace_id": workspace_id,
        "command": list(job.command) if job.command else None,
        "source_code": job.source_code,
        "function_name": job.function_name,
        "input_data": dict(job.input_data or {}),
        "env": dict(job.env or {}),
        "stdin": job.stdin,
        "timeout_s": float(policy.timeout_s),
        "max_output_size": int(policy.max_output_size),
        "memory_mb": int(policy.memory_mb),
    }


__all__ = ["WebContainerBridge", "WebContainerSandboxDriver"]
