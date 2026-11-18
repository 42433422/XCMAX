"""Proactive events: dedupe, durable outbox and channel delivery.

The service is transport-agnostic. In-app delivery is an injected callable so the
calling web process can reuse its own WebSocket hub; Apprise channel fanout is
optional and only imported when delivery URLs are configured.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

__all__ = ["ProactiveEvent", "ProactiveService", "apprise_sender", "proactive_root"]

DEDUPE_WINDOW_SECONDS = 24 * 60 * 60
_MAX_OUTBOX_BYTES = 2 * 1024 * 1024
Sender = Callable[["ProactiveEvent"], None]


@dataclass(frozen=True)
class ProactiveEvent:
    kind: str
    title: str
    detail: str = ""
    fingerprint: str = ""
    user_ids: tuple[int, ...] = ()
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "user_ids": list(self.user_ids),
            "created_at": self.created_at,
        }


def proactive_root() -> Path:
    base = os.environ.get("MODSTORE_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "proactive"


def apprise_sender(urls: list[str] | None = None) -> Sender:
    """Deliver through Apprise; configured by ``PROACTIVE_APPRISE_URLS``."""
    targets = urls

    def send(event: ProactiveEvent) -> None:
        configured = targets
        if configured is None:
            raw = str(os.environ.get("PROACTIVE_APPRISE_URLS") or "")
            configured = [item.strip() for item in raw.split(",") if item.strip()]
        if not configured:
            return
        import apprise

        client = apprise.Apprise()
        for url in configured:
            client.add(url)
        body = event.detail or event.title
        if not client.notify(body=body, title=event.title):
            raise RuntimeError("Apprise 投递失败")

    return send


class ProactiveService:
    def __init__(
        self,
        root: Path | None = None,
        *,
        senders: list[Sender] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root or proactive_root()
        self._senders = list(senders) if senders is not None else []
        self._clock = clock

    def _state_path(self) -> Path:
        return self._root / "dedupe.json"

    def _read_state(self) -> dict[str, float]:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(key): float(value) for key, value in data.items()} if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, float], now: float) -> None:
        pruned = {
            key: value for key, value in state.items() if now - value < DEDUPE_WINDOW_SECONDS
        }
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_path().write_text(json.dumps(pruned, ensure_ascii=False), encoding="utf-8")

    def _append_outbox(self, event: ProactiveEvent) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / "outbox.jsonl"
        try:
            if path.stat().st_size > _MAX_OUTBOX_BYTES:
                path.replace(self._root / "outbox.1.jsonl")
        except OSError:
            pass
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.as_dict(), ensure_ascii=False) + "\n")

    def publish(self, event: ProactiveEvent) -> dict[str, Any]:
        """Store the event once per dedupe window and deliver it to every channel."""
        fingerprint = event.fingerprint or f"{event.kind}:{event.title}"
        now = self._clock()
        state = self._read_state()
        last = state.get(fingerprint)
        if last is not None and now - last < DEDUPE_WINDOW_SECONDS:
            return {"ok": True, "deduped": True, "fingerprint": fingerprint}
        self._append_outbox(event)
        state[fingerprint] = now
        self._write_state(state, now)
        delivered: list[str] = []
        errors: list[str] = []
        for sender in self._senders:
            try:
                sender(event)
                delivered.append(getattr(sender, "__name__", "channel"))
            except Exception as exc:  # delivery failures never duplicate the event
                errors.append(f"{type(exc).__name__}: {exc}")
        return {
            "ok": True,
            "deduped": False,
            "fingerprint": fingerprint,
            "event_id": event.event_id,
            "delivered": delivered,
            "errors": errors,
        }

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Read the newest outbox rows (bounded)."""
        try:
            lines = (self._root / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in lines[-max(1, limit) :]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows
