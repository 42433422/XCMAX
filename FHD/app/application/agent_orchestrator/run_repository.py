from __future__ import annotations

import copy
import json
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import (
    AgentRun,
    RunEvent,
    agent_run_from_dict,
    utc_now_iso,
)
from app.application.agent_orchestrator.task_models import (
    AgentTask,
    TaskControlCommand,
    agent_task_from_dict,
    task_control_from_dict,
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


class SQLAlchemyAgentRunRepository:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        auto_create: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._auto_create = auto_create
        self._schema_ready = False
        self._schema_lock = threading.RLock()

    def save(self, run: AgentRun) -> AgentRun:
        self._ensure_schema()
        run.touch()
        payload = json.dumps(run.to_dict(), ensure_ascii=False, default=str)
        with self._session_scope() as db:
            from app.db.models.agent import AgentRunRecord, AgentTaskRecord

            record = db.get(AgentRunRecord, run.run_id)
            if record is None:
                record = AgentRunRecord(
                    run_id=run.run_id,
                    user_id=run.user_id,
                    status=run.status,
                    intent=run.intent or None,
                    plan_id=run.plan_id or None,
                    message=run.message,
                    payload_json=payload,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
                db.add(record)
            else:
                record.user_id = run.user_id
                record.status = run.status
                record.intent = run.intent or None
                record.plan_id = run.plan_id or None
                record.message = run.message
                record.payload_json = payload
                record.created_at = run.created_at
                record.updated_at = run.updated_at
            existing_task_record = (
                db.query(AgentTaskRecord)
                .filter(
                    AgentTaskRecord.tenant_id == tenant_id_of_run(run),
                    AgentTaskRecord.user_id == run.user_id,
                    AgentTaskRecord.task_id == self._run_task_id(run),
                )
                .one_or_none()
            )
            existing_task = (
                self._task_record_to_model(existing_task_record)
                if existing_task_record is not None
                else None
            )
            self._save_task_record(db, task_from_run(run, existing=existing_task))
        return self.get(run.run_id) or copy.deepcopy(run)

    def get(self, run_id: str) -> AgentRun | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            record = db.get(AgentRunRecord, str(run_id or ""))
            return self._record_to_run(record) if record is not None else None

    def list_recent(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            query = db.query(AgentRunRecord)
            if user_id is not None:
                query = query.filter(AgentRunRecord.user_id == str(user_id))
            records = (
                query.order_by(AgentRunRecord.updated_at.desc()).limit(max(0, int(limit))).all()
            )
            return [run for record in records if (run := self._record_to_run(record)) is not None]

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[AgentRun]:
        """Resolve a durable task without relying on a recent-run window.

        ``task_id`` currently lives in the versioned AgentRun payload.  Scanning one
        principal's rows is intentionally slower than adding an un-migrated shadow
        index, but it keeps idempotency correct for old tasks as well as recent ones.
        """
        self._ensure_schema()
        wanted_task = str(task_id or "")
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            records = (
                db.query(AgentRunRecord)
                .filter(AgentRunRecord.user_id == str(user_id or ""))
                .order_by(AgentRunRecord.created_at.asc(), AgentRunRecord.run_id.asc())
                .all()
            )
            runs: list[AgentRun] = []
            for record in records:
                run = self._record_to_run(record)
                if run is None:
                    continue
                context = run.metadata.get("task_context")
                if isinstance(context, dict) and str(context.get("task_id") or "") == wanted_task:
                    runs.append(run)
            return runs

    def save_task(self, task: AgentTask) -> AgentTask:
        self._ensure_schema()
        with self._session_scope() as db:
            self._save_task_record(db, task)
        return self.get_task(
            user_id=task.user_id,
            task_id=task.task_id,
            tenant_id=task.tenant_id,
        ) or copy.deepcopy(task)

    def get_task(
        self, *, user_id: str, task_id: str, tenant_id: str | None = None
    ) -> AgentTask | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskRecord

            query = db.query(AgentTaskRecord).filter(
                AgentTaskRecord.user_id == str(user_id or ""),
                AgentTaskRecord.task_id == str(task_id or ""),
            )
            if tenant_id is not None:
                query = query.filter(AgentTaskRecord.tenant_id == str(tenant_id))
            records = query.limit(2).all()
            if len(records) != 1:
                return None
            return self._task_record_to_model(records[0])

    def list_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[AgentTask]:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskRecord

            query = db.query(AgentTaskRecord).filter(AgentTaskRecord.user_id == str(user_id or ""))
            if tenant_id is not None:
                query = query.filter(AgentTaskRecord.tenant_id == str(tenant_id))
            if not include_archived:
                query = query.filter(
                    (AgentTaskRecord.archived_at.is_(None)) | (AgentTaskRecord.archived_at == "")
                )
            records = (
                query.order_by(AgentTaskRecord.updated_at.desc(), AgentTaskRecord.task_id.desc())
                .limit(max(0, int(limit)))
                .all()
            )
            return [self._task_record_to_model(record) for record in records]

    def archive_task(
        self,
        *,
        user_id: str,
        task_id: str,
        archived_at: str,
        tenant_id: str | None = None,
    ) -> AgentTask | None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskRecord

            record = db.query(AgentTaskRecord).filter(
                AgentTaskRecord.user_id == str(user_id or ""),
                AgentTaskRecord.task_id == str(task_id or ""),
            )
            if tenant_id is not None:
                record = record.filter(AgentTaskRecord.tenant_id == str(tenant_id))
            records = record.limit(2).all()
            if len(records) != 1:
                return None
            record = records[0]
            record.archived_at = str(archived_at or "") or None
            record.updated_at = str(archived_at or record.updated_at)
        return self.get_task(user_id=user_id, task_id=task_id, tenant_id=tenant_id)

    def request_task_control(
        self, run_id: str, action: str, *, requested_by: str = ""
    ) -> TaskControlCommand:
        self._ensure_schema()
        run = self.get(run_id)
        command = TaskControlCommand(
            task_id=self._run_task_id(run),
            run_id=str(run_id or ""),
            action=str(action),  # type: ignore[arg-type]
            requested_by=str(requested_by or ""),
        )
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskCommandRecord

            superseded_at = utc_now_iso()
            requested = (
                db.query(AgentTaskCommandRecord)
                .filter(
                    AgentTaskCommandRecord.run_id == str(run_id or ""),
                    AgentTaskCommandRecord.status == "requested",
                )
                .all()
            )
            for previous in requested:
                previous.status = "superseded"
                previous.applied_at = superseded_at
            db.add(
                AgentTaskCommandRecord(
                    command_id=command.command_id,
                    task_id=command.task_id,
                    run_id=command.run_id,
                    action=command.action,
                    status=command.status,
                    requested_by=command.requested_by or None,
                    metadata_json=json.dumps(command.metadata, ensure_ascii=False, default=str),
                    created_at=command.created_at,
                    applied_at=command.applied_at or None,
                )
            )
        return command

    def latest_task_control(self, run_id: str) -> TaskControlCommand | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskCommandRecord

            record = (
                db.query(AgentTaskCommandRecord)
                .filter(AgentTaskCommandRecord.run_id == str(run_id or ""))
                .order_by(
                    AgentTaskCommandRecord.created_at.desc(),
                    AgentTaskCommandRecord.command_id.desc(),
                )
                .first()
            )
            return self._command_record_to_model(record) if record is not None else None

    def mark_task_control(
        self, command_id: str, status: str, *, applied_at: str = ""
    ) -> TaskControlCommand | None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskCommandRecord

            record = db.get(AgentTaskCommandRecord, str(command_id or ""))
            if record is None:
                return None
            record.status = str(status or "requested")
            record.applied_at = str(applied_at or "") or None
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskCommandRecord

            updated = db.get(AgentTaskCommandRecord, str(command_id or ""))
            return self._command_record_to_model(updated) if updated is not None else None

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
        return events

    def clear(self) -> None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskRecord

            db.query(AgentTaskCommandRecord).delete()
            db.query(AgentTaskRecord).delete()
            db.query(AgentRunRecord).delete()

    @contextmanager
    def _session_scope(self, *, read_only: bool = False) -> Iterator[Session]:
        session_factory = self._session_factory
        if session_factory is None:
            from app.db import SessionLocal

            session_factory = SessionLocal
        db = session_factory()
        try:
            yield db
            if not read_only:
                db.commit()
        except RECOVERABLE_ERRORS:
            if not read_only:
                db.rollback()
            raise
        finally:
            db.close()

    def _ensure_schema(self) -> None:
        if not self._auto_create or self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._session_scope(read_only=True) as db:
                from app.db.base import Base
                from app.db.models.agent import (
                    AgentRunRecord,
                    AgentTaskCommandRecord,
                    AgentTaskRecord,
                )

                Base.metadata.create_all(
                    bind=db.get_bind(),
                    tables=[
                        AgentRunRecord.__table__,
                        AgentTaskRecord.__table__,
                        AgentTaskCommandRecord.__table__,
                    ],
                    checkfirst=True,
                )
            self._schema_ready = True

    @staticmethod
    def _run_task_id(run: AgentRun | None) -> str:
        if run is None:
            return ""
        context = run.metadata.get("task_context")
        if isinstance(context, dict):
            return str(context.get("task_id") or run.run_id)
        return run.run_id

    @staticmethod
    def _save_task_record(db: Session, task: AgentTask) -> None:
        from app.db.models.agent import AgentTaskRecord

        record = (
            db.query(AgentTaskRecord)
            .filter(
                AgentTaskRecord.tenant_id == task.tenant_id,
                AgentTaskRecord.user_id == task.user_id,
                AgentTaskRecord.task_id == task.task_id,
            )
            .one_or_none()
        )
        values = task.to_dict()
        if record is None:
            record = AgentTaskRecord(
                task_id=task.task_id,
                user_id=task.user_id,
                title=task.title,
                status=task.status,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            db.add(record)
        record.tenant_id = task.tenant_id
        record.title = task.title
        record.source = task.source
        record.task_type = task.task_type
        record.status = task.status
        record.attention_state = task.attention_state
        record.active_run_id = task.active_run_id or None
        record.root_run_id = task.root_run_id or None
        record.conversation_id = task.conversation_id or None
        record.workspace_id = task.workspace_id or None
        record.workspace_path = task.workspace_path or None
        record.workspace_isolation = task.workspace_isolation
        record.attempt = task.attempt
        record.run_count = task.run_count
        record.archived_at = task.archived_at or None
        record.metadata_json = json.dumps(values["metadata"], ensure_ascii=False, default=str)
        record.created_at = task.created_at
        record.updated_at = task.updated_at

    @staticmethod
    def _task_record_to_model(record) -> AgentTask:
        return agent_task_from_dict(
            {
                "task_id": record.task_id,
                "user_id": record.user_id,
                "tenant_id": record.tenant_id,
                "title": record.title,
                "source": record.source,
                "task_type": record.task_type,
                "status": record.status,
                "attention_state": record.attention_state,
                "active_run_id": record.active_run_id,
                "root_run_id": record.root_run_id,
                "conversation_id": record.conversation_id,
                "workspace_id": record.workspace_id,
                "workspace_path": record.workspace_path,
                "workspace_isolation": record.workspace_isolation,
                "attempt": record.attempt,
                "run_count": record.run_count,
                "archived_at": record.archived_at,
                "metadata": json.loads(record.metadata_json or "{}"),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    @staticmethod
    def _command_record_to_model(record) -> TaskControlCommand:
        return task_control_from_dict(
            {
                "command_id": record.command_id,
                "task_id": record.task_id,
                "run_id": record.run_id,
                "action": record.action,
                "status": record.status,
                "requested_by": record.requested_by,
                "metadata": json.loads(record.metadata_json or "{}"),
                "created_at": record.created_at,
                "applied_at": record.applied_at,
            }
        )

    @staticmethod
    def _record_to_run(record) -> AgentRun | None:
        try:
            data = json.loads(record.payload_json or "{}")
            if isinstance(data, dict):
                return agent_run_from_dict(data)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("agent run payload invalid: %s", exc)
        return None


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
