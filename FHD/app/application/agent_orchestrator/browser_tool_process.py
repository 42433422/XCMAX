"""Retain the existing isolated tool worker for one authenticated browser run.

Each command still executes the original worker's authorization, invocation
deadline, JSON receipt and stream boundary. Only the owned process lifetime
changes; a lost worker is never silently recreated for an old session receipt.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import multiprocessing
import shutil
import tempfile
import threading
import time
from contextvars import copy_context
from dataclasses import asdict
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any

import psutil

from app.application.agent_orchestrator import tool_process as boundary
from app.infrastructure.mcp.config import McpServerConfig
from app.utils.operational_errors import BOUNDARY_ERRORS

_LOCK = threading.Lock()
_WORKERS: dict[tuple[str, str], _BrowserWorker] = {}
_PAYLOAD_LIMIT = 8 * 1024 * 1024


def _failure(code: str, *, unknown: bool = True) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": code,
        "retryable": False,
        "outcome": "unknown" if unknown else "not_started",
        "reconciliation_required": unknown,
    }


def _worker_loop(executor_type, folder, commands, control, start, stream, scope, tool_id):
    from app.application.tools.mcp.registry import mcp_session_scope

    first = True
    try:
        while True:
            raw = commands.recv_bytes(_PAYLOAD_LIMIT)
            request = json.loads(raw)
            payload = json.loads(request["payload"])
            if (mcp_session_scope(payload["context"]), payload["step"]["tool_id"]) != (
                scope,
                tool_id,
            ):
                raise ValueError("browser worker scope changed")
            start.clear()
            boundary._worker(
                executor_type,
                request["payload"],
                folder,
                control,
                start,
                request["deadline"],
                request["llm_scope"],
                stream_connection=stream,
                initialize=first,
                retain=True,
                browser=True,
            )
            first = False
    except BOUNDARY_ERRORS:
        try:
            control.send_bytes(b"x")
        except OSError:
            pass
    finally:
        # Retain ancestry even after a protocol failure until the parent reaps it.
        start.clear()
        start.wait()


class _BrowserWorker:
    def __init__(self, executor, config, scope, tool_id, fingerprint):
        self.executor, self.config = executor, config
        self.fingerprint = fingerprint
        self.lock, self.cleanup_lock = threading.Lock(), threading.Lock()
        self.lost = False
        self.clean: bool | None = None
        self.stopped = threading.Event()
        self.sender: threading.Thread | None = None
        self.expires_at = time.monotonic() + config.session_idle_seconds
        self.failure_code = "mcp_session_lost"
        self.folder = tempfile.mkdtemp(prefix="xcagi-browser-tool-")
        self.memory_limit = boundary._limit_from_env("XCAGI_BROWSER_MEMORY_MB", 4096) * 1024 * 1024
        ctx = multiprocessing.get_context("spawn")
        self.start = ctx.Event()
        commands, self.commands = ctx.Pipe(duplex=False)
        self.control, control = ctx.Pipe(duplex=False)
        self.stream, stream = ctx.Pipe(duplex=False)
        self.process = ctx.Process(
            target=_worker_loop,
            args=(
                type(executor),
                self.folder,
                commands,
                control,
                self.start,
                stream,
                scope,
                tool_id,
            ),
        )
        try:
            self.process.start()
            threading.Thread(target=self._watchdog, daemon=True, name="browser-watchdog").start()
        except BOUNDARY_ERRORS:
            self.close()
            raise
        finally:
            commands.close()
            control.close()
            stream.close()

    def close(self) -> bool:
        with self.cleanup_lock:
            self.lost = True
            self.stopped.set()
            if self.clean is not None:
                return self.clean
            clean = True
            if self.process.pid is not None:
                try:
                    clean = boundary._reap(self.process)
                    if clean:
                        self.process.close()
                except (OSError, ValueError):
                    clean = False
            for connection in (self.commands, self.control, self.stream):
                connection.close()
            if self.sender is not None and self.sender.ident is not None:
                self.sender.join(timeout=1)
                clean = clean and not self.sender.is_alive()
            if clean:
                try:
                    shutil.rmtree(self.folder, onerror=boundary._ignore_missing_cleanup_entry)
                except OSError:
                    clean = False
            self.clean = clean
            if not clean:
                self.executor._tool_cleanup_failed = True
            return clean

    def _watchdog(self) -> None:
        while not self.stopped.wait(0.2):
            try:
                if not self._memory_ok():
                    self.failure_code = "tool_browser_memory_exceeded"
                elif self.lock.acquire(blocking=False):
                    try:
                        if time.monotonic() < self.expires_at:
                            continue
                        self.close()
                    finally:
                        self.lock.release()
                    return
                else:
                    continue
            except (psutil.Error, OSError, ValueError):
                if self.stopped.is_set():
                    return
                self.failure_code = "tool_browser_resources_unverified"
            self.close()
            return

    def _memory_ok(self) -> bool:
        root = psutil.Process(self.process.pid)
        total = 0
        for process in [root, *root.children(recursive=True)]:
            try:
                total += process.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return bool(total <= self.memory_limit)

    def _wait(self, marker: bytes, deadline: float) -> None:
        while not self.lost and time.monotonic() < deadline:
            ready = wait(
                (self.control, self.process.sentinel),
                timeout=max(0, min(0.2, deadline - time.monotonic())),
            )
            if not self._memory_ok():
                raise MemoryError("browser worker memory limit")
            if self.control in ready:
                if self.control.recv_bytes(1) == marker:
                    return
                raise RuntimeError("browser worker receipt invalid")
            if self.process.sentinel in ready:
                break
        raise TimeoutError("browser worker deadline or lifetime ended")

    def _send_request(self, payload: bytes, deadline: float) -> None:
        """Bound pipe backpressure by the action deadline; never spool credentials."""
        sent, failed = threading.Event(), threading.Event()

        def send() -> None:
            try:
                self.commands.send_bytes(payload)
            except BOUNDARY_ERRORS:
                failed.set()
            finally:
                sent.set()

        sender = threading.Thread(target=send, daemon=True, name="browser-tool-send")
        with self.cleanup_lock:
            if self.lost:
                raise RuntimeError("browser worker lifetime ended")
            self.sender = sender
            sender.start()
        if not sent.wait(max(0, deadline - time.monotonic())):
            raise TimeoutError("browser worker request deadline")
        sender.join(timeout=max(0, deadline - time.monotonic()))
        if sender.is_alive():
            raise TimeoutError("browser worker sender deadline")
        if failed.is_set():
            raise OSError("browser worker request transport failed")

    def call(self, step, context, deadline, business_url) -> dict[str, Any]:
        from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime
        from app.infrastructure.llm.client import (
            capture_worker_llm_scope,
            record_worker_route_metadata,
        )

        if not self.lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return _failure("mcp_session_busy", unknown=False)
        stopped, drained, failed = (threading.Event() for _ in range(3))
        relay = None
        try:
            if self.lost:
                clean = self.close()  # A watchdog may still be reaping the owned tree.
                return _failure(self.failure_code if clean else "tool_cleanup_unresolved")
            llm_scope = capture_worker_llm_scope(context)
            payload = json.dumps(
                {
                    "step": step.to_dict(),
                    "context": context,
                    "business_db_url": business_url,
                },
                allow_nan=False,
            )
            request = json.dumps(
                {"payload": payload, "deadline": deadline, "llm_scope": llm_scope}, allow_nan=False
            ).encode("utf-8")
            if len(request) > _PAYLOAD_LIMIT:
                return _failure("tool_context_not_serializable", unknown=False)
            Path(self.folder, "result").unlink(missing_ok=True)
            lifetime = current_lifetime.get() or StreamLifetime()
            lifetime.worker_started()
            relay = threading.Thread(
                target=copy_context().run,
                args=(boundary._relay_stream, self.stream, lifetime, drained, failed, stopped),
                kwargs={"keep_connection": True},
                daemon=True,
                name="browser-tool-stream",
            )
            try:
                relay.start()
            except RuntimeError:
                lifetime.worker_finished()
                raise
            self.start.clear()
            self._send_request(request, deadline)
            self._wait(b"r", deadline)
            self.start.set()
            self._wait(b"d", deadline)
            raw = Path(self.folder, "result").read_bytes()
            if len(raw) > _PAYLOAD_LIMIT:
                raise ValueError("browser worker result exceeds transport limit")
            result = json.loads(raw)
            while not drained.wait(max(0, min(0.2, deadline - time.monotonic()))):
                if time.monotonic() >= deadline or not self._memory_ok():
                    raise TimeoutError("browser worker stream deadline")
            if failed.is_set():
                raise RuntimeError("browser worker stream receipt failed")
            record_worker_route_metadata(result.get("llm_route_metadata"), llm_scope)
            from app.application.tool_execution_deadline import invocation_deadline

            with invocation_deadline(deadline) as budget:
                budget.uncertain.extend(result["uncertain"])
            output = result["output"]
            if not isinstance(output, dict):
                raise ValueError("invalid browser tool result")
            if output.get("outcome") == "unknown" or output.get("error_code") == "mcp_session_lost":
                self.close()
            return output if self.clean is not False else _failure("tool_cleanup_unresolved")
        except BOUNDARY_ERRORS as exc:
            self.close()
            code = (
                "tool_browser_memory_exceeded"
                if isinstance(exc, MemoryError)
                else self.failure_code
            )
            return _failure(code if self.clean else "tool_cleanup_unresolved")
        finally:
            stopped.set()
            Path(self.folder, "result").unlink(missing_ok=True)
            self.expires_at = time.monotonic() + self.config.session_idle_seconds
            self.lock.release()


def execute_browser_isolated(
    executor, step, context, deadline: float, config: McpServerConfig
) -> dict[str, Any]:
    from app.application.tools.mcp.registry import mcp_session_scope

    if getattr(executor, "_tool_cleanup_failed", False):
        return _failure("tool_cleanup_unresolved")
    if not boundary._process_namespace_matches():
        return _failure("tool_process_namespace_unverified", unknown=False)
    scope = mcp_session_scope(context)
    if not scope:
        return _failure("mcp_session_scope_required", unknown=False)
    from app.db import HostSessionLocal

    try:
        business_url = boundary._caller_business_db_url()
        with HostSessionLocal() as db:
            host_url = db.get_bind().url.render_as_string(hide_password=False)
        identity = [
            asdict(config),
            context.get("_actor_authorization"),
            context.get("_mod_authorization"),
            host_url,
            business_url,
        ]
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    except BOUNDARY_ERRORS:
        return _failure("tool_scope_unavailable", unknown=False)
    key = (config.name, scope)
    with _LOCK:
        worker = _WORKERS.get(key)
        if worker is None:
            outputs = context.get("node_outputs")
            if any(
                isinstance(value, dict)
                and value.get("server") == config.name
                and value.get("session_id")
                for value in (outputs.values() if isinstance(outputs, dict) else [])
            ):
                return _failure("mcp_session_lost")
            if step.action not in config.session_start_tools:
                return _failure("mcp_session_not_started", unknown=False)
            if (
                sum(
                    server == config.name and row.clean is not True
                    for (server, _), row in _WORKERS.items()
                )
                >= config.max_sessions
                or sum(row.clean is not True for row in _WORKERS.values()) >= 32
                or len(_WORKERS) >= 256
            ):
                return _failure("mcp_session_limit", unknown=False)
            try:
                worker = _BrowserWorker(executor, config, scope, step.tool_id, fingerprint)
            except BOUNDARY_ERRORS:
                return _failure("tool_worker_not_started", unknown=False)
            _WORKERS[key] = worker
        elif worker.fingerprint != fingerprint:
            worker.close()
            return _failure("mcp_session_lost")
    return worker.call(step, context, deadline, business_url)


def close_browser_worker_scope(scope: str) -> int:
    with _LOCK:
        entries = [(key, worker) for key, worker in _WORKERS.items() if key[1] == scope]
    closed = [(key, worker) for key, worker in entries if worker.close()]
    with _LOCK:
        for key, worker in closed:
            if _WORKERS.get(key) is worker:
                _WORKERS.pop(key)
    return len(closed)


def close_all_browser_workers() -> None:
    for scope in {key[1] for key in tuple(_WORKERS)}:
        close_browser_worker_scope(scope)


atexit.register(close_all_browser_workers)
