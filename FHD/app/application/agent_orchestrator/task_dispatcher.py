"""Concurrent background dispatcher for durable Agent task executions."""

from __future__ import annotations

import contextvars
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
from app.application.agent_orchestrator.task_execution_models import dispatched_run_state
from app.application.agent_orchestrator.task_execution_repository import (
    AgentTaskExecution,
    TaskExecutionRepository,
    get_task_execution_repository,
)
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_open_effect: contextvars.ContextVar[tuple[object, str, str] | None] = contextvars.ContextVar(
    "task_open_effect", default=None
)


def note_open_effect(run_id: str, effect_id: str) -> None:
    """Record a side effect only while a worker is inside a real tool call."""
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim

    worker = capture_worker_claim()
    claim = _open_effect.get()
    if claim is None and worker is not None:
        from app.application.agent_orchestrator.task_execution_sql_repository import (
            SQLAlchemyTaskExecutionRepository,
        )

        # Spawn restores only the server-captured HOST claim, never a caller's
        # runtime fields or the independently routed Mod business database.
        claim = (SQLAlchemyTaskExecutionRepository(auto_create=False), worker[0], worker[1])
    if claim is None:
        return
    repo, claimed_run_id, owner_id = claim
    marker = getattr(repo, "mark_open_effect", None)
    if marker is not None:
        effect = effect_id if run_id == claimed_run_id else f"child:{run_id}:{effect_id}"
        generation = (
            {"execution_count": worker[2]}
            if worker is not None and worker[:2] == (claimed_run_id, owner_id)
            else {}
        )
        if marker(claimed_run_id, effect, owner_id=owner_id, **generation) is False:
            from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

            raise WorkerLeaseLost("worker lease expired before opening a side effect")


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
        self._outcome_worker: threading.Thread | None = None
        self._last_outcome_recovery = float("-inf")
        self._xiaox_resume_cursor: dict[str, str] = {}
        self._chat_delivery_cursor: dict[str, str] = {}

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
        if self._outcome_worker is not None:
            self._outcome_worker.join(timeout=max(0.0, deadline - time.monotonic()))

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
            try:
                self._dispatch_available()
            except RECOVERABLE_ERRORS:
                # Database startup, migration, or a transient outage must not
                # escape the daemon thread as an unhandled exception.
                logger.exception("agent task dispatcher cycle failed; retrying")
                self._wake.wait(timeout=max(1.0, self._poll_seconds))
            else:
                self._wake.wait(timeout=self._poll_seconds)
            self._wake.clear()

    def _dispatch_available(self) -> None:
        self._prune_and_heartbeat()
        self._recover_outcomes()
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

    def _recover_outcomes(self) -> None:
        """Reconcile evidence independently so readback cannot delay worker leases."""
        now = time.monotonic()
        if (
            self._stop.is_set()
            or (self._outcome_worker is not None and self._outcome_worker.is_alive())
            or now - self._last_outcome_recovery < 30.0
        ):
            return
        self._last_outcome_recovery = now

        def recover() -> None:
            from app.application.agent_orchestrator.verification_recovery import (
                reconcile_pending_verifications,
            )
            from app.application.ai_chat.queued_chat_delivery import reconcile_pending_chat_replies
            from app.application.enterprise_cognition.outcomes import reconcile_pending_outcomes
            from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

            try:
                reconcile_pending_verifications(
                    repository=self._run_repo, stopped=self._stop.is_set
                )
            except RECOVERABLE_ERRORS:
                logger.warning("original result verification remains pending", exc_info=True)
            try:
                reconcile_pending_outcomes(repository=self._run_repo, stopped=self._stop.is_set)
            except RECOVERABLE_ERRORS:
                logger.warning("enterprise outcome reconciliation remains pending", exc_info=True)
            try:
                resume_ready_xiaox_runs(
                    repository=self._run_repo,
                    stopped=self._stop.is_set,
                    cursor=self._xiaox_resume_cursor,
                )
            except RECOVERABLE_ERRORS:
                logger.warning("original Xiaox continuation remains pending", exc_info=True)
            try:
                reconcile_pending_chat_replies(
                    repository=self._run_repo,
                    stopped=self._stop.is_set,
                    cursor=self._chat_delivery_cursor,
                )
            except RECOVERABLE_ERRORS:
                logger.warning("original chat delivery remains pending", exc_info=True)
            self._wake.set()

        self._outcome_worker = threading.Thread(
            target=recover, name=f"{self._instance_id}-outcomes", daemon=True
        )
        self._outcome_worker.start()

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
        from contextlib import nullcontext

        from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
        from app.application.agent_orchestrator.cross_module_chain import (
            InjectedTransactionFault,
            cross_module_ready,
            execute_claimed_cross_module,
        )
        from app.application.agent_orchestrator.elt_checkpoint_recovery import (
            EltCheckpointWorkerExited,
        )
        from app.application.agent_orchestrator.run_sql_repository import (
            SQLAlchemyAgentRunRepository,
        )
        from app.application.agent_orchestrator.worker_repository import (
            ClaimedRunRepository,
            WorkerLeaseLost,
        )

        repository = self._run_repo
        if isinstance(repository, SQLAlchemyAgentRunRepository):
            repository = ClaimedRunRepository(repository, execution, owner_id)
        error_code = ""
        state = "failed"
        abandon = False
        xiaox_run = False
        effect_token = _open_effect.set((self._execution_repo, execution.run_id, owner_id))
        try:
            from app.infrastructure.xiaox.binding import has_legacy_runtime_binding

            preview = self._run_repo.get(execution.run_id)
            if preview is not None and has_legacy_runtime_binding(preview):
                # Never send an old runtime request to the generic step executor.
                # Preserve its signed output and ledger for explicit reconciliation.
                xiaox_run = True
                error_code = "needs_verification"
                return
            orchestrator = self._orchestrator_factory(repository)
            if preview is not None and preview.metadata.get("runtime_type") == "xiaox":
                from app.infrastructure.xiaox.queued_runtime import execute_queued_runtime

                xiaox_run = True
                if not isinstance(self._run_repo, SQLAlchemyAgentRunRepository):
                    raise RuntimeError("queued Xiaox execution requires durable SQL storage")
                with worker_claim_scope(self._run_repo, execution, owner_id):
                    result = execute_queued_runtime(self._run_repo, execution, owner_id)
                state = {
                    "completed": "succeeded",
                    "waiting_user": "waiting_approval",
                    "waiting_approval": "waiting_approval",
                    "running": "waiting_approval",
                    "paused": "waiting_approval",
                    "cancelled": "cancelled",
                }.get(str(result.get("execution_state") or ""), "failed")
                if state == "failed":
                    error_code = (
                        "needs_verification"
                        if result.get("reconciliation_required")
                        else str(result.get("error_code") or "xiaox_request_failed")
                    )
                return
            if preview is not None and cross_module_ready(preview):
                receipt = execute_claimed_cross_module(
                    orchestrator,
                    preview,
                    owner=owner_id,
                    queue=self._execution_repo,
                    request_id=str(preview.metadata.get("approval_request_id") or ""),
                    finish=False,
                )
                state = "succeeded" if receipt.get("success") else "failed"
                error_code = "cross_module_failed" if state == "failed" else ""
                return
            scope = (
                worker_claim_scope(self._run_repo, execution, owner_id)
                if isinstance(self._run_repo, SQLAlchemyAgentRunRepository)
                else nullcontext()
            )
            with scope:
                run = orchestrator.execute_dispatched_run(
                    execution.run_id,
                    recovered=execution.recovery_count > 0,
                )
            if run is None:
                error_code = "worker_run_unavailable"
            else:
                state, error_code = dispatched_run_state(run)
        except EltCheckpointWorkerExited:
            abandon = True
            try:
                self._execution_repo.heartbeat(execution.run_id, owner_id, lease_seconds=1.0)
            except RECOVERABLE_ERRORS:
                logger.info("ELT worker claim will expire normally for %s", execution.run_id)
            logger.warning(
                "ELT checkpoint worker exited; leaving queue claim to expire for %s",
                execution.run_id,
            )
        except InjectedTransactionFault:
            abandon = True
            logger.warning("transaction fault abandoned lease for %s", execution.run_id)
        except WorkerLeaseLost:
            error_code = "worker_lease_lost"
            logger.info("worker stopped after lease loss for run %s", execution.run_id)
        except TimeoutError:
            error_code = "timeout"
            logger.exception("agent task worker timed out for run %s", execution.run_id)
        except BOUNDARY_ERRORS:  # The worker has no request boundary to settle unexpected faults.
            logger.exception("agent task worker failed for run %s", execution.run_id)
            error_code = "needs_verification" if xiaox_run else "worker_execution_failed"
            if not xiaox_run:
                try:
                    lifecycle = self._execution_repo.lifecycle(execution.run_id)
                    failed_run = self._orchestrator_factory(repository).fail_dispatched_run(
                        execution.run_id, open_effects=bool(lifecycle.get("effects"))
                    )
                    if failed_run is not None:
                        state, code = dispatched_run_state(failed_run)
                        error_code = code or (error_code if state == "failed" else "")
                except WorkerLeaseLost:
                    abandon = True
                except BOUNDARY_ERRORS:
                    # Keep the lease recoverable when the durable projection failed.
                    abandon = True
                    logger.exception("agent task failure receipt could not be persisted")
        finally:
            _open_effect.reset(effect_token)
            if not abandon:
                finished = self._execution_repo.finish(
                    execution.run_id,
                    owner_id,
                    state,
                    error_code=error_code,
                )
                if finished is not None and finished.state == "succeeded":
                    from app.application.enterprise_cognition.outcomes import (
                        recover_terminal_outcome,
                    )

                    recover_terminal_outcome(execution.run_id, repository=self._run_repo)
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


def reconcile_interrupted_runs() -> int:
    """启动对账：收敛上一进程遗留的 running 任务（M15）。

    在重新认领执行之前恢复可证明安全的余步，其余中断任务保护停机；
    被动节点不启动 dispatcher，因此也不会误改运行状态。
    """
    from app.application.agent_orchestrator.stale_run_reconciler import (
        reconcile_stale_running_runs,
    )

    try:
        return reconcile_stale_running_runs()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("agent run startup reconciliation skipped: %s", exc)
        return 0


def start_agent_task_dispatcher() -> AgentTaskDispatcher:
    dispatcher = get_agent_task_dispatcher()
    reconciled = reconcile_interrupted_runs()
    if reconciled:
        logger.info("agent run startup reconciliation converged %s run(s)", reconciled)
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
    "reconcile_interrupted_runs",
    "set_agent_task_dispatcher_for_tests",
    "start_agent_task_dispatcher",
    "stop_agent_task_dispatcher",
]
