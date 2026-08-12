"""SQLAlchemy implementation of the durable Agent task execution queue."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_execution_models import (
    AgentTaskExecution,
    _deadline,
    _task_id_of,
)
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.utils.operational_errors import RECOVERABLE_ERRORS


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


__all__ = ["SQLAlchemyTaskExecutionRepository"]
