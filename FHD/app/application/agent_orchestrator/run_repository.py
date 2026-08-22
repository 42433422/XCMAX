from __future__ import annotations

import copy
import logging
import os
import threading
from typing import Protocol

from app.application.agent_orchestrator.run_models import (
    AgentRun,
    RunEvent,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.task_models import (
    AgentTask,
    TaskControlCommand,
    task_from_run,
    tenant_id_of_run,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class AgentRunRepository(Protocol):
    def save(self, run: AgentRun) -> AgentRun: ...

    def get(self, run_id: str) -> AgentRun | None: ...

    def list_recent(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]: ...

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[AgentRun]: ...

    def save_task(self, task: AgentTask) -> AgentTask: ...

    def get_task(
        self, *, user_id: str, task_id: str, tenant_id: str | None = None
    ) -> AgentTask | None: ...

    def list_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[AgentTask]: ...

    def archive_task(
        self,
        *,
        user_id: str,
        task_id: str,
        archived_at: str,
        tenant_id: str | None = None,
    ) -> AgentTask | None: ...

    def request_task_control(
        self, run_id: str, action: str, *, requested_by: str = ""
    ) -> TaskControlCommand: ...

    def latest_task_control(self, run_id: str) -> TaskControlCommand | None: ...

    def mark_task_control(
        self, command_id: str, status: str, *, applied_at: str = ""
    ) -> TaskControlCommand | None: ...

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]: ...

    def clear(self) -> None: ...


class InMemoryAgentRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._tasks: dict[tuple[str, str, str], AgentTask] = {}
        self._commands: dict[str, TaskControlCommand] = {}
        self._lock = threading.RLock()

    def save(self, run: AgentRun) -> AgentRun:
        from app.application.agent_orchestrator.business_harness import (
            ensure_terminal_business_result,
        )

        ensure_terminal_business_result(run)
        run.touch()
        with self._lock:
            self._runs[run.run_id] = copy.deepcopy(run)
            key = self._task_key(
                tenant_id_of_run(run),
                run.user_id,
                self._run_task_id(run),
            )
            self._tasks[key] = copy.deepcopy(task_from_run(run, existing=self._tasks.get(key)))
            return copy.deepcopy(run)

    def get(self, run_id: str) -> AgentRun | None:
        with self._lock:
            run = self._runs.get(str(run_id or ""))
            return copy.deepcopy(run) if run is not None else None

    def list_recent(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        with self._lock:
            runs = list(self._runs.values())
        if user_id is not None:
            runs = [run for run in runs if run.user_id == user_id]
        runs.sort(key=lambda run: run.updated_at, reverse=True)
        return [copy.deepcopy(run) for run in runs[: max(0, int(limit))]]

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[AgentRun]:
        wanted_user = str(user_id or "")
        wanted_task = str(task_id or "")
        with self._lock:
            runs = [
                copy.deepcopy(run)
                for run in self._runs.values()
                if run.user_id == wanted_user
                and isinstance(run.metadata.get("task_context"), dict)
                and str(run.metadata["task_context"].get("task_id") or "") == wanted_task
            ]
        runs.sort(key=lambda run: (run.created_at, run.run_id))
        return runs

    def save_task(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self._tasks[self._task_key(task.tenant_id, task.user_id, task.task_id)] = copy.deepcopy(
                task
            )
        return copy.deepcopy(task)

    def get_task(
        self, *, user_id: str, task_id: str, tenant_id: str | None = None
    ) -> AgentTask | None:
        with self._lock:
            if tenant_id is not None:
                task = self._tasks.get(self._task_key(tenant_id, user_id, task_id))
                return copy.deepcopy(task) if task is not None else None
            matches = [
                task
                for (_, owner, candidate_task_id), task in self._tasks.items()
                if owner == str(user_id or "") and candidate_task_id == str(task_id or "")
            ]
            if len(matches) != 1:
                return None
            return copy.deepcopy(matches[0])

    def list_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[AgentTask]:
        with self._lock:
            tasks = [task for (_, owner, _), task in self._tasks.items() if owner == str(user_id)]
        if tenant_id is not None:
            tasks = [task for task in tasks if task.tenant_id == tenant_id]
        if not include_archived:
            tasks = [task for task in tasks if not task.archived_at]
        tasks.sort(key=lambda task: (task.updated_at, task.task_id), reverse=True)
        return [copy.deepcopy(task) for task in tasks[: max(0, int(limit))]]

    def archive_task(
        self,
        *,
        user_id: str,
        task_id: str,
        archived_at: str,
        tenant_id: str | None = None,
    ) -> AgentTask | None:
        with self._lock:
            task = self.get_task(user_id=user_id, task_id=task_id, tenant_id=tenant_id)
            if task is None:
                return None
            task.archived_at = archived_at
            task.touch()
            key = self._task_key(task.tenant_id, task.user_id, task.task_id)
            self._tasks[key] = copy.deepcopy(task)
            return copy.deepcopy(task)

    def request_task_control(
        self, run_id: str, action: str, *, requested_by: str = ""
    ) -> TaskControlCommand:
        with self._lock:
            run = self._runs.get(str(run_id or ""))
            task_id = self._run_task_id(run) if run is not None else ""
            now = utc_now_iso()
            for previous in self._commands.values():
                if previous.run_id == str(run_id or "") and previous.status == "requested":
                    previous.status = "superseded"
                    previous.applied_at = now
            command = TaskControlCommand(
                task_id=task_id,
                run_id=str(run_id or ""),
                action=str(action),  # type: ignore[arg-type]
                requested_by=requested_by,
            )
            self._commands[command.command_id] = copy.deepcopy(command)
            return copy.deepcopy(command)

    def latest_task_control(self, run_id: str) -> TaskControlCommand | None:
        with self._lock:
            commands = [
                command
                for command in self._commands.values()
                if command.run_id == str(run_id or "")
            ]
        if not commands:
            return None
        commands.sort(key=lambda command: (command.created_at, command.command_id), reverse=True)
        return copy.deepcopy(commands[0])

    def mark_task_control(
        self, command_id: str, status: str, *, applied_at: str = ""
    ) -> TaskControlCommand | None:
        with self._lock:
            command = self._commands.get(str(command_id or ""))
            if command is None:
                return None
            command.status = str(status)  # type: ignore[assignment]
            command.applied_at = applied_at
            self._commands[command.command_id] = copy.deepcopy(command)
            return copy.deepcopy(command)

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]:
        run = self.get(run_id)
        if run is None:
            return []
        events = run.events
        if after_event_id:
            for idx, event in enumerate(events):
                if event.event_id == after_event_id:
                    events = events[idx + 1 :]
                    break
        return [copy.deepcopy(event) for event in events]

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._tasks.clear()
            self._commands.clear()

    @staticmethod
    def _task_key(tenant_id: str, user_id: str, task_id: str) -> tuple[str, str, str]:
        return str(tenant_id or ""), str(user_id or ""), str(task_id or "")

    @staticmethod
    def _run_task_id(run: AgentRun | None) -> str:
        if run is None:
            return ""
        context = run.metadata.get("task_context")
        if isinstance(context, dict):
            return str(context.get("task_id") or run.run_id)
        return run.run_id


_agent_run_repository: AgentRunRepository | None = None
_agent_run_repository_status: dict[str, str | bool] = {
    "mode": "uninitialized",
    "durable": False,
    "degraded_reason": "",
}


def get_agent_run_repository() -> AgentRunRepository:
    global _agent_run_repository, _agent_run_repository_status
    if _agent_run_repository is None:
        try:
            _agent_run_repository = SQLAlchemyAgentRunRepository()
            _agent_run_repository.list_recent(limit=1)
            _agent_run_repository_status = {
                "mode": "sqlalchemy",
                "durable": True,
                "degraded_reason": "",
            }
        except RECOVERABLE_ERRORS as exc:
            require_durable = os.environ.get(
                "XCAGI_AGENT_RUN_REQUIRE_DURABLE", ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            if require_durable:
                raise RuntimeError(
                    f"durable AgentRun repository is required but unavailable: {exc}"
                ) from exc
            logger.warning("AgentRun SQL repository unavailable, using memory store: %s", exc)
            _agent_run_repository = InMemoryAgentRunRepository()
            _agent_run_repository_status = {
                "mode": "memory",
                "durable": False,
                "degraded_reason": str(exc),
            }
    return _agent_run_repository


def get_agent_run_repository_status() -> dict[str, str | bool]:
    get_agent_run_repository()
    return dict(_agent_run_repository_status)


def set_agent_run_repository_for_tests(repository: AgentRunRepository | None) -> None:
    global _agent_run_repository, _agent_run_repository_status
    _agent_run_repository = repository
    _agent_run_repository_status = {
        "mode": "memory" if isinstance(repository, InMemoryAgentRunRepository) else "uninitialized",
        "durable": False,
        "degraded_reason": "",
    }
