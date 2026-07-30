from __future__ import annotations

import contextvars
import logging
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)

logger = logging.getLogger(__name__)

ControlAction = Literal["pause", "cancel"]

ACTIVE_RUN_STATUSES = {"queued", "planning", "running", "retrying"}
TERMINAL_RUN_STATUSES = {"blocked", "completed", "failed", "cancelled"}


def _max_workers() -> int:
    try:
        return max(1, min(int(os.environ.get("XCAGI_AGENT_RUN_WORKERS", "3")), 8))
    except (TypeError, ValueError):
        return 3


class _RunControl:
    def __init__(self) -> None:
        self.pause_requested = threading.Event()
        self.cancel_requested = threading.Event()


class AgentRunRuntime:
    """Process-local workers backed by durable AgentRun checkpoints."""

    def __init__(
        self,
        *,
        repository: AgentRunRepository | None = None,
        max_workers: int | None = None,
    ) -> None:
        self._repo = repository or get_agent_run_repository()
        self._max_workers = max_workers or _max_workers()
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[Any]] = {}
        self._controls: dict[str, _RunControl] = {}
        self._lock = threading.RLock()
        self._started = False
        self._worker_instance_id = f"worker_{os.getpid()}_{uuid.uuid4().hex[:10]}"

    def start(self, *, recover: bool = True) -> dict[str, int]:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="xcagi-agent-run",
                )
            already_started = self._started
            self._started = True
        if recover and not already_started:
            return self.recover_incomplete_runs()
        return {"recovered": 0, "waiting_user": 0, "cancelled": 0}

    def stop(self, *, wait: bool = False) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
            self._started = False
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)

    def submit(self, run_id: str) -> AgentRun | None:
        normalized = str(run_id or "").strip()
        if not normalized:
            return None
        self.start(recover=False)
        run = self._repo.get(normalized)
        if run is None or run.status in TERMINAL_RUN_STATUSES | {"paused", "waiting_user"}:
            return run

        with self._lock:
            existing = self._futures.get(normalized)
            if existing is not None and not existing.done():
                return run
            control = self._controls.setdefault(normalized, _RunControl())
            control.pause_requested.clear()
            control.cancel_requested.clear()

            runtime = self._runtime_metadata(run)
            runtime.update(
                {
                    "mode": "background",
                    "queue_state": "queued",
                    "queued_at": utc_now_iso(),
                    "worker_instance_id": self._worker_instance_id,
                }
            )
            run.metadata["background_execution"] = True
            if run.status not in {"planning", "running", "retrying"}:
                run.status = "queued"
            run.add_event(
                "run.queued",
                "任务已进入后台队列",
                {"worker_instance_id": self._worker_instance_id},
            )
            run = self._repo.save(run)

            ctx = contextvars.copy_context()
            future = self._executor.submit(ctx.run, self._execute, normalized)
            self._futures[normalized] = future
            future.add_done_callback(lambda completed, rid=normalized: self._forget(rid, completed))
        return run

    def request_pause(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return run
        control = self._control(run.run_id)
        control.pause_requested.set()
        runtime = self._runtime_metadata(run)
        runtime["pause_requested"] = True
        runtime["pause_requested_at"] = utc_now_iso()
        run.add_event(
            "run.pause_requested",
            "已请求暂停，当前步骤结束后生效",
            {"requested_by": requested_by},
        )
        with self._lock:
            future = self._futures.get(run.run_id)
            active = future is not None and not future.done()
        if not active and run.status in {"queued", "planning", "retrying", "running"}:
            run.status = "paused"
            runtime["queue_state"] = "paused"
            run.add_event("run.paused", "后台任务已暂停", {"requested_by": requested_by})
        return self._repo.save(run)

    def resume(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return run
        control = self._control(run.run_id)
        control.pause_requested.clear()
        control.cancel_requested.clear()
        runtime = self._runtime_metadata(run)
        runtime["pause_requested"] = False
        runtime["cancel_requested"] = False
        runtime["resumed_at"] = utc_now_iso()
        runtime["queue_state"] = "queued"
        run.status = "queued"
        run.error = ""
        run.add_event("run.resumed", "后台任务已恢复", {"requested_by": requested_by})
        saved = self._repo.save(run)
        return self.submit(saved.run_id)

    def cancel(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return run
        control = self._control(run.run_id)
        control.cancel_requested.set()
        runtime = self._runtime_metadata(run)
        runtime["cancel_requested"] = True
        runtime["cancel_requested_at"] = utc_now_iso()
        run.add_event(
            "run.cancel_requested",
            "已请求取消，当前步骤结束后停止",
            {"requested_by": requested_by},
        )
        with self._lock:
            future = self._futures.get(run.run_id)
            active = future is not None and not future.done()
        if not active:
            run.status = "cancelled"
            runtime["queue_state"] = "cancelled"
            run.add_event("run.cancelled", "后台任务已取消", {"requested_by": requested_by})
        return self._repo.save(run)

    def retry(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status not in TERMINAL_RUN_STATUSES:
            return run
        for step in run.steps:
            if step.status == "completed":
                continue
            step.status = "pending"
            step.output = {}
            step.error = ""
            step.started_at = ""
            step.finished_at = ""
            step.duration_ms = 0
        run.status = "queued"
        run.error = ""
        run.final_output = {}
        runtime = self._runtime_metadata(run)
        runtime["pause_requested"] = False
        runtime["cancel_requested"] = False
        runtime["queue_state"] = "queued"
        runtime["retried_at"] = utc_now_iso()
        run.add_event("run.retry_requested", "后台任务已重新入队", {"requested_by": requested_by})
        self._repo.save(run)
        return self.submit(run.run_id)

    def control_action(self, run_id: str) -> ControlAction | None:
        control = self._control(run_id)
        if control.cancel_requested.is_set():
            return "cancel"
        if control.pause_requested.is_set():
            return "pause"
        persisted = self._repo.get(run_id)
        if persisted is None:
            return "cancel"
        runtime = persisted.metadata.get("runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        if bool(runtime.get("cancel_requested")):
            control.cancel_requested.set()
            return "cancel"
        if bool(runtime.get("pause_requested")):
            control.pause_requested.set()
            return "pause"
        return None

    def recover_incomplete_runs(self) -> dict[str, int]:
        counts = {"recovered": 0, "waiting_user": 0, "cancelled": 0}
        runs = self._repo.list_by_status(ACTIVE_RUN_STATUSES, limit=1000)
        for run in runs:
            runtime = self._runtime_metadata(run)
            if bool(runtime.get("cancel_requested")):
                run.status = "cancelled"
                runtime["queue_state"] = "cancelled"
                run.add_event("run.cancelled", "重启恢复时完成取消")
                self._repo.save(run)
                counts["cancelled"] += 1
                continue
            if bool(runtime.get("pause_requested")):
                run.status = "paused"
                runtime["queue_state"] = "paused"
                run.add_event("run.paused", "重启后保持暂停")
                self._repo.save(run)
                continue

            unsafe_step = False
            for step in run.steps:
                if step.status != "running":
                    continue
                for call in run.tool_calls:
                    if call.step_id == step.step_id and call.status == "running":
                        call.status = "failed"
                        call.error = "worker restart interrupted the tool call"
                        call.finished_at = utc_now_iso()
                        call.metadata["interrupted_by_restart"] = True
                step.output = {}
                step.error = "上次运行在该步骤中断"
                if step.idempotent:
                    step.status = "pending"
                    run.add_event(
                        "step.recovered",
                        f"幂等步骤 {step.node_id} 将从检查点重试",
                        {"step_id": step.step_id, "node_id": step.node_id},
                    )
                else:
                    step.status = "waiting_user"
                    unsafe_step = True
                    run.add_event(
                        "step.recovery_confirmation_required",
                        f"步骤 {step.node_id} 可能已产生副作用，需要确认后重试",
                        {
                            "step_id": step.step_id,
                            "node_id": step.node_id,
                            "tool_id": step.tool_id,
                            "action": step.action,
                        },
                    )
            runtime["recovered_at"] = utc_now_iso()
            runtime["previous_worker_instance_id"] = runtime.get("worker_instance_id")
            runtime["worker_instance_id"] = self._worker_instance_id
            if unsafe_step:
                run.status = "waiting_user"
                runtime["queue_state"] = "waiting_user"
                self._repo.save(run)
                counts["waiting_user"] += 1
                continue
            run.status = "queued"
            runtime["queue_state"] = "queued"
            run.add_event(
                "run.recovered",
                "后台任务已从持久检查点恢复",
                {"worker_instance_id": self._worker_instance_id},
            )
            self._repo.save(run)
            self.submit(run.run_id)
            counts["recovered"] += 1
        return counts

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = sorted(
                run_id
                for run_id, future in self._futures.items()
                if not future.done()
            )
        queued = self._repo.list_by_status(ACTIVE_RUN_STATUSES | {"paused", "waiting_user"})
        counts: dict[str, int] = {}
        for run in queued:
            counts[run.status] = counts.get(run.status, 0) + 1
        return {
            "started": self._started,
            "worker_instance_id": self._worker_instance_id,
            "max_workers": self._max_workers,
            "active_run_ids": active,
            "status_counts": counts,
        }

    def _execute(self, run_id: str) -> None:
        run = self._repo.get(run_id)
        if run is None:
            return
        runtime = self._runtime_metadata(run)
        runtime.update(
            {
                "queue_state": "running",
                "worker_instance_id": self._worker_instance_id,
                "worker_started_at": utc_now_iso(),
                "lease_expires_at": (
                    datetime.now(UTC) + timedelta(minutes=10)
                ).isoformat(),
            }
        )
        run.add_event(
            "run.background_started",
            "后台执行器已接管任务",
            {"worker_instance_id": self._worker_instance_id},
        )
        self._repo.save(run)
        try:
            from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

            AgentOrchestrator(repository=self._repo).execute_existing_run(
                run_id,
                control_check=lambda current: self.control_action(current.run_id),
                worker_instance_id=self._worker_instance_id,
            )
        except Exception as exc:  # noqa: BLE001 - worker must persist terminal failure
            logger.exception("background AgentRun failed: run_id=%s", run_id)
            failed = self._repo.get(run_id)
            if failed is None or failed.status in TERMINAL_RUN_STATUSES:
                return
            failed.status = "failed"
            failed.error = str(exc)
            runtime = self._runtime_metadata(failed)
            runtime["queue_state"] = "failed"
            runtime["worker_finished_at"] = utc_now_iso()
            failed.add_event("run.failed", "后台任务执行失败", {"error": str(exc)})
            self._repo.save(failed)

    def _forget(self, run_id: str, future: Future[Any]) -> None:
        with self._lock:
            if self._futures.get(run_id) is future:
                self._futures.pop(run_id, None)

    def _control(self, run_id: str) -> _RunControl:
        with self._lock:
            return self._controls.setdefault(str(run_id), _RunControl())

    @staticmethod
    def _runtime_metadata(run: AgentRun) -> dict[str, Any]:
        runtime = run.metadata.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {}
            run.metadata["runtime"] = runtime
        runtime.setdefault("schema_version", "1.0")
        return runtime


_agent_run_runtime: AgentRunRuntime | None = None
_runtime_lock = threading.RLock()


def get_agent_run_runtime() -> AgentRunRuntime:
    global _agent_run_runtime
    with _runtime_lock:
        if _agent_run_runtime is None:
            _agent_run_runtime = AgentRunRuntime()
        return _agent_run_runtime


def start_agent_run_runtime() -> dict[str, int]:
    return get_agent_run_runtime().start(recover=True)


def stop_agent_run_runtime() -> None:
    get_agent_run_runtime().stop(wait=False)
