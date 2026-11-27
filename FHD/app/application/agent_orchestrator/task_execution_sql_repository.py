"""SQLAlchemy implementation of the durable Agent task execution queue."""

from __future__ import annotations

import random
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Table, and_, or_
from sqlalchemy.engine import Engine
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
    APPROVAL_STATES,
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
        from app.application.agent_orchestrator.task_execution_repository import (
            remember_open_repository,
        )

        remember_open_repository(self)
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
        self,
        db: Session,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        retryable: bool = False,
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
                str(record.state), retryable=retryable
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

    def enqueue_waiting_approval(
        self,
        run: AgentRun,
        *,
        requested_by: str = "",
        priority: int = 100,
        approver: str = "",
    ) -> AgentTaskExecution:
        """Insert a queued row and park it for approval in one commit.

        Other workers never observe a claimable ``queued`` row. The lifecycle
        history still records ``queued → waiting_approval``.
        """
        self._ensure_schema()
        now = utc_now_iso()
        with self._session_scope() as db:
            self.enqueue_in_session(db, run, requested_by=requested_by, priority=priority)
            db.flush()
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.adapters import execution_transition_allowed
            from app.domain.task_lifecycle.control import SessionBook, remember

            record = db.get(AgentTaskExecutionRecord, run.run_id)
            if record is not None and str(record.state) == "queued":
                if not execution_transition_allowed("queued", "waiting_approval"):
                    raise RuntimeError("队列不能从 queued 进入 waiting_approval")
                book = SessionBook(db)
                tenant = str(record.tenant_id or "")
                body = book.get("agent", tenant, run.run_id)
                body["approver"] = str(approver or record.user_id or "")
                body["approval_requested_at"] = now
                remember(
                    body,
                    at=now,
                    source="queued",
                    target="waiting_approval",
                    code="approval_required",
                    actor=str(approver or ""),
                )
                book.put("agent", tenant, run.run_id, body)
                record.state = "waiting_approval"
                record.lease_owner = None
                record.lease_expires_at = None
                record.heartbeat_at = None
                record.updated_at = now
        stored = self.get(run.run_id)
        if stored is None:
            raise RuntimeError("审批队列行未能持久化")
        return stored

    def claim(
        self,
        owner_id: str,
        *,
        lease_seconds: float,
        now: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
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
            candidate_filter = [AgentTaskExecutionRecord.available_at <= current, eligible]
            wanted = str(run_id or "")
            if wanted:
                candidate_filter.append(AgentTaskExecutionRecord.run_id == wanted)
            if tenant_id is not None:
                candidate_filter.append(AgentTaskExecutionRecord.tenant_id == str(tenant_id))
            candidates = (
                db.query(AgentTaskExecutionRecord)
                .filter(*candidate_filter)
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

                effects: list[Any] = []
                if recovered:
                    # Fence the expired observation before either settling receipts
                    # or failing the row. Another worker may already own a new lease.
                    fenced = (
                        db.query(AgentTaskExecutionRecord)
                        .filter(
                            AgentTaskExecutionRecord.run_id == candidate.run_id,
                            AgentTaskExecutionRecord.state == candidate.state,
                            AgentTaskExecutionRecord.execution_count == candidate.execution_count,
                            AgentTaskExecutionRecord.lease_owner == candidate.lease_owner,
                            eligible,
                        )
                        .update(
                            {AgentTaskExecutionRecord.updated_at: candidate.updated_at},
                            synchronize_session=False,
                        )
                    )
                    if fenced != 1:
                        continue
                    effects = list(
                        book.get(
                            "agent", str(candidate.tenant_id or ""), str(candidate.run_id)
                        ).get("effects")
                        or []
                    )
                    if effects:
                        import json

                        from app.application.agent_orchestrator.elt_checkpoint_recovery import (
                            checkpoint_step,
                        )
                        from app.application.agent_orchestrator.resume_transaction import (
                            unresolved_effects,
                        )
                        from app.application.agent_orchestrator.run_models import (
                            agent_run_from_dict,
                        )
                        from app.db.models.agent import AgentRunRecord

                        saved = db.get(AgentRunRecord, candidate.run_id)
                        if saved is not None:
                            run = agent_run_from_dict(json.loads(saved.payload_json))
                            effects = unresolved_effects(
                                db,
                                run,
                                clear_confirmed=True,
                            )
                            approved = checkpoint_step(run)
                            if approved is not None and set(effects) <= {approved.step_id}:
                                # Let only the exact native router reconcile. The
                                # stored effect remains open until a final receipt.
                                effects = []
                if recovered and effects:
                    db.query(AgentTaskExecutionRecord).filter(
                        AgentTaskExecutionRecord.run_id == candidate.run_id,
                        AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
                    ).update(
                        {
                            AgentTaskExecutionRecord.state: "unknown",
                            AgentTaskExecutionRecord.lease_owner: None,
                            AgentTaskExecutionRecord.lease_expires_at: None,
                            AgentTaskExecutionRecord.last_error_code: "needs_verification",
                            AgentTaskExecutionRecord.finished_at: None,
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

    def reconcile_xiaox_receipts(self, run_repository: Any, previous: AgentRun) -> AgentRun | None:
        """Project verified delegated results without claiming or replaying a worker.

        This restricted reconciliation event is not a general lifecycle edge.
        A stopped parent's original children and frozen goal are independently
        checked, then its run, Task view and unleased waiting queue row commit
        together. Callers cannot supply a desired state or replacement result.
        """
        from app.application.agent_orchestrator.run_sql_repository import (
            SQLAlchemyAgentRunRepository,
        )
        from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord, AgentTaskRecord
        from app.domain.task_lifecycle.agent_runtime_results import (
            model_unsettled,
            receipt_verified,
        )
        from app.domain.task_lifecycle.control import SessionBook, remember
        from app.infrastructure.xiaox.binding import (
            XiaoxBinding,
            XiaoxBindingError,
            XiaoxBindingStore,
        )
        from app.infrastructure.xiaox.receipt_projection import (
            project_receipt_state,
            projection_allowed,
        )
        from app.infrastructure.xiaox.receipts import read_call_receipt

        if not isinstance(run_repository, SQLAlchemyAgentRunRepository) or not projection_allowed(
            previous
        ):
            return None
        store = XiaoxBindingStore(run_repository)
        binding = XiaoxBinding(previous)
        store._validate_goal(previous, binding.metadata)
        rows, children = [], {}
        for call_id, call in binding.metadata["calls"].items():
            receipt = read_call_receipt(store, binding, call)
            if receipt != call.get("receipt"):
                return None  # A child changed since the caller's receipt snapshot.
            rows.append({"call_id": call_id, **call})
            if child_id := receipt.get("run_id"):
                child = run_repository.get(child_id)
                if child is None or child.updated_at != receipt.get("child_updated_at"):
                    return None
                children[child_id] = child
        previous_result = previous.final_output.get("xiaox_result") or {}
        prior = {
            str(row.get("call_id")): row for row in previous_result.get("business_receipts") or []
        }
        recovered_writes = [
            row
            for row in rows
            if row.get("read_only") is not True
            and (prior.get(str(row["call_id"])) or {}).get("state")
            in {"waiting_user", "waiting_approval", "running"}
        ]
        verified_child_recovery = bool(
            (previous.metadata.get("recovery") or {}) == {"state": "manual_reconciliation_required"}
            and previous.metadata.get("non_retryable") is True
            and previous.status in {"running", "waiting_user", "unknown"}
            and not previous.metadata.get("stream_interruption")
            and not model_unsettled(binding.metadata)
            and previous_result.get("exit_status") in {"waiting_user", "running"}
            and not any(
                (request.get("result") or {}).get("execution_state") == "unknown"
                for request in (previous.metadata.get("runtime_requests") or {}).values()
            )
            and recovered_writes
            and all(receipt_verified(row) for row in rows)
        )
        projected = project_receipt_state(
            previous, rows, verified_child_recovery=verified_child_recovery
        )
        if projected is None:
            return None
        result = projected.final_output["xiaox_result"]
        if projected.status == "completed" and not (
            result.get("business_completed") is True
            and result.get("verified_operations") is True
            and (result.get("goal_coverage") or {}).get("completed") is True
        ):
            return None
        target = {"completed": "succeeded", "failed": "failed", "blocked": "failed"}.get(
            projected.status, "waiting_approval"
        )
        code = (
            "needs_verification"
            if result.get("reconciliation_required")
            else "xiaox_receipt_projection"
        )
        now = utc_now_iso()
        with self.transaction() as db, run_repository.transaction(read_only=True) as runs:
            if db.get_bind() is not runs.get_bind():
                raise XiaoxBindingError("durable_storage_required", "父任务与队列不属于同一数据库")
            execution = db.get(AgentTaskExecutionRecord, previous.run_id)
            if execution is not None:
                if (
                    execution.state not in WAITING_STATES
                    or execution.lease_owner
                    or execution.lease_expires_at
                ):
                    return None
                fenced = (
                    db.query(AgentTaskExecutionRecord)
                    .filter(
                        AgentTaskExecutionRecord.run_id == previous.run_id,
                        AgentTaskExecutionRecord.state == execution.state,
                        AgentTaskExecutionRecord.execution_count == execution.execution_count,
                        AgentTaskExecutionRecord.lease_owner == execution.lease_owner,
                        AgentTaskExecutionRecord.lease_expires_at == execution.lease_expires_at,
                    )
                    .update(
                        {AgentTaskExecutionRecord.updated_at: execution.updated_at},
                        synchronize_session=False,
                    )
                )
                if fenced != 1:
                    return None
                book = SessionBook(db)
                body = book.get("agent", str(execution.tenant_id or ""), previous.run_id)
                if body.get("effects") or execution.last_error_code == "needs_verification":
                    return None
            for child_id, child in children.items():
                record = db.get(AgentRunRecord, child_id)
                current = run_repository._record_to_run(record) if record is not None else None
                if current is None or current.to_dict() != child.to_dict():
                    return None
                assert record is not None
                if (
                    db.query(AgentRunRecord)
                    .filter(
                        AgentRunRecord.run_id == child_id,
                        AgentRunRecord.payload_json == record.payload_json,
                    )
                    .update({AgentRunRecord.status: record.status}, synchronize_session=False)
                    != 1
                ):
                    return None
            if verified_child_recovery:
                for row in recovered_writes:
                    child_id, task_id = row["child_run_id"], row["child_task_id"]
                    child = children[child_id]
                    tasks = (
                        db.query(AgentTaskRecord)
                        .filter(
                            AgentTaskRecord.task_id == task_id,
                            AgentTaskRecord.user_id == previous.user_id,
                            AgentTaskRecord.tenant_id == tenant_id_of_run(previous),
                        )
                        .limit(2)
                        .all()
                    )
                    if (
                        len(tasks) != 1
                        or tasks[0].active_run_id != child_id
                        or tasks[0].root_run_id != previous.run_id
                        or tasks[0].attempt != 1
                        or tasks[0].run_count != 1
                        or child.status != "completed"
                        or child.metadata.get("non_retryable")
                        or child.metadata.get("recovery")
                    ):
                        return None
            if not run_repository.save_if_unchanged_in_session(
                db,
                projected,
                previous,
                allow_verified_xiaox_recovery=verified_child_recovery,
            ):
                return None
            if projected.status != result["execution_state"] and not (
                projected.status == "blocked" and result["execution_state"] == "unknown"
            ):
                raise XiaoxBindingError("evidence_mismatch", "父任务投影未通过宿主结果核验")
            if execution is not None:
                remember(
                    body, at=now, source=str(execution.state), target=target, code=code, actor=""
                )
                book.put("agent", str(execution.tenant_id or ""), previous.run_id, body)
                execution.state = target
                execution.last_error_code = None if target == "succeeded" else code
                execution.updated_at = now
                if target in {"succeeded", "failed"}:
                    execution.finished_at = now
        return run_repository.get(previous.run_id)

    def _transition(
        self,
        run_id: str,
        state: str,
        *,
        error_code: str,
        owner_id: str = "",
        require_claim: bool = False,
        approver: str | None = None,
        approval_actor: str | None = None,
    ) -> AgentTaskExecution | None:
        self._ensure_schema()
        now = utc_now_iso()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.adapters import execution_transition_allowed

            existing = (
                db.query(AgentTaskExecutionRecord)
                .filter(AgentTaskExecutionRecord.run_id == str(run_id or ""))
                .with_for_update()
                .one_or_none()
            )
            from app.domain.task_lifecycle.control import (
                SessionBook,
                TaskLifecycleError,
                approval_actor_allowed,
                jittered_delay,
                remember,
                settle_target,
            )

            if existing is None:
                return None
            book = SessionBook(db)
            body = book.get("agent", str(existing.tenant_id or ""), str(existing.run_id))
            if approval_actor is not None:
                if existing.state not in APPROVAL_STATES:
                    return None
                if not approval_actor_allowed(body, approval_actor):
                    raise TaskLifecycleError("无权审批该任务")
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
            if visible in APPROVAL_STATES:
                body["approver"] = (
                    approver
                    if approver is not None
                    else body.get("approver") or str(existing.user_id or "")
                )
                body["approval_requested_at"] = now
            if available_at:
                body["available_at"] = available_at
            query = db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id == str(run_id or ""),
                AgentTaskExecutionRecord.state == existing.state,
                AgentTaskExecutionRecord.execution_count == existing.execution_count,
                AgentTaskExecutionRecord.updated_at == existing.updated_at,
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
            # The lifecycle and open-effect log belong to the winning transition.
            # A rejected/expired worker must not publish lifecycle history or
            # erase the replacement worker's unresolved business effects.
            # A stale owner must not clear receipts even when its row CAS fails.
            book.put("agent", str(existing.tenant_id or ""), str(existing.run_id), body)
        return self.get(run_id)

    def mark_open_effect(
        self,
        run_id: str,
        effect_id: str = "dispatch",
        *,
        owner_id: str = "",
        execution_count: int | None = None,
    ) -> bool:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            now = utc_now_iso()
            query = db.query(AgentTaskExecutionRecord).filter(
                AgentTaskExecutionRecord.run_id == str(run_id or ""),
                AgentTaskExecutionRecord.state.in_(tuple(LEASED_STATES)),
            )
            if owner_id:
                query = query.filter(
                    AgentTaskExecutionRecord.lease_owner == owner_id,
                    AgentTaskExecutionRecord.lease_expires_at > now,
                )
            if execution_count is not None:
                query = query.filter(AgentTaskExecutionRecord.execution_count == execution_count)
            if (
                query.update({AgentTaskExecutionRecord.updated_at: now}, synchronize_session=False)
                != 1
            ):
                return False
            record = db.get(AgentTaskExecutionRecord, str(run_id or ""))
            if record is None:
                return False
            book = SessionBook(db)
            body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
            effects = set(body.get("effects") or [])
            effects.add(str(effect_id or "dispatch"))
            body["effects"] = sorted(effects)
            book.put("agent", str(record.tenant_id or ""), str(record.run_id), body)
            return True

    def request_approval(self, run_id: str, approver: str) -> AgentTaskExecution | None:
        return self._transition(
            run_id,
            "waiting_approval",
            error_code="approval_requested",
            approver=str(approver or ""),
        )

    def resolve_approval(self, run_id: str, decision: str, actor: str) -> AgentTaskExecution | None:
        from app.domain.task_lifecycle.control import TaskLifecycleError

        if decision not in {"approve", "reject"}:
            raise TaskLifecycleError("未知审批决定")
        return self._transition(
            run_id,
            "queued" if decision == "approve" else "rejected",
            error_code="approved" if decision == "approve" else "approval_rejected",
            approval_actor=actor,
        )

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
            .filter(AgentTaskExecutionRecord.state.in_(tuple(APPROVAL_STATES)))
            .with_for_update()
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
                from app.db.bootstrap.orm_tables import _serialized_schema_bind
                from app.db.db_base import Base
                from app.db.models.agent import AgentTaskExecutionRecord
                from app.db.models.task_lifecycle import (
                    TaskLifecycleIdempotency,
                    TaskLifecycleRecord,
                )

                bind = db.get_bind()
                if self._schema_ready and self._schema_bind is bind:
                    return
                with _serialized_schema_bind(bind) as schema_bind:
                    Base.metadata.create_all(
                        bind=schema_bind,
                        tables=[
                            cast("Table", AgentTaskExecutionRecord.__table__),
                            cast("Table", TaskLifecycleRecord.__table__),
                            cast("Table", TaskLifecycleIdempotency.__table__),
                        ],
                        checkfirst=True,
                    )
                self._schema_bind = bind
            # DDL on a caller-owned Connection can still be rolled back later.
            self._schema_ready = isinstance(bind, Engine)

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
