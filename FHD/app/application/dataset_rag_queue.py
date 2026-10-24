"""Process-safe dataset state and rebuild ownership; tool children only enqueue."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import threading
import uuid
import weakref
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Protocol

import psutil


def owner_id() -> str:
    return f"{os.getpid()}:{psutil.Process().create_time()}:{uuid.uuid4().hex}"


def owner_alive(owner: str) -> bool:
    try:
        pid, created, *_ = owner.split(":")
        process = psutil.Process(int(pid))
        return (
            process.create_time() == float(created)
            and process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except (ValueError, psutil.Error):
        return False


class PersistentDatasetState(Protocol):
    storage_path: Path

    def _load_persisted_state(self) -> None: ...


class DatasetStateLock:
    def __init__(self, repository: PersistentDatasetState) -> None:
        self.repository = weakref.proxy(repository)
        self.thread_lock = threading.Lock()
        self.connection: sqlite3.Connection | None = None
        self.revision: tuple[int, int] | None = None

    def revision_now(self) -> tuple[int, int] | None:
        path = self.repository.storage_path
        return (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None

    def __enter__(self) -> DatasetStateLock:
        with ExitStack() as cleanup:
            self.thread_lock.acquire()
            cleanup.callback(self.__exit__, None, None, None)
            path = self.repository.storage_path
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(path) + ".lock.sqlite3", timeout=1)
            self.connection.execute("BEGIN IMMEDIATE")
            if self.revision != self.revision_now():
                self.repository._load_persisted_state()
                self.revision = self.revision_now()
            cleanup.pop_all()
            return self

    def __exit__(self, *args: object) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.thread_lock.release()


_hosts: dict[str | None, tuple[threading.Event, threading.Thread, list[Any]]] = {}
_hosts_lock = threading.Lock()


def ensure_host_worker() -> None:
    """No read/resolve/initialization on the caller's tool-deadline path."""
    if multiprocessing.parent_process() is not None:
        return
    path = os.environ.get("DATASET_RAG_STORE_PATH") or os.environ.get(
        "XCAGI_DATASET_RAG_STORE_PATH"
    )
    with _hosts_lock:
        if path in _hosts and _hosts[path][1].is_alive():
            return
        stop = threading.Event()
        holder: list[Any] = []

        def consume():
            from app.application.dataset_rag_app_service import DatasetRagApplicationService

            service = DatasetRagApplicationService(storage_path=path, rebuild_workers_enabled=False)
            holder.append(service)
            service._rebuild_workers_enabled = True
            while not stop.is_set():
                try:
                    service._schedule_rebuild_jobs()
                except (OSError, sqlite3.Error):
                    pass  # Durable work stays queued for the next poll/restart.
                stop.wait(0.1)

        thread = threading.Thread(target=consume, name="dataset-rebuild-host", daemon=True)
        _hosts[path] = (stop, thread, holder)
        thread.start()


def stop_host_workers() -> bool:
    """Fence late writes before teardown; report any still-running host work."""
    with _hosts_lock:
        hosts = list(_hosts.values())
        _hosts.clear()
    clean = True
    for stop, thread, holder in hosts:
        stop.set()
        thread.join(2)
        clean &= not thread.is_alive()
        for service in holder:
            service._rebuild_shutdown = True
            with service._lock:
                for state in service._datasets.values():
                    for job in state.rebuild_jobs.values():
                        if job.status == "running" and job.worker_id == service._rebuild_owner:
                            job.status, job.worker_id = "queued", ""
                service._persist_locked()
            for worker in list(service._rebuild_threads):
                worker.join(1)
                clean &= not worker.is_alive()
    return clean
