"""Owned workbench snapshots and the transition rules for their progress steps."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.intent import CANVAS_SKILL_INTENT

_LOG = logging.getLogger("modstore_server.workbench_api")
Payload = dict[str, Any]


def session_store_directory() -> Path:
    from modstore_server.infrastructure.private_asset_storage import (
        require_private_directory,
    )

    configured = os.environ.get("MODSTORE_RUNTIME_DIR", "").strip()
    runtime = Path(configured) if configured else Path(tempfile.gettempdir()) / "modstore_runtime"
    directory = require_private_directory(runtime / "workbench_sessions")
    directory.mkdir(parents=True, mode=448, exist_ok=True)
    return directory


def session_filename(sid: str) -> str:
    normalized = str(sid or "").strip().lower()
    if not 16 <= len(normalized) <= 32 or any((c not in "0123456789abcdef" for c in normalized)):
        raise ValueError("invalid session id")
    return f"{normalized}.json"


@dataclass
class SessionStore:
    data: MutableMapping[str, Payload]
    lock: asyncio.Lock
    path_for: Callable[[str], Path]
    legacy_directory: Path | None = None

    @staticmethod
    def _write(path: Path, session: Payload) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(session, stream, ensure_ascii=False, default=str)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def persist(self, sid: str) -> None:
        session = self.data.get(sid)
        if not session:
            return
        try:
            path = self.path_for(sid)
        except ValueError:
            return
        try:
            self._write(path, session)
        except OSError:
            _LOG.debug("workbench snapshot write failed sid=%s", sid, exc_info=True)

    def load(self, sid: str) -> Payload | None:
        try:
            path = self.path_for(sid)
        except ValueError:
            return None
        source = path
        if not path.exists() and self.legacy_directory is not None:
            source = self.legacy_directory / session_filename(sid)
        if source.is_symlink() or not source.is_file():
            return None
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        if source != path:
            if str(raw.get("id") or "") != str(sid):
                return None
            try:
                self._write(path, raw)
            except OSError:
                _LOG.debug("workbench snapshot migration failed sid=%s", sid, exc_info=True)
        return raw

    def hydrate(self, sid: str) -> None:
        if sid in self.data:
            return
        loaded = self.load(sid)
        if loaded and str(loaded.get("id") or "") == str(sid):
            if loaded.get("intent") == "workflow":
                loaded["intent"] = CANVAS_SKILL_INTENT
            self.data[sid] = loaded

    async def persist_locked(self, sid: str) -> None:
        async with self.lock:
            self.persist(sid)

    def task_failsafe(self, sid: str) -> Callable[[asyncio.Task[None]], None]:

        def completed(task: asyncio.Task[None]) -> None:
            try:
                error = task.exception()
            except asyncio.CancelledError:
                return
            except RECOVERABLE_ERRORS:
                return
            if error is None:
                return
            _LOG.exception("workbench task failed session=%s: %s", sid, error, exc_info=error)
            session = self.data.get(sid)
            if not session:
                return
            message = f"[内部错误] {type(error).__name__}: {error!s}"[:2000]
            if session.get("status") == "running":
                session.update(status="error", error=message)
            for step in session.get("steps") or []:
                if step.get("status") == "running":
                    step.update(status="error", message=message[:480])
                    step.pop("started_at", None)
                    break
            self.persist(sid)

        return completed


class StepUpdate(Protocol):
    def __call__(
        self, sid: str, step_id: str, status: str, message: str | dict | None = None
    ) -> Awaitable[None]: ...


@dataclass(frozen=True)
class ProgressCallbacks:
    set_step: StepUpdate
    fail: Callable[[str, str, str], Awaitable[None]]
    finish: Callable[[str, Payload], Awaitable[None]]


@dataclass
class SessionProgress:
    store: SessionStore
    record_skip: Callable[[str, str, Payload | None], None]

    async def set_step(
        self, sid: str, step_id: str, status: str, message: str | dict | None = None
    ) -> None:
        async with self.store.lock:
            self.store.hydrate(sid)
            session = self.store.data.get(sid)
            if not session:
                return
            for step in session["steps"]:
                if step["id"] != step_id:
                    continue
                previous = step.get("status")
                if previous in ("done", "error") and status not in (
                    "done",
                    "error",
                    "skipped",
                ):
                    break
                if previous == "running" and status == "pending":
                    break
                step["status"] = status
                if message is not None:
                    step["message"] = message
                if status == "running" and previous != "running":
                    step["started_at"] = datetime.now(timezone.utc).isoformat() + "Z"
                elif status in ("done", "error", "skipped"):
                    step.pop("started_at", None)
                break
            self.store.persist(sid)
        if status in ("done", "error", "skipped"):
            self.record_skip(step_id, status, session)

    async def fail(self, sid: str, step_id: str, error: str) -> None:
        message = (error or "步骤失败").strip()[:1000]
        if step_id == "workflow_sandbox" and message:
            try:
                from modstore_server.craft_failure_signals import (
                    emit_craft_step_failure,
                )

                async with self.store.lock:
                    self.store.hydrate(sid)
                    signal_session = self.store.data.get(sid) or {}
                emit_craft_step_failure(
                    step_id="workflow_sandbox",
                    error=message,
                    user_id=int(signal_session.get("user_id") or 0),
                )
            except RECOVERABLE_ERRORS:
                _LOG.debug("workflow_sandbox fail signal emit skipped", exc_info=True)
        async with self.store.lock:
            self.store.hydrate(sid)
            session = self.store.data.get(sid)
            if not session:
                return
            session.update(status="error", error=message)
            selected = next(
                (
                    step
                    for step in session["steps"]
                    if step["id"] == step_id and step["status"] == "running"
                ),
                None,
            )
            if selected is None:
                selected = next((step for step in session["steps"] if step["id"] == step_id), None)
            if selected is not None:
                selected.update(status="error", message=message)
            self.store.persist(sid)

    async def finish(self, sid: str, artifact: Payload) -> None:
        async with self.store.lock:
            self.store.hydrate(sid)
            session = self.store.data.get(sid)
            if not session or session.get("status") == "error":
                return
            for step in session.get("steps") or []:
                if step.get("status") not in ("done", "error", "skipped"):
                    _LOG.warning(
                        "workbench session=%s step=%s incomplete; marking skipped",
                        sid,
                        step.get("id"),
                    )
                    step["status"] = "skipped"
                    if not step.get("message"):
                        step["message"] = "管线收尾时标记跳过"
                    step.pop("started_at", None)
            session.update(status="done", artifact=artifact)
            self.store.persist(sid)


def record_craft_skip(step_id: str, status: str, session: Payload | None) -> None:
    if status != "skipped":
        return
    try:
        from modstore_server.craft_executor import (
            _record_craft_execution,
            craft_step_to_employee_id,
        )

        employee_id = craft_step_to_employee_id(step_id)
        if employee_id:
            _record_craft_execution(
                employee_id=employee_id,
                user_id=session.get("user_id", 0) if session else 0,
                task=f"craft pipeline step: {step_id}",
                status="skipped",
                duration_ms=0,
                llm_tokens=0,
            )
    except RECOVERABLE_ERRORS:
        pass
