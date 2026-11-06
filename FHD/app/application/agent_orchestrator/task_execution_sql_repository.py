"""SQLAlchemy implementation of the durable Agent task execution queue."""

from __future__ import annotations

import random
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Table, and_, or_
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_execution_models import (
    AgentTaskExecution,
    ExecutionState,
    _deadline,
    _task_id_of,
)
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.domain.task_lifecycle.adapters import (
    LEASED_STATES,
    WAITING_STATES,
    canonical_execution_state,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class SQLAlchemyTaskExecutionRepository:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        auto_create: bool = True,
        jitter_ratio: float = 0.2,
        approval_timeout_seconds: float = 86400.0,
        rng: random.Random | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._auto_create = auto_create
        self._jitter_ratio = jitter_ratio
        self._approval_timeout_seconds = approval_timeout_seconds
        self._rng = rng or random.Random()
        self._schema_ready = False
        self._schema_bind: object | None = None
        self._schema_lock = threading.RLock()

    def enqueue(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        idempotency_key: str = "",
        fingerprint: str = "",
    ) -> AgentTaskExecution:
        self._ensure_schema()
        prior = ""
        with self._session_scope() as db:
            if idempotency_key:
                from app.domain.task_lifecycle.control import SessionBook

                prior = SessionBook(db).claim_key(
                    "agent",
                    tenant_id_of_run(run),
                    idempotency_key,
                    fingerprint or run.message,
                    run.run_id,
                )
            if not prior:
                self.enqueue_in_session(db, run, requested_by=requested_by, priority=priority)
        return cast(AgentTaskExecution, self.get(prior or run.run_id))

    def enqueue_in_session(
        self, db: Session, run: AgentRun, *, requested_by: str = "", priority: int = 100
    ) -> None:
        """Stage queue state in the caller's transaction; never publish it early."""
        now = utc_now_iso()
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
        else:
            from app.domain.task_lifecycle.adapters import execution_requeue_allowed

            if record.state not in LEASED_STATES and not execution_requeue_allowed(
                str(record.state)
            ):
                return
            if record.state not in LEASED_STATES:
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
                    AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
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
            from app.domain.task_lifecycle.control import SessionBook

            book = SessionBook(db)
            self._expire_approvals(db, book, current)
            for candidate in candidates:
                recovered = candidate.state in LEASED_STATES
                from app.domain.task_lifecycle.machine import DEFAULT_MAX_ATTEMPTS

                if recovered and book.get(
                    "agent", str(candidate.tenant_id or ""), str(candidate.run_id)
                ).get("effects"):
                    db.query(AgentTaskExecutionRecord).filter(
                        AgentTaskExecutionRecord.run_id == candidate.run_id,
                        AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
                    ).update(
                        {
                            AgentTaskExecutionRecord.state: "failed",
                            AgentTaskExecutionRecord.lease_owner: None,
                            AgentTaskExecutionRecord.lease_expires_at: None,
                            AgentTaskExecutionRecord.last_error_code: "needs_verification",
                            AgentTaskExecutionRecord.finished_at: current,
                            AgentTaskExecutionRecord.updated_at: current,
                        },
                        synchronize_session=False,
                    )
                    continue
                if recovered and int(candidate.execution_count or 0) + 1 > DEFAULT_MAX_ATTEMPTS:
                    db.query(AgentTaskExecutionRecord).filter(
                        AgentTaskExecutionRecord.run_id == candidate.run_id,
                        AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
                    ).update(
                        {
                            AgentTaskExecutionRecord.state: "failed",
                            AgentTaskExecutionRecord.lease_owner: None,
                            AgentTaskExecutionRecord.lease_expires_at: None,
                            AgentTaskExecutionRecord.last_error_code: "retries_exhausted",
                            AgentTaskExecutionRecord.finished_at: current,
                            AgentTaskExecutionRecord.updated_at: current,
                        },
                        synchronize_session=False,
                    )
                    continue
                updated = (
                    db.query(AgentTaskExecutionRecord)
                    .filter(
                        AgentTaskExecutionRecord.run_id == candidate.run_id,
                        AgentTaskExecutionRecord.available_at <= current,
                        eligible,
                    )
                    .update(
                        {
                            AgentTaskExecutionRecord.state: "running",
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
                    AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
                    AgentTaskExecutionRecord.lease_owner == str(owner_id or ""),
                    AgentTaskExecutionRecord.lease_expires_at > current,
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
            from app.domain.task_lifecycle.adapters import execution_transition_allowed

            existing = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.run_id == str(run_id or ""))
                .one_or_none()
            )
            from app.domain.task_lifecycle.adapters import WAITING_STATES
            from app.domain.task_lifecycle.control import (
                SessionBook,
                jittered_delay,
                remember,
                settle_target,
            )

            if existing is None:
                return None
            book = SessionBook(db)
            body = book.get("agent", str(existing.tenant_id or ""), str(existing.run_id))
            requested = canonical_execution_state(state)
            if not execution_transition_allowed(str(existing.state), requested):
                return None
            visible, error_code = settle_target(
                state,
                error_code,
                int(existing.execution_count or 0),
                open_effects=bool(body.get("effects")),
            )
            available_at = None
            if visible == "queued" and str(state) in {"failed", "timed_out"}:
                available_at = _deadline(
                    now,
                    jittered_delay(
                        int(existing.execution_count or 0),
                        jitter_ratio=self._jitter_ratio,
                        rng=self._rng,
                    ),
                )
            previous = str(existing.state)
            remember(
                body,
                at=now,
                source=previous,
                target=visible,
                code=str(error_code or ""),
                actor="",
            )
            if error_code != "needs_verification":
                body["effects"] = []
            if visible == "waiting_approval" or visible in WAITING_STATES:
                body["approver"] = body.get("approver") or str(existing.user_id or "")
                body["approval_requested_at"] = now
            if available_at:
                body["available_at"] = available_at
            book.put("agent", str(existing.tenant_id or ""), str(existing.run_id), body)

            query = db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id == str(run_id or "")
            )
            if require_claim:
                query = query.filter(
                    AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
                    AgentTaskExecutionRecord.lease_owner == str(owner_id or ""),
                    AgentTaskExecutionRecord.lease_expires_at > now,
                )
            values: dict[Any, Any] = {
                AgentTaskExecutionRecord.state: visible,
                AgentTaskExecutionRecord.lease_owner: None,
                AgentTaskExecutionRecord.lease_expires_at: None,
                AgentTaskExecutionRecord.heartbeat_at: None,
                AgentTaskExecutionRecord.last_error_code: str(error_code or "")[:64] or None,
                AgentTaskExecutionRecord.updated_at: now,
            }
            if available_at:
                values[AgentTaskExecutionRecord.available_at] = available_at
                values[AgentTaskExecutionRecord.finished_at] = None
            elif visible in {"succeeded", "failed", "timed_out", "cancelled", "rejected"}:
                values[AgentTaskExecutionRecord.finished_at] = now
            # Ownership must be checked by the UPDATE itself. Reading the owner
            # then flushing an ORM object permits an expired worker to overwrite
            # a claim acquired by another process between those two operations.
            if query.update(values, synchronize_session=False) != 1:
                return None
        return self.get(run_id)

    def mark_open_effect(self, run_id: str, effect_id: str = "dispatch") -> None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            if record is None or record.state not in LEASED_STATES:
                return
            book = SessionBook(db)
            body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
            effects = set(body.get("effects") or [])
            effects.add(str(effect_id or "dispatch"))
            body["effects"] = sorted(effects)
            book.put("agent", str(record.tenant_id or ""), str(record.run_id), body)

    def request_approval(self, run_id: str, approver: str) -> AgentTaskExecution | None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            if record is None:
                return None
            book = SessionBook(db)
            body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
            body["approver"] = str(approver or "")
            book.put("agent", str(record.tenant_id or ""), str(record.run_id), body)
        return self.transition(run_id, "paused", error_code="approval_requested")

    def resolve_approval(self, run_id: str, decision: str, actor: str) -> AgentTaskExecution | None:
        from app.domain.task_lifecycle.control import TaskLifecycleError, approval_actor_allowed

        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            if record is None:
                return None
            book = SessionBook(db)
            body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
            if not approval_actor_allowed(body, actor):
                raise TaskLifecycleError("无权审批该任务")
            if decision not in {"approve", "reject"}:
                raise TaskLifecycleError("未知审批决定")
        if decision == "approve":
            return self.transition(run_id, "queued", error_code="approved")
        return self.transition(run_id, "rejected", error_code="approval_rejected")

    def lifecycle(self, run_id: str) -> dict[str, Any]:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            tenant = str(record.tenant_id or "") if record is not None else ""
            return SessionBook(db).get("agent", tenant, str(run_id or ""))

    def _expire_approvals(self, db: Session, book: Any, current: str) -> None:
        from app.db.models.agent import AgentTaskExecutionRecord
        from app.domain.task_lifecycle.control import remember

        moment = datetime.fromisoformat(current.replace("Z", "+00:00"))
        rows = (
            db.query(AgentTaskExecutionRecord)
            .filter(AgentTaskExecutionRecord.state.in_(tuple(WAITING_STATES)))
            .all()
        )
        for record in rows:
            body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
            started = str(body.get("approval_requested_at") or record.updated_at or "")
            if not started:
                continue
            age = (moment - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
            if age < self._approval_timeout_seconds:
                continue
            previous = str(record.state)
            record.state = "rejected"
            record.last_error_code = "approval_timeout"
            record.finished_at = current
            record.updated_at = current
            remember(
                body,
                at=current,
                source=previous,
                target="rejected",
                code="approval_timeout",
                actor="",
            )
            book.put("agent", str(record.tenant_id or ""), str(record.run_id), body)

    def clear(self) -> None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.application.agent_orchestrator.catalog_authority_retention import (
                catalog_retention,
                lock_catalog_cleanup,
            )
            from app.db.models.agent import AgentTaskExecutionRecord

            lock_catalog_cleanup(db)
            retained = catalog_retention(db)
            db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id.not_in(retained.run_ids)
            ).delete(synchronize_session=False)

    @contextmanager
    def transaction(self, *, read_only: bool = False) -> Iterator[Session]:
        """Own one initialized storage transaction for cross-repository operations.

        The caller may use session-bound writes but must not commit or close the
        session. Successful writes commit once on exit; failures roll back.
        """
        self._ensure_schema()
        with self._session_scope(read_only=read_only) as db:
            yield db

    @contextmanager
    def _session_scope(self, *, read_only: bool = False) -> Iterator[Session]:
        session_factory = self._session_factory
        if session_factory is None:
            from app.db import HostSessionLocal

            # Workers and HTTP requests share one durable control database.
            session_factory = HostSessionLocal
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
        if not self._auto_create:
            return
        with self._schema_lock:
            with self._session_scope(read_only=True) as db:
                from app.db.db_base import Base
                from app.db.models.agent import AgentTaskExecutionRecord
                from app.db.models.task_lifecycle import (
                    TaskLifecycleIdempotency,
                    TaskLifecycleRecord,
                )

                bind = db.get_bind()
                if self._schema_ready and self._schema_bind is bind:
                    return
                Base.metadata.create_all(
                    bind=bind,
                    tables=[
                        cast("Table", AgentTaskExecutionRecord.__table__),
                        cast("Table", TaskLifecycleRecord.__table__),
                        cast("Table", TaskLifecycleIdempotency.__table__),
                    ],
                    checkfirst=True,
                )
                self._schema_bind = bind
            self._schema_ready = True

    @staticmethod
    def _to_model(record) -> AgentTaskExecution:
        return AgentTaskExecution(
            run_id=str(record.run_id),
            task_id=str(record.task_id),
            user_id=str(record.user_id),
            tenant_id=str(record.tenant_id or ""),
            state=cast(ExecutionState, canonical_execution_state(str(record.state))),
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
