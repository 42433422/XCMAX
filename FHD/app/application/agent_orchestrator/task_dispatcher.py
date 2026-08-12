"""Concurrent background dispatcher for durable Agent task executions."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.task_execution_repository import (
    AgentTaskExecution,
    TaskExecutionRepository,
    get_task_execution_repository,
)

logger = logging.getLogger(__name__)


@dataclass
class _ActiveWorker:
    execution: AgentTaskExecution
    owner_id: str
    thread: threading.Thread
    last_heartbeat: float


def _configured_worker_count() -> int:
    raw = os.environ.get("XCAGI_AGENT_TASK_WORKERS", "4").strip()
    try:
        return max(1, min(16, int(raw)))
    except ValueError:
        return 4


class AgentTaskDispatcher:
    def __init__(
        self,
        *,
        execution_repository: TaskExecutionRepository | None = None,
        run_repository: AgentRunRepository | None = None,
        max_workers: int | None = None,
        poll_seconds: float = 0.2,
        lease_seconds: float = 15.0,
        heartbeat_seconds: float = 4.0,
        orchestrator_factory: Callable[[AgentRunRepository], AgentOrchestrator] | None = None,
    ) -> None:
        self._execution_repo = execution_repository or get_task_execution_repository()
        self._run_repo = run_repository or get_agent_run_repository()
        self._max_workers = max(1, int(max_workers or _configured_worker_count()))
        self._poll_seconds = max(0.02, float(poll_seconds))
        self._lease_seconds = max(3.0, float(lease_seconds))
        self._heartbeat_seconds = min(
            max(0.5, float(heartbeat_seconds)),
            self._lease_seconds / 2,
        )
        self._orchestrator_factory = orchestrator_factory or (
            lambda repository: AgentOrchestrator(repository=repository)
        )
        self._instance_id = f"task-dispatcher-{uuid.uuid4().hex}"
        self._active: dict[str, _ActiveWorker] = {}
        self._active_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._coordinator: threading.Thread | None = None

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def start(self) -> None:
        if self._coordinator is not None and self._coordinator.is_alive():
            return
        self._stop.clear()
        self._coordinator = threading.Thread(
            target=self._run_loop,
            name=f"{self._instance_id}-coordinator",
            daemon=True,
        )
        self._coordinator.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        coordinator = self._coordinator
        if coordinator is not None:
            coordinator.join(timeout=max(0.0, float(timeout)))
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._active_lock:
            workers = [item.thread for item in self._active.values()]
        for worker in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)

    def notify(self) -> None:
        self._wake.set()

    def snapshot(self) -> dict[str, object]:
        with self._active_lock:
            active = [
                {
                    "run_id": item.execution.run_id,
                    "task_id": item.execution.task_id,
                    "owner_id": item.owner_id,
                }
                for item in self._active.values()
            ]
        return {
            "instance_id": self._instance_id,
            "max_workers": self._max_workers,
            "active_count": len(active),
            "active": active,
            "running": bool(self._coordinator and self._coordinator.is_alive()),
        }

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self._prune_and_heartbeat()
            while not self._stop.is_set() and self._active_count() < self._max_workers:
                owner_id = f"{self._instance_id}:{uuid.uuid4().hex}"
                execution = self._execution_repo.claim(
                    owner_id,
                    lease_seconds=self._lease_seconds,
                )
                if execution is None:
                    break
                worker = threading.Thread(
                    target=self._execute_claim,
                    args=(execution, owner_id),
                    name=f"agent-task-{execution.run_id[-10:]}",
                    daemon=True,
                )
                with self._active_lock:
                    self._active[execution.run_id] = _ActiveWorker(
                        execution=execution,
                        owner_id=owner_id,
                        thread=worker,
                        last_heartbeat=time.monotonic(),
                    )
                worker.start()
            self._wake.wait(timeout=self._poll_seconds)
            self._wake.clear()

    def _active_count(self) -> int:
        with self._active_lock:
            return len(self._active)

    def _prune_and_heartbeat(self) -> None:
        now = time.monotonic()
        with self._active_lock:
            active = list(self._active.items())
        for run_id, item in active:
            if not item.thread.is_alive():
                with self._active_lock:
                    self._active.pop(run_id, None)
                continue
            if now - item.last_heartbeat < self._heartbeat_seconds:
                continue
            renewed = self._execution_repo.heartbeat(
                run_id,
                item.owner_id,
                lease_seconds=self._lease_seconds,
            )
            if renewed:
                with self._active_lock:
                    current = self._active.get(run_id)
                    if current is not None:
                        current.last_heartbeat = now

    def _execute_claim(self, execution: AgentTaskExecution, owner_id: str) -> None:
        error_code = ""
        state = "failed"
        try:
            orchestrator = self._orchestrator_factory(self._run_repo)
            run = orchestrator.execute_dispatched_run(
                execution.run_id,
                recovered=execution.recovery_count > 0,
            )
            if run is None:
                error_code = "worker_run_unavailable"
            else:
                state = {
                    "completed": "completed",
                    "failed": "failed",
                    "cancelled": "cancelled",
                    "paused": "paused",
                    "blocked": "blocked",
                    "waiting_user": "blocked",
                }.get(run.status, "failed")
                if state == "failed" and run.status != "failed":
                    error_code = "worker_incomplete_state"
        except Exception:  # thread boundary: preserve the worker pool and persist safe evidence
            logger.exception("agent task worker failed for run %s", execution.run_id)
            error_code = "worker_execution_failed"
            try:
                self._orchestrator_factory(self._run_repo).fail_dispatched_run(execution.run_id)
            except Exception:
                logger.exception("agent task failure receipt could not be persisted")
        finally:
            self._execution_repo.finish(
                execution.run_id,
                owner_id,
                state,
                error_code=error_code,
            )
            with self._active_lock:
                self._active.pop(execution.run_id, None)
            self._wake.set()


_dispatcher: AgentTaskDispatcher | None = None
_dispatcher_lock = threading.RLock()


def get_agent_task_dispatcher() -> AgentTaskDispatcher:
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            _dispatcher = AgentTaskDispatcher()
        return _dispatcher


def start_agent_task_dispatcher() -> AgentTaskDispatcher:
    dispatcher = get_agent_task_dispatcher()
    dispatcher.start()
    return dispatcher


def stop_agent_task_dispatcher(*, timeout: float = 5.0) -> None:
    with _dispatcher_lock:
        dispatcher = _dispatcher
    if dispatcher is not None:
        dispatcher.stop(timeout=timeout)


def notify_agent_task_dispatcher() -> None:
    get_agent_task_dispatcher().notify()


def set_agent_task_dispatcher_for_tests(dispatcher: AgentTaskDispatcher | None) -> None:
    global _dispatcher
    with _dispatcher_lock:
        _dispatcher = dispatcher


__all__ = [
    "AgentTaskDispatcher",
    "get_agent_task_dispatcher",
    "notify_agent_task_dispatcher",
    "set_agent_task_dispatcher_for_tests",
    "start_agent_task_dispatcher",
    "stop_agent_task_dispatcher",
]
