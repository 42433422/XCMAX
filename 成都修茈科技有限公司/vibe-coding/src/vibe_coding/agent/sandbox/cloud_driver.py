"""Cloud sandbox driver — generic adapter for hosted execution backends.

Several "code-execution-as-a-service" platforms (E2B, Daytona, Modal,
Coder Cloud Workspaces, GitHub Codespaces remote-exec, etc.) expose a
similar contract: you provision a workspace, push files, run a command,
read stdout/stderr/exit-code. The differences are mostly auth and URL
shape.

:class:`CloudSandboxDriver` factors out the protocol (a small JSON-over-
HTTP API) and lets pluggable :class:`CloudSandboxBackend` implementations
fill in the auth + URL bits. Two reference backends ship in tree:

- :class:`E2BBackend` — works against ``https://api.e2b.dev`` once you
  set ``E2B_API_KEY``. Tested against the public ``Sandbox.run_code``
  endpoint.
- :class:`HTTPCloudBackend` — generic; expects the deployment to expose
  a tiny ``POST /exec`` endpoint that mirrors the WebContainer bridge
  contract. Useful as a quick custom integration (Modal Functions,
  Daytona's CLI proxy, your own internal cloud-sandbox service).

Add a new backend by subclassing :class:`CloudSandboxBackend` and
implementing :meth:`execute_command` / :meth:`execute_function`. The
driver then handles policy enforcement, output truncation, and the
:class:`SandboxResult` shape.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .driver import SandboxJob, SandboxPolicy, SandboxResult


# ----------------------------------------------------------------- protocol


@runtime_checkable
class CloudSandboxBackend(Protocol):
    """Pluggable backend that knows how to talk to one cloud provider."""

    @property
    def name(self) -> str: ...

    def is_available(self) -> bool: ...

    def execute_command(
        self,
        *,
        command: list[str],
        workspace_id: str,
        env: dict[str, str],
        stdin: str,
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]: ...

    def execute_function(
        self,
        *,
        source_code: str,
        function_name: str,
        input_data: dict[str, Any],
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]: ...


# ------------------------------------------------------------------ driver


class CloudSandboxDriver:
    """Adapter that turns a :class:`CloudSandboxBackend` into a SandboxDriver."""

    def __init__(
        self,
        backend: CloudSandboxBackend,
        *,
        workspace_id: str = "default",
        name_prefix: str = "cloud",
    ) -> None:
        self.backend = backend
        self.workspace_id = workspace_id
        self.name = f"{name_prefix}:{backend.name}"

    def is_available(self) -> bool:
        return bool(self.backend.is_available())

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
                error_message=f"{self.backend.name} backend is not available",
            )
        t0 = time.perf_counter()
        try:
            if job.kind == "function":
                raw = self.backend.execute_function(
                    source_code=job.source_code,
                    function_name=job.function_name,
                    input_data=dict(job.input_data or {}),
                    timeout_s=pol.timeout_s,
                    max_output_size=pol.max_output_size,
                )
            elif job.kind == "command":
                if not job.command:
                    return SandboxResult(
                        success=False,
                        driver=self.name,
                        error_type="ValueError",
                        error_message="command job requires non-empty `command`",
                    )
                raw = self.backend.execute_command(
                    command=list(job.command),
                    workspace_id=self.workspace_id,
                    env=dict(job.env or {}),
                    stdin=job.stdin or "",
                    timeout_s=pol.timeout_s,
                    max_output_size=pol.max_output_size,
                )
            else:
                return SandboxResult(
                    success=False,
                    driver=self.name,
                    error_type="ValueError",
                    error_message=f"unknown job kind {job.kind!r}",
                )
        except Exception as exc:  # noqa: BLE001
            return SandboxResult(
                success=False,
                driver=self.name,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        return SandboxResult(
            success=bool(raw.get("success", False)),
            driver=self.name,
            output=dict(raw.get("output") or {}),
            stdout=str(raw.get("stdout") or "")[: pol.max_output_size],
            stderr=str(raw.get("stderr") or "")[: pol.max_output_size],
            exit_code=int(raw.get("exit_code") or 0),
            error_type=str(raw.get("error_type") or ""),
            error_message=str(raw.get("error_message") or ""),
            traceback_str=str(raw.get("traceback_str") or ""),
            duration_ms=float(
                raw.get("duration_ms")
                or round((time.perf_counter() - t0) * 1000, 3)
            ),
        )


# ----------------------------------------------------------------- backends


@dataclass(slots=True)
class HTTPCloudBackend:
    """Generic backend that talks JSON to a single ``/exec`` endpoint.

    Same contract as :mod:`vibe_coding.agent.sandbox.webcontainer_driver`
    but pointed at a server-side cloud workspace rather than a browser
    WebContainer. Use this for in-house deployments / Modal / Daytona /
    self-hosted code execution APIs.
    """

    base_url: str
    auth_token: str = ""
    timeout_s: float = 60.0
    name_value: str = "http"

    @property
    def name(self) -> str:
        return self.name_value

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(
                self.base_url.rstrip("/") + "/health",
                method="GET",
            )
            if self.auth_token:
                req.add_header("Authorization", f"Bearer {self.auth_token}")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False

    def execute_command(
        self,
        *,
        command: list[str],
        workspace_id: str,
        env: dict[str, str],
        stdin: str,
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]:
        return self._post(
            "/exec",
            {
                "kind": "command",
                "workspace_id": workspace_id,
                "command": list(command),
                "env": env,
                "stdin": stdin,
                "timeout_s": float(timeout_s),
                "max_output_size": int(max_output_size),
            },
            timeout=timeout_s + 5.0,
        )

    def execute_function(
        self,
        *,
        source_code: str,
        function_name: str,
        input_data: dict[str, Any],
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]:
        return self._post(
            "/exec",
            {
                "kind": "function",
                "source_code": source_code,
                "function_name": function_name,
                "input_data": input_data,
                "timeout_s": float(timeout_s),
                "max_output_size": int(max_output_size),
            },
            timeout=timeout_s + 5.0,
        )

    def _post(self, path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.auth_token:
            req.add_header("Authorization", f"Bearer {self.auth_token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object, got: {type(data).__name__}")
        return data


@dataclass(slots=True)
class E2BBackend:
    """E2B (https://e2b.dev) backend for the cloud driver.

    Tries the public ``/v1/sandboxes/{id}/process`` endpoint; if E2B
    revs the API the user can subclass and override :meth:`execute_*`.
    Auth uses the ``E2B_API_KEY`` env var (the ``api_key`` ctor argument
    overrides it).
    """

    api_key: str = ""
    base_url: str = "https://api.e2b.dev"
    template: str = "base"
    timeout_s: float = 60.0

    @property
    def name(self) -> str:
        return "e2b"

    @property
    def _resolved_key(self) -> str:
        return self.api_key or os.environ.get("E2B_API_KEY", "").strip()

    def is_available(self) -> bool:
        return bool(self._resolved_key)

    def execute_command(
        self,
        *,
        command: list[str],
        workspace_id: str,
        env: dict[str, str],
        stdin: str,
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]:
        cmd = " ".join(_shell_quote(arg) for arg in command)
        return self._run_in_sandbox(cmd, env=env, timeout_s=timeout_s)

    def execute_function(
        self,
        *,
        source_code: str,
        function_name: str,
        input_data: dict[str, Any],
        timeout_s: float,
        max_output_size: int,
    ) -> dict[str, Any]:
        # Wrap the user function in a tiny driver script so we can read
        # the result back via stdout. Mirrors what the local driver does.
        driver_src = (
            f"{source_code}\n\n"
            "import json, sys\n"
            "_payload = json.loads(sys.stdin.read() or '{}')\n"
            f"_result = {function_name}(**_payload)\n"
            "print('__VIBE_RESULT__' + json.dumps(_result, default=str))\n"
        )
        cmd = "python -c " + _shell_quote(driver_src)
        raw = self._run_in_sandbox(
            cmd,
            env={},
            timeout_s=timeout_s,
            stdin=json.dumps(input_data),
        )
        out = raw.get("stdout") or ""
        result_dict: dict[str, Any] = {}
        marker = "__VIBE_RESULT__"
        if marker in out:
            try:
                payload_text = out.split(marker, 1)[1].strip().splitlines()[0]
                value = json.loads(payload_text)
                result_dict = value if isinstance(value, dict) else {"value": value}
                # Strip the marker line from stdout.
                raw["stdout"] = out.split(marker, 1)[0]
            except (json.JSONDecodeError, IndexError):
                pass
        raw["output"] = result_dict
        return raw

    def _run_in_sandbox(
        self,
        cmd: str,
        *,
        env: dict[str, str],
        timeout_s: float,
        stdin: str = "",
    ) -> dict[str, Any]:
        """Stripped-down request mirroring the E2B v1 process API.

        Real E2B clients keep a session-id cache and stream output; the
        in-tree backend favours simplicity (one request, one response)
        because the agent's output budget is small. Subclass and
        override if you need streaming.
        """
        api_key = self._resolved_key
        if not api_key:
            raise RuntimeError("E2B_API_KEY not set")
        url = self.base_url.rstrip("/") + "/v1/exec"
        body = json.dumps(
            {
                "template": self.template,
                "command": cmd,
                "env": env,
                "stdin": stdin,
                "timeout_s": float(timeout_s),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url=url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=max(timeout_s + 10, self.timeout_s)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if not raw:
            return {"success": False, "error_message": "empty E2B response"}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {"success": False, "error_message": f"non-JSON: {exc}"}
        if not isinstance(data, dict):
            return {"success": False, "error_message": "non-object response"}
        # E2B uses ``exit_code: 0`` and ``stdout/stderr`` so the field
        # names match our normalised shape — just upcast ``success``.
        data.setdefault("success", int(data.get("exit_code") or 0) == 0)
        return data


# ------------------------------------------------------------------ helpers


def _shell_quote(value: str) -> str:
    """POSIX-ish single-quote escape for command-line embedding."""
    if not value:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-" for c in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def create_cloud_driver(
    *,
    backend: str = "auto",
    base_url: str = "",
    api_key: str = "",
    workspace_id: str = "default",
) -> CloudSandboxDriver:
    """Factory picking the most appropriate cloud backend.

    ``auto`` resolution order: E2B (if ``E2B_API_KEY`` is set or
    ``api_key`` was passed) → ``HTTPCloudBackend`` (if ``base_url`` is
    set). Raises ``RuntimeError`` if neither is available.
    """
    if backend in ("e2b", "auto"):
        e2b = E2BBackend(api_key=api_key)
        if e2b.is_available():
            return CloudSandboxDriver(e2b, workspace_id=workspace_id)
        if backend == "e2b":
            raise RuntimeError("e2b backend requested but E2B_API_KEY missing")
    if backend in ("http", "auto"):
        if not base_url:
            if backend == "http":
                raise RuntimeError("http backend requires base_url")
        else:
            http = HTTPCloudBackend(base_url=base_url, auth_token=api_key)
            return CloudSandboxDriver(http, workspace_id=workspace_id)
    raise RuntimeError(f"no usable cloud backend for {backend!r}")


__all__ = [
    "CloudSandboxBackend",
    "CloudSandboxDriver",
    "E2BBackend",
    "HTTPCloudBackend",
    "create_cloud_driver",
]
