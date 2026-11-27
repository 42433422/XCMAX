"""Thin, isolated transport over the Apache-2.0 OpenAI Xiaox Python SDK.

SDK 0.171.0 owns process I/O, JSON-RPC, typed payloads and event routing. Its
public low-level client exposes an approval callback; the high-level client
currently accepts shell/file approval requests by default. We explicitly deny
those requests. Business approvals are handled by the authenticated MCP bridge.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import ipaddress
import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.infrastructure.xiaox.launcher import WindowsRuntimeJob, launch_arguments
from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES
from app.utils.operational_errors import BOUNDARY_ERRORS

CODEX_SDK_VERSION = "0.171.0"
CODEX_RUNTIME_VERSION = "0.171.0"
_PROVIDER = "xcmax_gateway"


class XiaoxTransportError(RuntimeError):
    """A stable adapter error; an unknown effect must be reconciled upstream."""

    def __init__(self, code: str, message: str, *, outcome_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown


def _endpoint(value: str, *, loopback_only: bool) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False  # Do not trust DNS aliases, even "localhost".
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and not local)
        or (loopback_only and not local)
    ):
        raise ValueError("Xiaox endpoint must use an explicit approved HTTPS or loopback URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class XiaoxTransportConfig:
    runtime_root: Path
    scope_id: str
    model: str
    provider_url: str
    provider_token: str = field(repr=False)
    mcp_url: str
    mcp_token: str = field(repr=False)
    context_window: int
    auto_compact_token_limit: int | None = None
    mcp_tools: tuple[str, ...] = XIAOX_TOOL_NAMES
    codex_bin: str | None = None
    timeout_seconds: float = 60.0
    turn_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not Path(self.runtime_root).is_absolute():
            raise ValueError("Xiaox runtime_root must be absolute")
        if any(
            not isinstance(v, str) or not v.strip() or "\0" in v
            for v in (self.scope_id, self.model, self.provider_token, self.mcp_token)
        ):
            raise ValueError("Xiaox requires an explicit scope, model and scoped credentials")
        _endpoint(self.provider_url, loopback_only=True)
        _endpoint(self.mcp_url, loopback_only=False)
        if type(self.context_window) is not int or self.context_window <= 0:
            raise ValueError("Xiaox context capacity must be supplied by the model route")
        limit = self.auto_compact_token_limit
        if limit is not None and (type(limit) is not int or not 0 < limit < self.context_window):
            raise ValueError("Xiaox compaction threshold must fit the model context")
        if not self.mcp_tools or set(self.mcp_tools) - set(XIAOX_TOOL_NAMES):
            raise ValueError("Xiaox may only expose the controlled business bridge tools")
        for value in (self.timeout_seconds, self.turn_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Xiaox timeouts must be positive and finite")


def _write_private(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".xiaox-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _deny_runtime_approval(method: str, _params: dict | None) -> dict:
    if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
        return {"decision": "decline"}
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    return {}  # No affirmative authorization for an unknown server request.


def _close_sdk_client(client: Any, job: WindowsRuntimeJob | None = None) -> None:
    # SDK 0.171.0 waits indefinitely for a reader response, and close() does not
    # wake those waiters. Release callers before terminating owned processes.
    from openai_codex.errors import TransportClosedError

    # Prevent a late to_thread worker from creating a new live request after
    # fail_all(). SDK writes fail closed once its process reference is detached.
    process, client._proc = client._proc, None
    client._router.fail_all(TransportClosedError("Xiaox transport closed"))
    client.close()
    try:
        if job is not None:
            job.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    finally:
        if process is not None:
            # A surviving pipe writer can leave a reader holding the buffered
            # stream lock. Never block close() on that lock after a timeout.
            streams = (
                (process.stdout, client._reader_thread),
                (process.stderr, client._stderr_thread),
            )
            for stream, reader in streams:
                if reader is not None and reader.is_alive():
                    reader.join(timeout=0.5)
                if stream is not None and (reader is None or not reader.is_alive()):
                    stream.close()
            # The SDK serializes every stdin write with this lock. Do not wait
            # on a blocked writer when a descendant still owns the pipe reader.
            if process.stdin is not None and client._lock.acquire(blocking=False):
                try:
                    process.stdin.close()
                finally:
                    client._lock.release()


class XiaoxTransport:
    """One scoped thread; no automatic turn retry, business replay or fallback."""

    def __init__(self, config: XiaoxTransportConfig):
        self.config = config
        scope_hash = hashlib.sha256(config.scope_id.encode()).hexdigest()
        self.runtime_dir = Path(config.runtime_root) / scope_hash
        self.workspace = self.runtime_dir / "workspace"
        self.thread_id = ""
        self.turn_id = ""
        self._client: Any = None
        self._job: WindowsRuntimeJob | None = None
        self._streaming = False
        self._scope_hash = scope_hash

    def _prepare(self) -> Path:
        for directory in (self.runtime_dir, self.workspace, self.runtime_dir / "tmp"):
            if directory.is_symlink():
                raise XiaoxTransportError(
                    "xiaox_scope_invalid", "Runtime directory is not isolated"
                )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        q = json.dumps
        cfg = self.config
        settings = [
            f"model = {q(cfg.model)}",
            f"model_provider = {q(_PROVIDER)}",
            f"model_context_window = {cfg.context_window}",
            # Keep the largest core tool contract visible without unbounding other outputs.
            "tool_output_token_limit = 4096",
            'approval_policy = "never"',
            'sandbox_mode = "read-only"',
            "project_doc_max_bytes = 0",
            'web_search = "disabled"',
            "check_for_update_on_startup = false",
            'cli_auth_credentials_store = "file"',
            'mcp_oauth_credentials_store = "file"',
            "analytics.enabled = false",
            "feedback.enabled = false",
            'otel.exporter = "none"',
            "agents.enabled = false",
            "tools.experimental_request_user_input.enabled = false",
            "tools.update_plan.enabled = false",
            "features.api_key_model_discovery = false",
            "features.api_key_cyber_access_programs = false",
            "features.shell_tool = false",
            "features.shell_snapshot = false",
            "features.unified_exec = false",
            "features.apply_patch_freeform = false",
            "features.default_mode_request_user_input = false",
            "features.goals = false",
            "features.view_image = false",
            "features.browser_use = false",
            "features.computer_use = false",
            "features.image_generation = false",
            "features.code_mode = false",
            "features.apps = false",
            "features.plugins = false",
            "features.remote_plugin = false",
            "features.hooks = false",
            "features.memories = false",
            "features.memory_tool = false",
            "features.multi_agent = false",
            "features.multi_agent_v2 = false",
            "features.request_permissions_tool = false",
            "features.skill_search = false",
            "features.skip_host_skill_discovery = true",
            "features.skill_mcp_dependency_install = false",
            "features.search_tool = false",
            "features.tool_search = false",
            "plugins._default.enabled = false",
            "skills.include_instructions = false",
            "skills.bundled.enabled = false",
            "memories.generate_memories = false",
            "memories.use_memories = false",
        ]
        if cfg.auto_compact_token_limit is not None:
            settings.append(f"model_auto_compact_token_limit = {cfg.auto_compact_token_limit}")
        settings.extend(
            [
                f"[model_providers.{_PROVIDER}]",
                'name = "XCMAX scoped gateway"',
                f"base_url = {q(_endpoint(cfg.provider_url, loopback_only=True))}",
                'env_key = "XCMAX_XIAOX_PROVIDER_KEY"',
                'wire_api = "responses"',
                "requires_openai_auth = false",
                "supports_websockets = false",
                "request_max_retries = 0",
                "stream_max_retries = 0",
                'capabilities.remote_compaction = "unsupported"',
                "capabilities.external_web_access = false",
                "[mcp_servers.xcmax]",
                f"url = {q(_endpoint(cfg.mcp_url, loopback_only=False))}",
                'bearer_token_env_var = "XCMAX_XIAOX_MCP_TOKEN"',
                "required = true",
                f"enabled_tools = {q(list(cfg.mcp_tools))}",
                "supports_parallel_tool_calls = false",
                'default_tools_approval_mode = "prompt"',
            ]
        )
        # Permit entry into the host-controlled gates. This does not approve
        # business operations: execute_action still enforces XCMAX authorization.
        for name in cfg.mcp_tools:
            settings.extend([f"[mcp_servers.xcmax.tools.{q(name)}]", 'approval_mode = "approve"'])
        _write_private(self.runtime_dir / "config.toml", "\n".join(settings) + "\n")
        return self.runtime_dir / "launch.json"

    async def __aenter__(self) -> XiaoxTransport:
        try:
            import openai_codex
            from openai_codex.client import CodexClient, CodexConfig

            if openai_codex.__version__ != CODEX_SDK_VERSION:
                raise XiaoxTransportError(
                    "xiaox_sdk_version_mismatch", "Pinned Xiaox SDK is required"
                )
            binary = self.config.codex_bin
            if binary is None:
                bundled = importlib.import_module("codex_cli_bin")
                installed_path = bundled.bundled_codex_path()
                if not isinstance(installed_path, Path):
                    raise XiaoxTransportError(
                        "xiaox_runtime_unavailable", "Pinned Xiaox runtime is unavailable"
                    )
                binary = str(installed_path)
            binary_path = Path(binary)
            if not binary_path.is_absolute() or not binary_path.is_file():
                raise XiaoxTransportError(
                    "xiaox_runtime_unavailable", "Pinned Xiaox runtime is unavailable"
                )
            plan_path = self._prepare()
            if sys.platform == "win32":
                self._job = WindowsRuntimeJob()
            _write_private(
                plan_path,
                json.dumps(
                    {
                        "binary": str(binary_path),
                        "state_dir": str(self.runtime_dir),
                        "workspace": str(self.workspace),
                        "provider_token": self.config.provider_token,
                        "mcp_token": self.config.mcp_token,
                        "job_name": self._job.name if self._job is not None else None,
                    }
                ),
            )
            sdk_config = CodexConfig(
                launch_args_override=launch_arguments(plan_path),
                cwd=str(self.workspace),
                client_name="xcmax_runtime",
                experimental_api=False,
            )
            self._client = CodexClient(sdk_config, approval_handler=_deny_runtime_approval)
            self._client.start()  # Popen only; initialize performs the blocking protocol I/O.
            metadata = await self._call(self._client.initialize)
            version = (metadata.serverInfo.version if metadata.serverInfo else "") or ""
            if not version:
                version = (metadata.userAgent or "").split("/", 1)[-1]
            if not version.split() or version.split()[0] != CODEX_RUNTIME_VERSION:
                raise XiaoxTransportError(
                    "xiaox_runtime_version_mismatch", "Pinned Xiaox runtime is required"
                )
            return self
        except ImportError:
            await self.close()
            raise XiaoxTransportError(
                "xiaox_runtime_unavailable", "Install the pinned Xiaox SDK and runtime"
            ) from None
        except (XiaoxTransportError, asyncio.CancelledError):
            await self.close()
            raise
        except BOUNDARY_ERRORS:
            await self.close()
            raise XiaoxTransportError(
                "xiaox_start_failed", "Xiaox runtime could not be started"
            ) from None
        finally:
            (self.runtime_dir / "launch.json").unlink(missing_ok=True)

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def _call(
        self,
        fn: Callable,
        *args: Any,
        outcome_unknown: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            async with asyncio.timeout(timeout or self.config.timeout_seconds):
                return await asyncio.to_thread(fn, *args, **kwargs)
        except TimeoutError:
            raise XiaoxTransportError(
                "xiaox_timeout", "Xiaox request timed out", outcome_unknown=outcome_unknown
            ) from None
        except XiaoxTransportError:
            raise
        except BOUNDARY_ERRORS as exc:
            code = (
                "xiaox_connection_lost"
                if type(exc).__name__ == "TransportClosedError"
                else "xiaox_request_failed"
            )
            raise XiaoxTransportError(
                code, "Xiaox runtime request failed", outcome_unknown=outcome_unknown
            ) from None

    def _thread_params(self, instructions: str) -> dict:
        if self._client is None or self.thread_id:
            raise XiaoxTransportError(
                "xiaox_session_invalid", "Open one thread per runtime session"
            )
        return {
            "cwd": str(self.workspace),
            "model": self.config.model,
            "modelProvider": _PROVIDER,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "developerInstructions": instructions,
        }

    def _binding(self, thread_id: str) -> dict:
        return {
            "scope": self._scope_hash,
            "thread_id": thread_id,
            "model": self.config.model,
            "provider": _PROVIDER,
            "runtime_version": CODEX_RUNTIME_VERSION,
        }

    def _validate_thread(self, result: Any) -> None:
        actual = result.model_dump(
            by_alias=True,
            mode="json",
            include={
                "model_provider",
                "model",
                "cwd",
                "approval_policy",
                "sandbox",
                "instruction_sources",
            },
        )
        if (
            actual.get("modelProvider") != _PROVIDER
            or actual.get("model") != self.config.model
            or actual.get("cwd") != str(self.workspace)
            or actual.get("approvalPolicy") != "never"
            or actual.get("sandbox", {}).get("type") != "readOnly"
            or actual.get("instructionSources")
            or not result.thread.id
        ):
            raise XiaoxTransportError(
                "xiaox_policy_mismatch", "Runtime did not retain the scoped policy"
            )

    async def start_thread(
        self, *, developer_instructions: str = "", history: list[dict[str, str]] | None = None
    ) -> str:
        params = self._thread_params(developer_instructions)
        if (self.runtime_dir / "binding.json").exists():
            raise XiaoxTransportError(
                "xiaox_resume_required", "Existing runtime scope must be resumed"
            )
        result = await self._call(self._client.thread_start, params)
        self._validate_thread(result)
        if history:
            from openai_codex.generated.v2_all import (
                ThreadInjectItemsParams,
                ThreadInjectItemsResponse,
            )

            items = [
                {
                    "type": "message",
                    "role": row["role"],
                    "content": [
                        {
                            "type": "input_text" if row["role"] == "user" else "output_text",
                            "text": row["content"],
                        }
                    ],
                }
                for row in history
                if row["role"] in {"user", "assistant"}
            ]
            await self._call(
                self._client.request,
                "thread/inject_items",
                ThreadInjectItemsParams(thread_id=result.thread.id, items=items).model_dump(
                    by_alias=True
                ),
                response_model=ThreadInjectItemsResponse,
            )
        self.thread_id = result.thread.id
        _write_private(self.runtime_dir / "binding.json", json.dumps(self._binding(self.thread_id)))
        return self.thread_id

    async def resume_thread(self, thread_id: str, *, developer_instructions: str = "") -> str:
        params = self._thread_params(developer_instructions)
        try:
            binding = json.loads((self.runtime_dir / "binding.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            binding = None
        if binding != self._binding(thread_id):
            raise XiaoxTransportError(
                "xiaox_scope_mismatch", "Thread is not bound to this runtime scope"
            )
        result = await self._call(
            self._client.thread_resume, thread_id, {**params, "excludeTurns": True}
        )
        self._validate_thread(result)
        if result.thread.id != thread_id:
            raise XiaoxTransportError("xiaox_scope_mismatch", "Runtime returned a different thread")
        self.thread_id = thread_id
        return thread_id

    async def stream_turn(
        self,
        text: str | None,
        *,
        goal_feedback: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if (text is None) == (goal_feedback is None):
            raise ValueError("Supply either user text or host goal feedback")
        if self._client is None or not self.thread_id or self._streaming:
            raise XiaoxTransportError(
                "xiaox_session_invalid", "Runtime requires one active scoped thread"
            )
        self._streaming = True
        completed = False
        client = self._client
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                if goal_feedback is None:
                    from openai_codex.generated.v2_all import TurnStartParams

                    params = (
                        TurnStartParams(
                            thread_id=self.thread_id, input=[], output_schema=output_schema
                        )
                        if output_schema
                        else None
                    )
                    start_options: dict[str, Any] = {"params": params} if params else {}
                    result = await self._call(
                        client.turn_start,
                        self.thread_id,
                        text,
                        **start_options,
                        outcome_unknown=True,
                    )
                else:
                    from openai_codex.generated.v2_all import (
                        FunctionCallOutputBody,
                        TurnStartParams,
                        TurnToolOutput,
                    )

                    # Same tool-level input as SDK ExternalMessage, with our low-level
                    # client's deny-by-default approval handler still in place.
                    params = TurnStartParams(
                        thread_id=self.thread_id,
                        input=[],
                        tool_output=TurnToolOutput(
                            name="verify_runtime_goal",
                            output=FunctionCallOutputBody(root=goal_feedback),
                            retain=False,
                        ),
                        output_schema=output_schema or None,
                    )
                    result = await self._call(
                        client.turn_start, self.thread_id, [], params, outcome_unknown=True
                    )
                self.turn_id = result.turn.id
                yield {
                    "method": "turn/started",
                    "thread_id": self.thread_id,
                    "turn_id": self.turn_id,
                    "payload": {
                        "threadId": self.thread_id,
                        "turn": result.turn.model_dump(
                            by_alias=True, mode="json", exclude_unset=True
                        ),
                    },
                }
                while True:
                    # A notification wait covers real model latency; the turn budget
                    # below is the only ceiling. A short per-call limit would turn a
                    # slow model into an unsettled (unknown) business outcome.
                    notice = await self._call(
                        client.next_turn_notification,
                        self.turn_id,
                        outcome_unknown=True,
                        timeout=self.config.turn_timeout_seconds,
                    )
                    payload = notice.payload
                    if hasattr(payload, "model_dump"):
                        payload = payload.model_dump(by_alias=True, mode="json", exclude_unset=True)
                    else:
                        payload = dict(payload.params)
                    if payload.get("threadId", self.thread_id) != self.thread_id:
                        raise XiaoxTransportError(
                            "xiaox_scope_mismatch",
                            "Runtime event belongs to a different thread",
                            outcome_unknown=True,
                        )
                    if notice.method == "turn/started":
                        continue
                    event = {
                        "method": notice.method,
                        "thread_id": self.thread_id,
                        "turn_id": self.turn_id,
                        "payload": payload,
                    }
                    if isinstance(payload.get("item"), dict):
                        event["item_id"] = payload["item"].get("id")
                    if notice.method == "turn/completed":
                        turn = payload.get("turn", {})
                        if turn.get("id") != self.turn_id or turn.get("status") not in {
                            "completed",
                            "failed",
                            "interrupted",
                        }:
                            raise XiaoxTransportError(
                                "xiaox_invalid_event",
                                "Runtime completion is invalid",
                                outcome_unknown=True,
                            )
                        completed = True
                    yield event
                    if completed:
                        break
        except TimeoutError:
            raise XiaoxTransportError(
                "xiaox_timeout", "Xiaox turn timed out", outcome_unknown=True
            ) from None
        finally:
            if self.turn_id:
                client.unregister_turn_notifications(self.turn_id)
            self._streaming = False
            if not completed:
                await self.close()
            self.turn_id = ""

    async def interrupt(self) -> None:
        if self._client is not None and self.turn_id:
            await self._call(
                self._client.turn_interrupt, self.thread_id, self.turn_id, outcome_unknown=True
            )

    @property
    def process_id(self) -> int | None:
        process = getattr(self._client, "_proc", None)
        return process.pid if process is not None and process.poll() is None else None

    async def compact_thread(self) -> dict[str, str]:
        """Force SDK-owned compaction and observe completion, not merely its ACK."""
        if self._client is None or not self.thread_id or self._streaming:
            raise XiaoxTransportError("xiaox_session_invalid", "No idle scoped thread")
        self._streaming = True
        compact_turn = ""
        client = self._client
        completed = False
        # 0.171 routes every turn-scoped notice away from next_notification().
        # Its thread subscription API captures the server-generated compact
        # turn before we know its id. This registers only a local SDK route;
        # it sends no goal RPC and enables no autonomous goal feature.
        subscription = client.register_goal_operation(self.thread_id)
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                await self._call(client.thread_compact, self.thread_id)
                while True:
                    notice = await self._call(
                        client.next_goal_notification,
                        subscription,
                        timeout=self.config.turn_timeout_seconds,
                    )
                    payload = notice.payload
                    if hasattr(payload, "model_dump"):
                        payload = payload.model_dump(by_alias=True, mode="json")
                    else:
                        payload = dict(payload.params)
                    if payload.get("threadId") != self.thread_id:
                        continue
                    if (
                        notice.method == "item/completed"
                        and payload.get("item", {}).get("type") == "contextCompaction"
                    ):
                        compact_turn = payload.get("turnId", "")
                    if notice.method == "turn/completed":
                        turn = payload.get("turn", {})
                        if turn.get("status") != "completed":
                            raise XiaoxTransportError(
                                "xiaox_compaction_failed", "Runtime compaction did not complete"
                            )
                        if compact_turn and turn.get("id") == compact_turn:
                            completed = True
                            return {"thread_id": self.thread_id, "turn_id": compact_turn}
        except TimeoutError:
            raise XiaoxTransportError(
                "xiaox_timeout", "Runtime compaction completion was not observed"
            ) from None
        finally:
            self._streaming = False
            if not completed:
                await self.close()  # Wake the SDK subscriber before removing its route.
            client.unregister_goal_operation(subscription)

    async def close(self) -> None:
        client, self._client = self._client, None
        job, self._job = self._job, None
        if client is not None:
            await asyncio.to_thread(_close_sdk_client, client, job)
        elif job is not None:
            job.close()
        (self.runtime_dir / "launch.json").unlink(missing_ok=True)


def verify_packaged_runtime() -> None:
    """Launch and initialize the real CLI without requesting any model response.

    Run through the same isolated launcher as production, including the frozen
    executable branch. This proves packaging/protocol startup, not provider or
    business qualification; it cannot write a qualification receipt.
    """
    with tempfile.TemporaryDirectory(prefix="xcagi-xiaox-probe-") as temporary:
        config = XiaoxTransportConfig(
            runtime_root=Path(temporary).resolve(),
            scope_id="packaged-protocol-probe",
            model="packaging-probe-no-model-call",
            provider_url="http://127.0.0.1:1/v1",
            provider_token=secrets.token_urlsafe(32),
            mcp_url="http://127.0.0.1:1/mcp",
            mcp_token=secrets.token_urlsafe(32),
            context_window=32768,
            timeout_seconds=15,
        )

        async def initialize() -> None:
            runtime = XiaoxTransport(config)
            try:
                async with runtime:
                    pass
            finally:
                diagnostic = runtime.runtime_dir / "launcher-status.json"
                if diagnostic.is_file():
                    print(
                        "[frozen-runtime-probe] launcher " + diagnostic.read_text(encoding="utf-8"),
                        file=sys.stderr,
                        flush=True,
                    )

        asyncio.run(initialize())
    print(f"[frozen-runtime-probe] Xiaox SDK/CLI {CODEX_RUNTIME_VERSION} initialize OK")
