"""Bounded live Para hints; receipts and the periodic sweep remain authoritative."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
from urllib.parse import urlsplit, urlunsplit

from modstore_server.operational_errors import RECOVERABLE_ERRORS

_LOG = logging.getLogger(__name__)
_START_LOCK = threading.Lock()
_LISTENER = None


def _connection_settings():
    from modstore_server.cred_vault import get_credential
    from modstore_server.para_delegate_handler import _api_base

    if os.environ.get("MODSTORE_PARA_TASK_EVENTS_ENABLED", "1").lower() in {
        "0",
        "false",
        "off",
    }:
        return None
    base = urlsplit(_api_base())
    if (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.username
        or base.query
        or base.fragment
    ):
        return None
    token = (
        get_credential(
            "MODSTORE_PARA_AUTH_TOKEN",
            task_id="para-task-events",
            purpose="para_dispatch_auth",
            aliases=("DEVFLEET_AUTH_TOKEN",),
        )
        or ""
    )
    if not token.startswith("pst_"):
        return None  # Browser/guest JWT behavior and polling remain unchanged.
    return (
        urlunsplit(
            (
                "wss" if base.scheme == "https" else "ws",
                base.netloc,
                base.path.rstrip("/") + "/ws/task-events",
                "",
                "",
            )
        ),
        token,
    )


def task_id_from_notification(raw):
    try:
        message = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(message, dict)
        or message.get("type") != "task_status"
        or message.get("schema_version") != 1
    ):
        return None
    task_id = message.get("task_id")
    return (
        task_id
        if isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", task_id)
        else None
    )


class TaskEventListener:
    def __init__(self, on_notice, *, settings=_connection_settings, connector=None):
        self.on_notice = on_notice
        self.settings = settings
        self.connector = connector
        self.stopped = threading.Event()
        self.pending = queue.Queue(maxsize=256)
        self.queued = set()
        self.lock = threading.Lock()
        self.socket = None
        self.threads = [
            threading.Thread(
                target=self._receive, name="para-task-events", daemon=True
            ),
            threading.Thread(
                target=self._drain, name="para-task-readback", daemon=True
            ),
        ]

    def enqueue(self, task_id):
        with self.lock:
            if task_id in self.queued:
                return
            try:
                self.pending.put_nowait(task_id)
            except queue.Full:
                return  # The SQL sweep recovers missed hints; never grow an unbounded backlog.
            self.queued.add(task_id)

    def start(self):
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stopped.set()
        if self.socket is not None:
            try:
                self.socket.close()
            except RECOVERABLE_ERRORS:
                pass
        for thread in self.threads:
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=3)

    def _drain(self):
        while not self.stopped.is_set():
            try:
                task_id = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.on_notice(task_id)
            except RECOVERABLE_ERRORS as exc:
                _LOG.warning(
                    "Para notification readback deferred: %s", type(exc).__name__
                )
            finally:
                with self.lock:
                    self.queued.discard(task_id)

    def _receive(self):
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect

        connector = self.connector or connect
        delay = 1
        while not self.stopped.is_set():
            try:
                settings = self.settings()
                if settings is None:
                    if self.stopped.wait(30):
                        return
                    continue
                url, token = settings
                with connector(
                    url,
                    additional_headers={"Authorization": "Bearer " + token},
                    proxy=None,
                    open_timeout=10,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=4096,
                    max_queue=16,
                ) as ws:
                    self.socket = ws
                    while not self.stopped.is_set():
                        try:
                            raw = ws.recv(timeout=1)
                        except TimeoutError:
                            continue
                        try:
                            ready = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if (
                            isinstance(ready, dict)
                            and ready.get("type") == "task_events_ready"
                            and ready.get("schema_version") == 1
                        ):
                            delay = 1
                            self.enqueue(
                                None
                            )  # Live-only stream: recover missed receipts with GET.
                        task_id = task_id_from_notification(raw)
                        if task_id:
                            self.enqueue(task_id)
            except (*RECOVERABLE_ERRORS, WebSocketException) as exc:
                _LOG.debug("Para task events disconnected: %s", type(exc).__name__)
            finally:
                self.socket = None
            if self.stopped.wait(delay):
                return
            delay = min(delay * 2, 30)


def start_task_event_listener():
    global _LISTENER
    with _START_LOCK:
        if _LISTENER is not None and not _LISTENER.stopped.is_set():
            return _LISTENER
        try:
            settings = _connection_settings()
        except RECOVERABLE_ERRORS as exc:
            _LOG.warning("Para notifications unavailable: %s", type(exc).__name__)
            return None
        if settings is None:
            return None
        from modstore_server.incident_team_completion import reconcile_task_notification

        _LISTENER = TaskEventListener(reconcile_task_notification)
        _LISTENER.start()
        return _LISTENER
