"""Run-scoped lifetimes for the official MCP SDK; no browser or task engine.

The task that enters the SDK contexts also uses and exits them. Losing a
connection retains a tombstone until its owning run is released, so a retry
cannot silently operate a fresh browser. Durable callers retain ``session_id``
in their existing step receipts to detect a worker restart.
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import math
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from app.application.tool_execution_deadline import remaining_invocation_seconds
from app.infrastructure.mcp.config import McpServerConfig
from app.utils.operational_errors import BOUNDARY_ERRORS

if TYPE_CHECKING:
    from anyio import CancelScope

Operation = Callable[[Any], Awaitable[Any]]
Connection = Callable[[McpServerConfig, Operation], Awaitable[Any]]
_MAX_SESSIONS = 32
_MAX_PENDING = 16
_LOCK = threading.Lock()
_SESSIONS: dict[tuple[str, str], _Session] = {}


class McpSessionError(RuntimeError):
    def __init__(self, code: str, session_id: str = "") -> None:
        super().__init__(code)
        self.code, self.session_id = code, session_id


def _fingerprint(config: McpServerConfig) -> str:
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()


class _Session:
    def __init__(self, config: McpServerConfig, connection: Connection) -> None:
        self.config, self.connection = config, connection
        self.fingerprint = _fingerprint(config)
        self.session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._lost = False
        self._pending: set[Future[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel_scope: CancelScope | None = None
        self._queue: asyncio.Queue[tuple[Operation, Future[Any], float]] | None = None
        self._thread = threading.Thread(target=self._run, name="mcp-session", daemon=True)
        self._thread.start()

    def lose(self) -> None:
        with self._lock:
            self._lost = True
            for future in tuple(self._pending):
                if not future.done():
                    future.set_exception(McpSessionError("mcp_session_lost", self.session_id))
            self._pending.clear()

    def close(self) -> None:
        self.lose()
        loop, scope = self._loop, self._cancel_scope
        if loop is not None and scope is not None:
            try:
                # Respect the official SDK's shielded process/transport cleanup.
                loop.call_soon_threadsafe(scope.cancel)
            except RuntimeError:  # The owner already finished and closed its loop.
                pass

    def wait_closed(self, timeout: float) -> None:
        self._closed.wait(timeout=max(0.0, timeout))

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        finally:
            self.lose()
            self._ready.set()
            self._closed.set()

    async def _serve(self) -> None:
        from anyio import CancelScope

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        try:
            with CancelScope() as scope:
                self._cancel_scope = scope
                self._ready.set()
                if not self._lost:
                    await self.connection(self.config, self._consume)
        except asyncio.CancelledError:
            pass
        except BOUNDARY_ERRORS:  # Isolate SDK/transport failure; never log credentials or args.
            pass

    async def _consume(self, session: Any) -> None:
        from anyio import fail_after

        assert self._queue is not None
        while not self._lost:
            with fail_after(self.config.session_idle_seconds):
                operation, future, deadline = await self._queue.get()
            if self._lost:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpSessionError("mcp_session_lost", self.session_id)
            with fail_after(remaining):
                result = await operation(session)
            with self._lock:
                if not future.done():
                    future.set_result(result)
                self._pending.discard(future)

    def call(self, operation: Operation, deadline: float) -> Any:
        if not self._ready.wait(timeout=max(0.0, deadline - time.monotonic())):
            self.close()
            raise McpSessionError("mcp_session_lost", self.session_id)
        future: Future[Any] = Future()
        with self._lock:
            if self._lost:
                raise McpSessionError("mcp_session_lost", self.session_id)
            if len(self._pending) >= _MAX_PENDING:
                raise McpSessionError("mcp_session_busy", self.session_id)
            self._pending.add(future)
        try:
            assert self._loop is not None and self._queue is not None
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (operation, future, deadline))
            result = future.result(timeout=max(0.0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                raise FutureTimeout
            return result
        except (FutureTimeout, RuntimeError):
            self.close()
            raise McpSessionError("mcp_session_lost", self.session_id) from None


def call_persistent(
    config: McpServerConfig,
    scope: str | None,
    tool_name: str,
    operation: Operation,
    connection: Connection,
    *,
    expected_session_id: str | None = None,
) -> tuple[Any, str]:
    if not isinstance(scope, str) or not scope.strip() or len(scope) > 512:
        raise McpSessionError("mcp_session_scope_required")
    # The owning SDK task has a different ContextVar scope. Carry the caller's
    # absolute deadline through startup, queueing and execution without changing
    # the session's stable configuration fingerprint or reconnecting it.
    timeout = remaining_invocation_seconds(config.timeout_seconds)
    if timeout <= 0 or not math.isfinite(timeout):
        raise McpSessionError("mcp_session_deadline_exceeded")
    deadline = time.monotonic() + timeout
    key = (config.name, scope)
    with _LOCK:
        session = _SESSIONS.get(key)
        if expected_session_id is not None and (
            session is None or session.session_id != expected_session_id
        ):
            raise McpSessionError("mcp_session_lost", expected_session_id)
        if session is None:
            if tool_name not in config.session_start_tools:
                raise McpSessionError("mcp_session_not_started")
            count = sum(server == config.name for server, _scope in _SESSIONS)
            if count >= config.max_sessions or len(_SESSIONS) >= _MAX_SESSIONS:
                raise McpSessionError("mcp_session_limit")
            session = _Session(config, connection)
            _SESSIONS[key] = session
        elif session.fingerprint != _fingerprint(config):
            session.close()
            raise McpSessionError("mcp_session_lost", session.session_id)
    return session.call(operation, deadline), session.session_id


def close_scope(scope: str, *, server_name: str | None = None) -> int:
    """Release only the caller's authenticated run; wait briefly for SDK cleanup."""
    with _LOCK:
        keys = [key for key in _SESSIONS if key[1] == scope and server_name in (None, key[0])]
        sessions = [_SESSIONS.pop(key) for key in keys]
    _close(sessions)
    return len(sessions)


def _close(sessions: list[_Session]) -> None:
    for session in sessions:
        session.close()
    deadline = time.monotonic() + 5.0
    for session in sessions:
        session.wait_closed(deadline - time.monotonic())


def close_all_sessions() -> None:
    with _LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    _close(sessions)


atexit.register(close_all_sessions)
