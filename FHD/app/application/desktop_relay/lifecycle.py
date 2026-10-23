"""Poller startup, shutdown and retry timing without holding locks across I/O."""

from __future__ import annotations

import logging
import threading
from _thread import LockType
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import httpx

from app.services.desktop_relay.ports import (
    PollBackoffCall,
    ReadConfig,
    StopSignal,
    Worker,
    WorkerFactory,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def poll_backoff_seconds(failure_count: int, *, base_interval: float, max_interval: float) -> float:
    failures = max(0, int(failure_count))
    if failures <= 0:
        return max(1.0, base_interval)
    return float(min(max_interval, max(1.0, base_interval) * 2 ** min(failures - 1, 8)))


@dataclass(frozen=True)
class LifecyclePorts:
    read_config: ReadConfig
    state_lock: Callable[[], LockType]
    stop_signal: Callable[[], StopSignal]
    worker: Callable[[], Worker | None]
    set_worker: Callable[[Worker | None], None]
    create_worker: WorkerFactory
    current_worker: Callable[[], Worker]
    collect_workspaces: Callable[[], int]
    poll_loop: Callable[[], Callable[[], None]]
    poll_once: Callable[[], None]
    backoff: PollBackoffCall
    environment: Callable[[], Mapping[str, str]]
    monotonic: Callable[[], float]


@dataclass
class _Launch:
    done: threading.Event = field(default_factory=threading.Event)
    worker: Worker | None = None


class RelayLifecycle:
    def __init__(self, ports: LifecyclePorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger
        self._launch: _Launch | None = None

    def start(self) -> bool:
        config = self.ports.read_config()
        if not config.get("relay_id") or not config.get("desktop_token"):
            return False
        logging.getLogger("httpx").setLevel(logging.WARNING)
        stop = self.ports.stop_signal()
        with self.ports.state_lock():
            worker = self.ports.worker()
            if worker is not None and worker.is_alive():
                return not stop.is_set()
            if self._launch is not None:
                return False
            launch = self._launch = _Launch()
            stop.clear()
        started = False
        worker = None
        try:
            try:
                self.ports.collect_workspaces()
            except RECOVERABLE_ERRORS:
                self.logger.warning("relay 工作区 GC 失败", exc_info=True)
            callback = self.ports.poll_loop()

            def run() -> None:
                if not stop.is_set():
                    callback()

            worker = self.ports.create_worker(run, "xcagi-mobile-relay-desktop")
            with self.ports.state_lock():
                if stop.is_set():
                    return False
                self.ports.set_worker(worker)
                launch.worker = worker
            if stop.is_set():
                return False
            worker.start()
            started = True
            return True
        finally:
            with self.ports.state_lock():
                if not started:
                    launch.worker = None
                    if self.ports.worker() is worker:
                        self.ports.set_worker(None)
                self._launch = None
                launch.done.set()

    def stop(self) -> None:
        try:
            request_timeout = float(
                self.ports.environment().get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30"
            )
        except (TypeError, ValueError):
            request_timeout = 30.0
        timeout = max(1.0, request_timeout + 1.0)
        with self.ports.state_lock():
            self.ports.stop_signal().set()
            worker, launch = self.ports.worker(), self._launch
        if worker is self.ports.current_worker():
            return
        if launch is not None:
            started = self.ports.monotonic()
            if not launch.done.wait(timeout):
                self.logger.warning(
                    "mobile relay poller startup did not stop within %.1fs", timeout
                )
                return
            worker = launch.worker
            timeout = max(0.0, timeout - (self.ports.monotonic() - started))
        if worker is None or worker is self.ports.current_worker():
            return
        worker.join(timeout=timeout)
        with self.ports.state_lock():
            if self.ports.worker() is worker and not worker.is_alive():
                self.ports.set_worker(None)
        if worker.is_alive():
            self.logger.warning(
                "mobile relay poller did not stop within %.1fs", request_timeout + 1.0
            )

    def poll_loop(self) -> None:
        interval = float(self.ports.environment().get("XCAGI_RELAY_POLL_INTERVAL_SEC") or "4")
        max_backoff = float(
            self.ports.environment().get("XCAGI_RELAY_POLL_MAX_BACKOFF_SEC") or "300"
        )
        failure_count = 0
        stop = self.ports.stop_signal()
        while not stop.is_set():
            wait_seconds = max(1.0, interval)
            try:
                self.ports.poll_once()
                if failure_count:
                    self.logger.info(
                        "mobile relay poll recovered after %d failure(s)", failure_count
                    )
                failure_count = 0
            except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
                failure_count += 1
                wait_seconds = self.ports.backoff(
                    failure_count, base_interval=interval, max_interval=max_backoff
                )
                if failure_count == 1 or failure_count & (failure_count - 1) == 0:
                    self.logger.warning(
                        "mobile relay unavailable; retry in %.0fs (failure %d): %s",
                        wait_seconds,
                        failure_count,
                        exc,
                    )
                else:
                    self.logger.debug("mobile relay remains unavailable: %s", exc)
            except RECOVERABLE_ERRORS as exc:
                failure_count += 1
                wait_seconds = self.ports.backoff(
                    failure_count, base_interval=interval, max_interval=max_backoff
                )
                self.logger.warning(
                    "mobile relay poll failed; retry in %.0fs: %s", wait_seconds, exc
                )
            stop.wait(wait_seconds)
