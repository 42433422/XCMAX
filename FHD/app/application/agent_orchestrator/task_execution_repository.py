"""Durable background queue and renewable execution leases for Agent tasks."""

from __future__ import annotations

import copy
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ExecutionState = Literal[
    "queued",
    "claimed",
    "paused",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]


def _task_id_of(run: AgentRun) -> str:
    context = run.metadata.get("task_context")
    if isinstance(context, dict):
        return str(context.get("task_id") or run.run_id)
    return run.run_id


def _deadline(now: str, seconds: float) -> str:
    parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=max(1.0, float(seconds)))).isoformat()


@dataclass
class AgentTaskExecution:
    run_id: str
    task_id: str
    user_id: str
    tenant_id: str = ""
    state: ExecutionState = "queued"
    priority: int = 100
    available_at: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    heartbeat_at: str = ""
    execution_count: int = 0
    recovery_count: int = 0
    requested_by: str = ""
    last_error_code: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, str | int]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "state": self.state,
            "priority": self.priority,
            "available_at": self.available_at,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "execution_count": self.execution_count,
            "recovery_count": self.recovery_count,
            "requested_by": self.requested_by,
            "last_error_code": self.last_error_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }


class TaskExecutionRepository(Protocol):
    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
    ) -> AgentTaskExecution: ...

    def get(self, run_id: str) -> AgentTaskExecution | None: ...

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]: ...

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> AgentTaskExecution | None: ...

    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> bool: ...

    def finish(
        self,
        run_id: str,
        owner_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None: ...

    def transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None: ...

    def clear(self) -> None: ...


class InMemoryTaskExecutionRepository:
    def __init__(self) -> None:
        self._rows: dict[str, AgentTaskExecution] = {}
        self._lock = threading.RLock()

    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
    ) -> AgentTaskExecution:
        now = utc_now_iso()
        with self._lock:
            row = self._rows.get(run.run_id)
            if row is None:
                row = AgentTaskExecution(
                    run_id=run.run_id,
                    task_id=_task_id_of(run),
                    user_id=run.user_id,
                    tenant_id=tenant_id_of_run(run),
                    created_at=now,
                )
            if row.state != "claimed":
                row.state = "queued"
                row.lease_owner = ""
                row.lease_expires_at = ""
                row.heartbeat_at = ""
                row.finished_at = ""
            row.priority = int(priority)
            row.available_at = now
            row.requested_by = str(requested_by or "")
            row.last_error_code = ""
            row.updated_at = now
            self._rows[row.run_id] = copy.deepcopy(row)
            return copy.deepcopy(row)

    def get(self, run_id: str) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            return copy.deepcopy(row) if row is not None else None

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]:
        wanted = {str(run_id or "") for run_id in run_ids if str(run_id or "")}
        with self._lock:
            return {
                run_id: copy.deepcopy(row) for run_id, row in self._rows.items() if run_id in wanted
            }

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> AgentTaskExecution | None:
        current = str(now or utc_now_iso())
        with self._lock:
            eligible = [
                row
                for row in self._rows.values()
                if row.available_at <= current
                and (
                    row.state == "queued"
                    or (
                        row.state == "claimed"
                        and bool(row.lease_expires_at)
                        and row.lease_expires_at <= current
                    )
                )
            ]
            if not eligible:
                return None
            eligible.sort(
                key=lambda row: (row.priority, row.available_at, row.created_at, row.run_id)
            )
            row = eligible[0]
            recovered = row.state == "claimed"
            row.state = "claimed"
            row.lease_owner = str(owner_id or "")
            row.lease_expires_at = _deadline(current, lease_seconds)
            row.heartbeat_at = current
            row.execution_count += 1
            row.recovery_count += int(recovered)
            row.updated_at = current
            self._rows[row.run_id] = copy.deepcopy(row)
            return copy.deepcopy(row)

    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> bool:
        current = str(now or utc_now_iso())
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None or row.state != "claimed" or row.lease_owner != owner_id:
                return False
            row.heartbeat_at = current
            row.lease_expires_at = _deadline(current, lease_seconds)
            row.updated_at = current
            return True

    def finish(
        self,
        run_id: str,
        owner_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None or row.state != "claimed" or row.lease_owner != owner_id:
                return None
            return self._transition_locked(row, state, error_code=error_code)

    def transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        with self._lock:
            row = self._rows.get(str(run_id or ""))
            if row is None:
                return None
            return self._transition_locked(row, state, error_code=error_code)

    def _transition_locked(
        self,
        row: AgentTaskExecution,
        state: str,
        *,
        error_code: str,
    ) -> AgentTaskExecution:
        now = utc_now_iso()
        row.state = str(state)  # type: ignore[assignment]
        row.lease_owner = ""
        row.lease_expires_at = ""
        row.heartbeat_at = ""
        row.last_error_code = str(error_code or "")[:64]
        row.updated_at = now
        if state in {"completed", "failed", "cancelled", "blocked"}:
            row.finished_at = now
        self._rows[row.run_id] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


class SQLAlchemyTaskExecutionRepository:
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

    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
    ) -> AgentTaskExecution:
        self._ensure_schema()
        now = utc_now_iso()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            record = db.get(AgentTaskExecutionRecord, run.run_id)
            if record is None:
                record = AgentTaskExecutionRecord(
                    run_id=run.run_id,
                    task_id=_task_id_of(run),
                    user_id=run.user_id,
                    tenant_id=tenant_id_of_run(run),
                    state="queued",
                    priority=int(priority),
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
            elif record.state != "claimed":
                record.state = "queued"
                record.lease_owner = None
                record.lease_expires_at = None
                record.heartbeat_at = None
                record.finished_at = None
            record.priority = int(priority)
            record.available_at = now
            record.requested_by = str(requested_by or "") or None
            record.last_error_code = None
            record.updated_at = now
        return self.get(run.run_id)  # type: ignore[return-value]

    def get(self, run_id: str) -> AgentTaskExecution | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            return self._to_model(record) if record is not None else None

    def list_for_run_ids(self, run_ids: list[str]) -> dict[str, AgentTaskExecution]:
        self._ensure_schema()
        wanted = sorted({str(run_id or "") for run_id in run_ids if str(run_id or "")})
        if not wanted:
            return {}
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            records = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.run_id.in_(wanted))
                .all()
            )
            return {str(record.run_id): self._to_model(record) for record in records}

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> AgentTaskExecution | None:
        self._ensure_schema()
        current = str(now or utc_now_iso())
        expires = _deadline(current, lease_seconds)
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            eligible = or_(
                AgentTaskExecutionRecord.state == "queued",
                and_(
                    AgentTaskExecutionRecord.state == "claimed",
                    AgentTaskExecutionRecord.lease_expires_at.is_not(None),
                    AgentTaskExecutionRecord.lease_expires_at <= current,
                ),
            )
            candidates = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.available_at <= current, eligible)
                .order_by(
                    AgentTaskExecutionRecord.priority.asc(),
                    AgentTaskExecutionRecord.available_at.asc(),
                    AgentTaskExecutionRecord.created_at.asc(),
                    AgentTaskExecutionRecord.run_id.asc(),
                )
                .limit(8)
                .all()
            )
            for candidate in candidates:
                recovered = candidate.state == "claimed"
                updated = (
                    db.query(AgentTaskExecutionRecord)
                    .filter(
                        AgentTaskExecutionRecord.run_id == candidate.run_id,
                        AgentTaskExecutionRecord.available_at <= current,
                        eligible,
                    )
                    .update(
                        {
                            AgentTaskExecutionRecord.state: "claimed",
                            AgentTaskExecutionRecord.lease_owner: str(owner_id or ""),
                            AgentTaskExecutionRecord.lease_expires_at: expires,
                            AgentTaskExecutionRecord.heartbeat_at: current,
                            AgentTaskExecutionRecord.execution_count: (
                                AgentTaskExecutionRecord.execution_count + 1
                            ),
                            AgentTaskExecutionRecord.recovery_count: (
                                AgentTaskExecutionRecord.recovery_count + int(recovered)
                            ),
                            AgentTaskExecutionRecord.updated_at: current,
                        },
                        synchronize_session=False,
                    )
                )
                if updated != 1:
                    continue
                db.flush()
                record = db.get(AgentTaskExecutionRecord, candidate.run_id)
                if record is not None:
                    db.refresh(record)
                    return self._to_model(record)
        return None

    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
    ) -> bool:
        self._ensure_schema()
        current = str(now or utc_now_iso())
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            updated = (
                db.query(AgentTaskExecutionRecord)
                .filter(
                    AgentTaskExecutionRecord.run_id == str(run_id or ""),
                    AgentTaskExecutionRecord.state == "claimed",
                    AgentTaskExecutionRecord.lease_owner == str(owner_id or ""),
                )
                .update(
                    {
                        AgentTaskExecutionRecord.heartbeat_at: current,
                        AgentTaskExecutionRecord.lease_expires_at: _deadline(
                            current, lease_seconds
                        ),
                        AgentTaskExecutionRecord.updated_at: current,
                    },
                    synchronize_session=False,
                )
            )
            return updated == 1

    def finish(
        self,
        run_id: str,
        owner_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        return self._transition(
            run_id,
            state,
            error_code=error_code,
            owner_id=owner_id,
            require_claim=True,
        )

    def transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> AgentTaskExecution | None:
        return self._transition(run_id, state, error_code=error_code)

    def _transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str,
        owner_id: str = "",
        require_claim: bool = False,
    ) -> AgentTaskExecution | None:
        self._ensure_schema()
        now = utc_now_iso()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            query = db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id == str(run_id or "")
            )
            if require_claim:
                query = query.filter(
                    AgentTaskExecutionRecord.state == "claimed",
                    AgentTaskExecutionRecord.lease_owner == str(owner_id or ""),
                )
            record = query.one_or_none()
            if record is None:
                return None
            record.state = str(state)
            record.lease_owner = None
            record.lease_expires_at = None
            record.heartbeat_at = None
            record.last_error_code = str(error_code or "")[:64] or None
            record.updated_at = now
            if state in {"completed", "failed", "cancelled", "blocked"}:
                record.finished_at = now
        return self.get(run_id)

    def clear(self) -> None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            db.query(AgentTaskExecutionRecord).delete()

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
                from app.db.models.agent import AgentTaskExecutionRecord

                Base.metadata.create_all(
                    bind=db.get_bind(),
                    tables=[AgentTaskExecutionRecord.__table__],
                    checkfirst=True,
                )
            self._schema_ready = True

    @staticmethod
    def _to_model(record) -> AgentTaskExecution:
        return AgentTaskExecution(
            run_id=str(record.run_id),
            task_id=str(record.task_id),
            user_id=str(record.user_id),
            tenant_id=str(record.tenant_id or ""),
            state=str(record.state),  # type: ignore[arg-type]
            priority=int(record.priority or 100),
            available_at=str(record.available_at or ""),
            lease_owner=str(record.lease_owner or ""),
            lease_expires_at=str(record.lease_expires_at or ""),
            heartbeat_at=str(record.heartbeat_at or ""),
            execution_count=int(record.execution_count or 0),
            recovery_count=int(record.recovery_count or 0),
            requested_by=str(record.requested_by or ""),
            last_error_code=str(record.last_error_code or ""),
            created_at=str(record.created_at or ""),
            updated_at=str(record.updated_at or ""),
            finished_at=str(record.finished_at or ""),
        )


_task_execution_repository: TaskExecutionRepository | None = None


def get_task_execution_repository() -> TaskExecutionRepository:
    global _task_execution_repository
    if _task_execution_repository is None:
        try:
            repository = SQLAlchemyTaskExecutionRepository()
            repository.get("")
            _task_execution_repository = repository
        except RECOVERABLE_ERRORS as exc:
            require_durable = os.environ.get(
                "XCAGI_AGENT_RUN_REQUIRE_DURABLE", ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            if require_durable:
                raise RuntimeError("durable task execution queue unavailable") from exc
            logger.warning("Task execution SQL queue unavailable, using memory: %s", exc)
            _task_execution_repository = InMemoryTaskExecutionRepository()
    return _task_execution_repository


def set_task_execution_repository_for_tests(
    repository: TaskExecutionRepository | None,
) -> None:
    global _task_execution_repository
    _task_execution_repository = repository


__all__ = [
    "AgentTaskExecution",
    "ExecutionState",
    "InMemoryTaskExecutionRepository",
    "SQLAlchemyTaskExecutionRepository",
    "TaskExecutionRepository",
    "get_task_execution_repository",
    "set_task_execution_repository_for_tests",
]
