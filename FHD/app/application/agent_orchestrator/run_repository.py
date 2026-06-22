from __future__ import annotations

import copy
import json
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import AgentRun, RunEvent, agent_run_from_dict
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class AgentRunRepository(Protocol):
    def save(self, run: AgentRun) -> AgentRun: ...

    def get(self, run_id: str) -> AgentRun | None: ...

    def list_recent(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]: ...

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]: ...

    def clear(self) -> None: ...


class InMemoryAgentRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._lock = threading.RLock()

    def save(self, run: AgentRun) -> AgentRun:
        run.touch()
        with self._lock:
            self._runs[run.run_id] = copy.deepcopy(run)
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
            from app.db.models.agent import AgentRunRecord

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
            from app.db.models.agent import AgentRunRecord

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
                from app.db.models.agent import AgentRunRecord

                Base.metadata.create_all(
                    bind=db.get_bind(),
                    tables=[AgentRunRecord.__table__],
                    checkfirst=True,
                )
            self._schema_ready = True

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


def get_agent_run_repository() -> AgentRunRepository:
    global _agent_run_repository
    if _agent_run_repository is None:
        try:
            _agent_run_repository = SQLAlchemyAgentRunRepository()
            _agent_run_repository.list_recent(limit=1)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("AgentRun SQL repository unavailable, using memory store: %s", exc)
            _agent_run_repository = InMemoryAgentRunRepository()
    return _agent_run_repository
