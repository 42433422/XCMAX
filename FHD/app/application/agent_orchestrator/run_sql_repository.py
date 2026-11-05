"""SQLAlchemy persistence for Agent runs, tasks, events, and controls."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast

from sqlalchemy import Table
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import (
    AgentRun,
    RunEvent,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_record_mapping import (
    _command_record_to_model,
    _record_to_run,
    _task_record_to_model,
)
from app.application.agent_orchestrator.task_models import (
    AgentTask,
    TaskControlCommand,
    mod_id_of_run,
    task_from_run,
    tenant_id_of_run,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def same_run_generation(run: AgentRun, previous: AgentRun) -> bool:
    def context(value):
        return {
            key: item
            for key, item in (value.metadata.get("runtime_context") or {}).items()
            if key not in {"run_id", "agent_run_id"}
        }

    return (run.run_id, run.user_id, run.created_at, context(run)) == (
        previous.run_id,
        previous.user_id,
        previous.created_at,
        context(previous),
    )


def preserve_run_evidence(run: AgentRun, previous: AgentRun | None) -> None:
    """Same-generation saves cannot erase an unknown outcome or returned receipt."""
    if previous is None or not same_run_generation(run, previous):
        return
    old = previous.metadata
    if old.get("non_retryable"):
        run.metadata["non_retryable"] = True
    recovery = {**copy.deepcopy(old.get("recovery") or {}), **(run.metadata.get("recovery") or {})}
    if (old.get("recovery") or {}).get("state") == "manual_reconciliation_required":
        recovery["state"] = "manual_reconciliation_required"
    if recovery:
        run.metadata["recovery"] = recovery
    interruption = old.get("stream_interruption")
    if interruption:
        incoming = run.metadata.get("stream_interruption") or interruption
        state = copy.deepcopy(interruption if not interruption.get("worker_pending") else incoming)
        state.update(business_outcome="unknown", replay_allowed=False)
        run.metadata["stream_interruption"] = state
        run.metadata["non_retryable"] = True
        run.metadata.setdefault("recovery", {}).update(
            state="manual_reconciliation_required", stream_interruption=copy.deepcopy(state)
        )
        run.final_output["stream_interruption"] = copy.deepcopy(state)
    audit = {item["sequence"]: copy.deepcopy(item) for item in old.get("stream_tool_audit", [])}
    for item in run.metadata.get("stream_tool_audit", []):
        if item["sequence"] in audit and audit[item["sequence"]] != item:
            raise ValueError("stream tool receipt sequence already has different evidence")
        audit[item["sequence"]] = item
    if audit:
        run.metadata["stream_tool_audit"] = [audit[key] for key in sorted(audit)]
    if "receipt" in previous.final_output:
        run.final_output.setdefault("receipt", copy.deepcopy(previous.final_output["receipt"]))
    for field, identity in (("steps", "step_id"), ("tool_calls", "call_id")):
        incoming = {getattr(item, identity): item for item in getattr(run, field)}
        combined = {}
        for item in getattr(previous, field):
            key = getattr(item, identity)
            replacement = incoming.pop(key, None)
            resolved_approval = item.output.get("pending_approval") is True and any(
                event.event_type == "approval.resolved"
                and event.data.get("approval_request_id")
                in (item.output.get("approval") or {}).get("approval_request_ids", [])
                for event in run.events
            )
            if replacement is None:
                replacement = copy.deepcopy(item)
            elif (
                (
                    item.status == "failed"
                    and (
                        old.get("non_retryable")
                        or (old.get("recovery") or {}).get("state")
                        == "manual_reconciliation_required"
                        or item.output.get("outcome") == "unknown"
                        or item.output.get("reconciliation_required")
                    )
                )
                or (
                    (
                        item.status == "completed"
                        or (field == "tool_calls" and item.status == "failed")
                    )
                    and replacement.status != item.status
                    and not resolved_approval
                )
            ) and getattr(replacement, "attempt_count", 0) <= getattr(item, "attempt_count", 0):
                # Keep the executor's step/call object alive: repair and result
                # processing retain this reference across repository checkpoints.
                replacement.__dict__.update(copy.deepcopy(item.__dict__))
            combined[key] = replacement
        combined.update(incoming)
        setattr(run, field, list(combined.values()))
    events = {event.event_id: copy.deepcopy(event) for event in previous.events}
    for event in run.events:
        events.setdefault(event.event_id, event)
    run.events = list(events.values())
    if previous.status in {"completed", "failed", "cancelled", "paused", "blocked"} and (
        run.status in {"queued", "planning", "running", "retrying"}
        and (
            previous.status in {"completed", "failed"}
            or old.get("stream_interruption")
            or old.get("non_retryable")
            or (old.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        )
    ):
        run.status, run.error = previous.status, previous.error
    if run.status == "cancelled" and (
        run.metadata.get("non_retryable")
        or recovery.get("state") == "manual_reconciliation_required"
    ):
        run.error = "任务已停止继续执行；已有调用结果仍需人工核对"


def valid_stream_interruption_update(run: AgentRun, previous: AgentRun) -> bool:
    """The CAS seam may add an observation marker, never rewrite execution facts."""
    before, after = previous.to_dict(), run.to_dict()
    if previous.status not in {
        "queued",
        "planning",
        "running",
        "retrying",
        "blocked",
        "cancelled",
        "paused",
    }:
        return False
    if previous.status == "blocked" and not previous.metadata.get("stream_interruption"):
        return False
    if run.status not in {"running", "blocked", "cancelled", "paused"}:
        return False
    state = run.metadata.get("stream_interruption")
    if not isinstance(state, dict) or state.get("replay_allowed") is not False:
        return False
    if (
        state.get("business_outcome") != "unknown"
        or run.final_output.get("stream_interruption") != state
    ):
        return False
    if run.status in {"cancelled", "paused"} and (
        (previous.metadata.get("control") or {}).get("state") != run.status
        or previous.status != run.status
    ):
        return False
    if run.status not in {"cancelled", "paused"} and (run.status == "running") != bool(
        state.get("worker_pending")
    ):
        return False
    recovery = previous.metadata.get("recovery")
    recovery = recovery if isinstance(recovery, dict) else {}
    if run.metadata.get("non_retryable") is not True or run.metadata.get("recovery") != {
        **recovery,
        "state": "manual_reconciliation_required",
        "stream_interruption": state,
    }:
        return False
    for snapshot in (before, after):
        snapshot["metadata"] = {
            key: value
            for key, value in snapshot["metadata"].items()
            if key not in {"non_retryable", "recovery"}
        }
    for key in ("metadata", "final_output"):
        before[key] = {k: v for k, v in before[key].items() if k != "stream_interruption"}
        after[key] = {k: v for k, v in after[key].items() if k != "stream_interruption"}
    events = after.pop("events")
    prior_events = before.pop("events")
    if len(events) != len(prior_events) + 1 or events[:-1] != prior_events:
        return False
    if events[-1].get("event_type") != "run.observation_interrupted":
        return False
    for key in ("status", "updated_at"):
        before.pop(key)
        after.pop(key)
    return before == after


def valid_control_update(run: AgentRun, previous: AgentRun) -> bool:
    """Accept precisely the lifecycle's pause/cancel delta, including its replay gate."""
    from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin

    control = run.metadata.get("control") or {}
    if run.status not in {"paused", "cancelled"} or control.get("state") != run.status:
        return False
    expected = copy.deepcopy(previous)
    RunLifecycleMixin._mark_controlled(
        expected,
        "pause" if run.status == "paused" else "cancel",
        requested_by=control.get("requested_by", ""),
        command_id=control.get("command_id", ""),
    )
    if run.status == "paused":
        expected.metadata["control"]["resume_status"] = (
            "waiting_user" if previous.status == "waiting_user" else "running"
        )
    before, after = expected.to_dict(), run.to_dict()
    events = after.pop("events")
    before.pop("events")
    original = [event.to_dict() for event in previous.events]
    if events[: len(original)] != original or any(
        event.get("event_type") not in {"run.paused", "run.cancelled"}
        for event in events[len(original) :]
    ):
        return False
    before.pop("updated_at")
    after.pop("updated_at")
    return before == after


def valid_stream_tool_audit_update(run: AgentRun, previous: AgentRun) -> bool:
    before, after = copy.deepcopy(previous.to_dict()), copy.deepcopy(run.to_dict())
    old = before["metadata"].pop("stream_tool_audit", [])
    new = after["metadata"].pop("stream_tool_audit", [])
    if len(new) != len(old) + 1 or new[:-1] != old:
        return False
    events, prior_events = after.pop("events"), before.pop("events")
    if len(events) != len(prior_events) + 1 or events[:-1] != prior_events:
        return False
    if events[-1].get("event_type") != "tool.receipt_observed":
        return False
    before.pop("updated_at")
    after.pop("updated_at")
    return before == after


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
        self._schema_bind: object | None = None
        self._schema_lock = threading.RLock()

    def save(self, run: AgentRun) -> AgentRun:
        self._ensure_schema()
        with self._session_scope() as db:
            self.save_in_session(db, run)
        return self.get(run.run_id) or copy.deepcopy(run)

    def save_stream_interruption_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        """CAS the complete snapshot, retaining the row lock through task persistence."""

        if not valid_stream_interruption_update(run, previous):
            return False
        return self._save_if_unchanged(run, previous)

    def save_control_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        return valid_control_update(run, previous) and self._save_if_unchanged(run, previous)

    def save_stream_tool_audit_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        return valid_stream_tool_audit_update(run, previous) and self._save_if_unchanged(
            run, previous
        )

    def _save_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        from app.db.models.agent import AgentRunRecord

        self._ensure_schema()
        with self._session_scope() as db:
            record = db.get(AgentRunRecord, previous.run_id)
            if record is None:
                return False
            current = self._record_to_run(record)
            if current is None or current.to_dict() != previous.to_dict():
                return False
            matched = (
                db.query(AgentRunRecord)
                .filter(
                    AgentRunRecord.run_id == previous.run_id,
                    AgentRunRecord.payload_json == record.payload_json,
                )
                .update({AgentRunRecord.status: record.status}, synchronize_session=False)
            )
            if matched != 1:
                return False
            self.save_in_session(db, run)
        return True

    def save_claimed(self, run: AgentRun, *, owner_id: str, execution_count: int) -> AgentRun:
        from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
        from app.db.models.agent import AgentTaskExecutionRecord

        self._ensure_schema()
        with self._session_scope() as db:
            # A conditional write holds the queue-row lock through run persistence.
            # Checking the lease in a separate SELECT would allow takeover between
            # the check and save. Execution count also fences reused owner IDs.
            owned = (
                db.query(AgentTaskExecutionRecord)
                .filter(
                    AgentTaskExecutionRecord.run_id == run.run_id,
                    AgentTaskExecutionRecord.state == "claimed",
                    AgentTaskExecutionRecord.lease_owner == owner_id,
                    AgentTaskExecutionRecord.execution_count == execution_count,
                    AgentTaskExecutionRecord.lease_expires_at > utc_now_iso(),
                )
                .update({AgentTaskExecutionRecord.lease_owner: owner_id}, synchronize_session=False)
            )
            if owned != 1:
                raise WorkerLeaseLost("worker lease expired or replaced")
            self.save_in_session(db, run)
        return copy.deepcopy(run)

    def save_in_session(self, db: Session, run: AgentRun) -> None:
        """Persist into the caller's transaction without committing or closing it."""
        from app.application.agent_orchestrator.business_harness import (
            ensure_terminal_business_result,
        )
        from app.db.models.agent import AgentRunRecord, AgentTaskRecord

        # Take ownership before reading the current payload; a SELECT followed by
        # an unconditional write can erase a receipt saved by another connection.
        db.query(AgentRunRecord).filter(AgentRunRecord.run_id == run.run_id).update(
            {AgentRunRecord.status: AgentRunRecord.status}, synchronize_session=False
        )
        record = db.get(AgentRunRecord, run.run_id, populate_existing=True)
        previous = self._record_to_run(record) if record is not None else None
        from app.application.agent_orchestrator.catalog_authority_retention import (
            preserve_catalog_run_authority,
        )

        preserve_catalog_run_authority(db, run, previous)
        preserve_run_evidence(run, previous)
        ensure_terminal_business_result(run)
        run.touch()
        payload = json.dumps(run.to_dict(), ensure_ascii=False, default=str)
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

    def get(self, run_id: str) -> AgentRun | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            record = db.get(AgentRunRecord, str(run_id or ""))
            return self._record_to_run(record) if record is not None else None

    def list_recent(
        self,
        *,
        user_id: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
        mod_id: str | None = None,
    ) -> list[AgentRun]:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            query = db.query(AgentRunRecord)
            if user_id is not None:
                query = query.filter(AgentRunRecord.user_id == str(user_id))
            query = query.order_by(AgentRunRecord.updated_at.desc())
            if tenant_id is None and mod_id is None:
                records = query.limit(max(0, int(limit))).all()
                return [
                    run for record in records if (run := self._record_to_run(record)) is not None
                ]
            result: list[AgentRun] = []
            if limit <= 0:
                return result
            # Older rows store tenant only in their JSON payload. Filter before
            # applying the public limit, without loading all rows at once.
            for record in query.yield_per(100):
                run = self._record_to_run(record)
                if (
                    run is not None
                    and (tenant_id is None or tenant_id_of_run(run) == tenant_id)
                    and (mod_id is None or mod_id_of_run(run) == mod_id)
                ):
                    result.append(run)
                    if len(result) >= limit:
                        break
            return result

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
        offset: int = 0,
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
                .offset(max(0, int(offset)))
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

            query = db.query(AgentTaskRecord).filter(
                AgentTaskRecord.user_id == str(user_id or ""),
                AgentTaskRecord.task_id == str(task_id or ""),
            )
            if tenant_id is not None:
                query = query.filter(AgentTaskRecord.tenant_id == str(tenant_id))
            records = query.limit(2).all()
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
            from sqlalchemy import or_, tuple_

            from app.application.agent_orchestrator.catalog_authority_retention import (
                catalog_retention,
                lock_catalog_cleanup,
            )
            from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskRecord

            lock_catalog_cleanup(db)
            retained = catalog_retention(db)
            protected_tasks = (
                db.query(AgentTaskRecord.id)
                .filter(
                    or_(
                        tuple_(
                            AgentTaskRecord.tenant_id,
                            AgentTaskRecord.user_id,
                            AgentTaskRecord.task_id,
                        ).in_(retained.task_keys),
                        AgentTaskRecord.active_run_id.in_(retained.run_ids),
                        AgentTaskRecord.root_run_id.in_(retained.run_ids),
                    )
                )
                .all()
            )
            db.query(AgentTaskCommandRecord).filter(
                AgentTaskCommandRecord.run_id.not_in(retained.run_ids)
            ).delete(synchronize_session=False)
            db.query(AgentTaskRecord).filter(
                AgentTaskRecord.id.not_in([row.id for row in protected_tasks])
            ).delete(synchronize_session=False)
            db.query(AgentRunRecord).filter(AgentRunRecord.run_id.not_in(retained.run_ids)).delete(
                synchronize_session=False
            )

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

            # Scheduling state must be visible outside the originating Mod request.
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
        # 就绪状态按 bind（引擎实例）键控：引擎缓存按 URL 解析，测试/多库环境下
        # DATABASE_URL 可能被切换（如桌面 runtime 直接改写 env），裸布尔会把
        # "A 库已建表"错误外推到 B 库（no such table: agent_runs）。
        # 与 task_execution_sql_repository._ensure_schema 的 bind-identity 模式一致。
        if not self._auto_create:
            return
        with self._schema_lock:
            with self._session_scope(read_only=True) as db:
                from app.db.db_base import Base
                from app.db.models.agent import (
                    AgentRunRecord,
                    AgentTaskCommandRecord,
                    AgentTaskRecord,
                )

                bind = db.get_bind()
                if self._schema_ready and self._schema_bind is bind:
                    return
                Base.metadata.create_all(
                    bind=bind,
                    tables=[
                        cast(Table, AgentRunRecord.__table__),
                        cast(Table, AgentTaskRecord.__table__),
                        cast(Table, AgentTaskCommandRecord.__table__),
                    ],
                    checkfirst=True,
                )
                self._schema_bind = bind
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

    _task_record_to_model = staticmethod(_task_record_to_model)
    _command_record_to_model = staticmethod(_command_record_to_model)
    _record_to_run = staticmethod(_record_to_run)


__all__ = ["SQLAlchemyAgentRunRepository"]
