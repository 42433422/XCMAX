#!/usr/bin/env python3
"""CI-runnable client/task continuity fault-injection harness.

Simulates disconnect/reconnect, history restore, streaming interruption,
tool timeouts, task retry/idempotency, and upgrade-before/after business
data consistency without touching production hosts.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class ContinuityError(RuntimeError):
    """Raised when a continuity contract is violated."""


@dataclass
class SessionState:
    session_id: str
    connected: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)
    stream_cursor: int = 0
    last_error: str = ""


@dataclass
class TaskRecord:
    task_id: str
    idempotency_key: str
    status: str
    attempts: int = 0
    result: Any = None


class ContinuityHarness:
    """In-memory client + task continuum with injectable faults."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.session = SessionState(session_id="sess-1")
        self.tasks: dict[str, TaskRecord] = {}
        self._stream_chunks: list[str] = []
        self._tool_impl: Callable[[], Any] | None = None
        self._tool_timeout_seconds = 1.0
        self.business_store: dict[str, Any] = {}
        self.app_version = "1.0.0.6"
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._load_business_store()

    # --- disconnect / reconnect ---
    def disconnect(self, reason: str = "network") -> None:
        self.session.connected = False
        self.session.last_error = reason

    def reconnect(self) -> SessionState:
        if self.session.connected:
            return self.session
        self.session.connected = True
        self.session.last_error = ""
        return self.session

    def require_connected(self) -> None:
        if not self.session.connected:
            raise ContinuityError(f"disconnected:{self.session.last_error or 'unknown'}")

    # --- history restore ---
    def append_history(self, role: str, content: str) -> None:
        self.require_connected()
        self.session.history.append(
            {"role": role, "content": content, "seq": len(self.session.history)}
        )

    def restore_history(self) -> list[dict[str, Any]]:
        """After reconnect, history must be intact and ordered."""
        self.reconnect()
        restored = list(self.session.history)
        for index, item in enumerate(restored):
            if item.get("seq") != index:
                raise ContinuityError("history_order_corrupt")
        return restored

    # --- streaming ---
    def begin_stream(self, chunks: list[str]) -> None:
        self.require_connected()
        self._stream_chunks = list(chunks)
        self.session.stream_cursor = 0

    def read_stream(self, *, inject_drop_after: int | None = None) -> list[str]:
        """Read stream; optional mid-stream disconnect then resume from cursor."""
        received: list[str] = []
        while self.session.stream_cursor < len(self._stream_chunks):
            if inject_drop_after is not None and len(received) >= inject_drop_after:
                self.disconnect("stream_reset")
                break
            self.require_connected()
            received.append(self._stream_chunks[self.session.stream_cursor])
            self.session.stream_cursor += 1
        return received

    def resume_stream(self) -> list[str]:
        self.reconnect()
        return self.read_stream(inject_drop_after=None)

    # --- tool timeout ---
    def set_tool(self, impl: Callable[[], Any], timeout_seconds: float = 1.0) -> None:
        self._tool_impl = impl
        self._tool_timeout_seconds = timeout_seconds

    def run_tool_with_deadline(self) -> dict[str, Any]:
        self.require_connected()
        if self._tool_impl is None:
            raise ContinuityError("tool_not_configured")
        started = time.monotonic()
        try:
            result = self._tool_impl()
        except (OSError, RuntimeError) as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "retryable": True,
                "elapsed": time.monotonic() - started,
            }
        elapsed = time.monotonic() - started
        if elapsed > self._tool_timeout_seconds:
            return {
                "ok": False,
                "error": "tool_timeout",
                "retryable": True,
                "elapsed": elapsed,
                "outcome": "unknown",
                "reconciliation_required": True,
            }
        return {"ok": True, "result": result, "elapsed": elapsed}

    # --- task retry / idempotency ---
    def submit_task(
        self, task_id: str, idempotency_key: str, work: Callable[[], Any]
    ) -> TaskRecord:
        self.require_connected()
        existing = next(
            (t for t in self.tasks.values() if t.idempotency_key == idempotency_key), None
        )
        if existing is not None:
            return existing
        record = TaskRecord(
            task_id=task_id, idempotency_key=idempotency_key, status="running", attempts=1
        )
        try:
            record.result = work()
            record.status = "succeeded"
        except (OSError, RuntimeError) as exc:
            record.status = "failed"
            record.result = {"error": type(exc).__name__, "message": str(exc)}
        self.tasks[task_id] = record
        return record

    def retry_task(self, task_id: str, work: Callable[[], Any]) -> TaskRecord:
        self.require_connected()
        record = self.tasks[task_id]
        if record.status == "succeeded":
            return record
        record.attempts += 1
        try:
            record.result = work()
            record.status = "succeeded"
        except (OSError, RuntimeError) as exc:
            record.status = "failed"
            record.result = {"error": type(exc).__name__, "message": str(exc)}
        return record

    # --- upgrade before/after business data ---
    def write_business(self, key: str, value: Any) -> None:
        self.business_store[key] = value
        self._persist_business_store()

    def read_business(self, key: str) -> Any:
        self._load_business_store()
        if key not in self.business_store:
            raise ContinuityError(f"missing_business_key:{key}")
        return self.business_store[key]

    def simulate_upgrade(self, new_version: str) -> dict[str, Any]:
        before = dict(self.business_store)
        fingerprint = hashlib.sha256(
            json.dumps(before, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        self.app_version = new_version
        self._persist_business_store()
        after = self.business_store
        if after != before:
            raise ContinuityError("upgrade_mutated_business_data")
        return {
            "version": self.app_version,
            "fingerprint": fingerprint,
            "keys": sorted(after),
        }

    def _store_path(self) -> Path | None:
        if self.data_dir is None:
            return None
        return self.data_dir / "business-store.json"

    def _persist_business_store(self) -> None:
        path = self._store_path()
        if path is None:
            return
        payload = {"version": self.app_version, "data": self.business_store}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _load_business_store(self) -> None:
        path = self._store_path()
        if path is None or not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.app_version = str(payload.get("version") or self.app_version)
        data = payload.get("data")
        if isinstance(data, dict):
            self.business_store = data
