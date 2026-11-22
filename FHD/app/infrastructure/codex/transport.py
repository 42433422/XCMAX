"""Thin, isolated transport over the Apache-2.0 OpenAI Codex Python SDK.

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
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.infrastructure.codex.launcher import launch_arguments
from app.utils.operational_errors import BOUNDARY_ERRORS

CODEX_SDK_VERSION = "0.171.0"
CODEX_RUNTIME_VERSION = "0.171.0"
_PROVIDER = "xcmax_gateway"
_MCP_TOOLS = (
    "capability_search",
    "capability_describe",
    "execute_action",
    "execute_plan",
    "task_evidence",
    "request_input",
)


class CodexTransportError(RuntimeError):
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
        raise ValueError("Codex endpoint must use an explicit approved HTTPS or loopback URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class CodexTransportConfig:
    runtime_root: Path
    scope_id: str
    model: str
    provider_url: str
    provider_token: str = field(repr=False)
    mcp_url: str
    mcp_token: str = field(repr=False)
    context_window: int
    auto_compact_token_limit: int | None = None
    mcp_tools: tuple[str, ...] = _MCP_TOOLS
    codex_bin: str | None = None
    timeout_seconds: float = 120.0
    turn_timeout_seconds: float = 900.0

    def __post_init__(self) -> None:
        if not Path(self.runtime_root).is_absolute():
            raise ValueError("Codex runtime_root must be absolute")
        if any(
            not isinstance(v, str) or not v.strip() or "\0" in v
            for v in (self.scope_id, self.model, self.provider_token, self.mcp_token)
        ):
            raise ValueError("Codex requires an explicit scope, model and scoped credentials")
        _endpoint(self.provider_url, loopback_only=True)
        _endpoint(self.mcp_url, loopback_only=False)
        if type(self.context_window) is not int or self.context_window <= 0:
            raise ValueError("Codex context capacity must be supplied by the model route")
        limit = self.auto_compact_token_limit
        if limit is not None and (type(limit) is not int or not 0 < limit < self.context_window):
            raise ValueError("Codex compaction threshold must fit the model context")
        if not self.mcp_tools or set(self.mcp_tools) - set(_MCP_TOOLS):
            raise ValueError("Codex may only expose the controlled business bridge tools")
        for value in (self.timeout_seconds, self.turn_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Codex timeouts must be positive and finite")


def _write_private(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".codex-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
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


def _close_sdk_client(client: Any) -> None:
    # 0.171.0 leaves stdout/stderr open after close(). Keep this version-bound
    # resource shim until upstream closes all pipes; do not suppress warnings.
    process = client._proc
    try:
        client.close()
    finally:
        if process is not None:
            process.wait(timeout=3)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


class CodexTransport:
    """One scoped thread; no automatic turn retry, business replay or fallback."""

    def __init__(self, config: CodexTransportConfig):
        self.config = config
        scope_hash = hashlib.sha256(config.scope_id.encode()).hexdigest()
        self.runtime_dir = Path(config.runtime_root) / scope_hash
        self.workspace = self.runtime_dir / "workspace"
        self.thread_id = ""
        self.turn_id = ""
        self._client: Any = None
        self._streaming = False
        self._scope_hash = scope_hash

    def _prepare(self) -> Path:
        for directory in (self.runtime_dir, self.workspace, self.runtime_dir / "tmp"):
            if directory.is_symlink():
                raise CodexTransportError(
                    "codex_scope_invalid", "Runtime directory is not isolated"
                )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        q = json.dumps
        cfg = self.config
        settings = [
            f"model = {q(cfg.model)}",
            f"model_provider = {q(_PROVIDER)}",
            f"model_context_window = {cfg.context_window}",
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
                'env_key = "XCMAX_CODEX_PROVIDER_KEY"',
                'wire_api = "responses"',
                "requires_openai_auth = false",
                "supports_websockets = false",
                "request_max_retries = 0",
                "stream_max_retries = 0",
                'capabilities.remote_compaction = "unsupported"',
                "capabilities.external_web_access = false",
                "[mcp_servers.xcmax]",
                f"url = {q(_endpoint(cfg.mcp_url, loopback_only=False))}",
                'bearer_token_env_var = "XCMAX_CODEX_MCP_TOKEN"',
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

    async def __aenter__(self) -> CodexTransport:
        try:
            import openai_codex
            from openai_codex.client import CodexClient, CodexConfig

            if openai_codex.__version__ != CODEX_SDK_VERSION:
                raise CodexTransportError(
                    "codex_sdk_version_mismatch", "Pinned Codex SDK is required"
                )
            binary = self.config.codex_bin
            if binary is None:
                bundled = importlib.import_module("codex_cli_bin")
                installed_path = bundled.bundled_codex_path()
                if not isinstance(installed_path, Path):
                    raise CodexTransportError(
                        "codex_runtime_unavailable", "Pinned Codex runtime is unavailable"
                    )
                binary = str(installed_path)
            binary_path = Path(binary)
            if not binary_path.is_absolute() or not binary_path.is_file():
                raise CodexTransportError(
                    "codex_runtime_unavailable", "Pinned Codex runtime is unavailable"
                )
            plan_path = self._prepare()
            _write_private(
                plan_path,
                json.dumps(
                    {
                        "binary": str(binary_path),
                        "state_dir": str(self.runtime_dir),
                        "workspace": str(self.workspace),
                        "provider_token": self.config.provider_token,
                        "mcp_token": self.config.mcp_token,
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
                raise CodexTransportError(
                    "codex_runtime_version_mismatch", "Pinned Codex runtime is required"
                )
            return self
        except ImportError:
            await self.close()
            raise CodexTransportError(
                "codex_runtime_unavailable", "Install the pinned Codex SDK and runtime"
            ) from None
        except (CodexTransportError, asyncio.CancelledError):
            await self.close()
            raise
        except BOUNDARY_ERRORS:
            await self.close()
            raise CodexTransportError(
                "codex_start_failed", "Codex runtime could not be started"
            ) from None
        finally:
            (self.runtime_dir / "launch.json").unlink(missing_ok=True)

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def _call(
        self, fn: Callable, *args: Any, outcome_unknown: bool = False, **kwargs: Any
    ) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs), self.config.timeout_seconds
            )
        except TimeoutError:
            raise CodexTransportError(
                "codex_timeout", "Codex request timed out", outcome_unknown=outcome_unknown
            ) from None
        except CodexTransportError:
            raise
        except BOUNDARY_ERRORS as exc:
            code = (
                "codex_connection_lost"
                if type(exc).__name__ == "TransportClosedError"
                else "codex_request_failed"
            )
            raise CodexTransportError(
                code, "Codex runtime request failed", outcome_unknown=outcome_unknown
            ) from None

    def _thread_params(self, instructions: str) -> dict:
        if self._client is None or self.thread_id:
            raise CodexTransportError(
                "codex_session_invalid", "Open one thread per runtime session"
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
            raise CodexTransportError(
                "codex_policy_mismatch", "Runtime did not retain the scoped policy"
            )

    async def start_thread(self, *, developer_instructions: str = "") -> str:
        params = self._thread_params(developer_instructions)
        if (self.runtime_dir / "binding.json").exists():
            raise CodexTransportError(
                "codex_resume_required", "Existing runtime scope must be resumed"
            )
        result = await self._call(self._client.thread_start, params)
        self._validate_thread(result)
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
            raise CodexTransportError(
                "codex_scope_mismatch", "Thread is not bound to this runtime scope"
            )
        result = await self._call(
            self._client.thread_resume, thread_id, {**params, "excludeTurns": True}
        )
        self._validate_thread(result)
        if result.thread.id != thread_id:
            raise CodexTransportError("codex_scope_mismatch", "Runtime returned a different thread")
        self.thread_id = thread_id
        return thread_id

    async def stream_turn(self, text: str) -> AsyncIterator[dict[str, Any]]:
        if self._client is None or not self.thread_id or self._streaming:
            raise CodexTransportError(
                "codex_session_invalid", "Runtime requires one active scoped thread"
            )
        self._streaming = True
        completed = False
        client = self._client
        try:
            async with asyncio.timeout(self.config.turn_timeout_seconds):
                result = await self._call(
                    client.turn_start, self.thread_id, text, outcome_unknown=True
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
                    notice = await self._call(
                        client.next_turn_notification, self.turn_id, outcome_unknown=True
                    )
                    payload = notice.payload
                    if hasattr(payload, "model_dump"):
                        payload = payload.model_dump(by_alias=True, mode="json", exclude_unset=True)
                    else:
                        payload = dict(payload.params)
                    if payload.get("threadId", self.thread_id) != self.thread_id:
                        raise CodexTransportError(
                            "codex_scope_mismatch",
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
                            raise CodexTransportError(
                                "codex_invalid_event",
                                "Runtime completion is invalid",
                                outcome_unknown=True,
                            )
                        completed = True
                    yield event
                    if completed:
                        break
        except TimeoutError:
            raise CodexTransportError(
                "codex_timeout", "Codex turn timed out", outcome_unknown=True
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

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await asyncio.to_thread(_close_sdk_client, client)
        (self.runtime_dir / "launch.json").unlink(missing_ok=True)


def verify_packaged_runtime() -> None:
    """Launch and initialize the real CLI without requesting any model response.

    Run through the same isolated launcher as production, including the frozen
    executable branch. This proves packaging/protocol startup, not provider or
    business qualification; it cannot write a qualification receipt.
    """
    with tempfile.TemporaryDirectory(prefix="xcagi-codex-probe-") as temporary:
        # Probe credentials are ephemeral. No fixed token is shipped in source.
        probe_nonce = os.urandom(24).hex()
        config = CodexTransportConfig(
            runtime_root=Path(temporary).resolve(),
            scope_id="packaged-protocol-probe",
            model="packaging-probe-no-model-call",
            provider_url="http://127.0.0.1:1/v1",
            provider_token=probe_nonce,
            mcp_url="http://127.0.0.1:1/mcp",
            mcp_token=probe_nonce,
            context_window=32768,
            timeout_seconds=15,
        )

        async def initialize() -> None:
            async with CodexTransport(config):
                pass

        asyncio.run(initialize())
    print(f"[frozen-runtime-probe] Codex SDK/CLI {CODEX_RUNTIME_VERSION} initialize OK")
