"""SQL admission and fair candidate selection within the caller's transaction.

This adapter owns queue policy queries, not session or lease transitions. The
repository acquires the native transaction lock before admission/selection and
supplies an already captured catalog snapshot for policy revalidation.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, and_, case, false, func, inspect, literal, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_models import (
    ADMITTED_STATES,
    AgentTaskExecution,
    TaskDispatchLimits,
    TaskQueueCapacityError,
    _task_id_of,
    dispatch_tenant,
    freeze_dispatch_policy,
)
from app.application.agent_orchestrator.task_models import tenant_id_of_run
from app.domain.task_lifecycle.adapters import LEASED_STATES

if TYPE_CHECKING:
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.domain.task_lifecycle.control import SessionBook


def queue_admission_lock(db: Session) -> None:
    """Serialize short admission/claim decisions across actual database clients."""
    from app.db.models.agent import AgentTaskExecutionRecord as Record

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        # A caller can already hold its original approval/run locks. A try-lock
        # avoids lock-order deadlocks and rolls that same transaction back.
        if not db.scalar(select(func.pg_try_advisory_xact_lock(0x584341474951))):
            raise TaskQueueCapacityError("coordinator_busy")
    elif dialect == "sqlite":
        # Even an empty UPDATE obtains SQLite's database writer reservation.
        db.execute(update(Record).where(false()).values(updated_at=Record.updated_at))
    else:
        raise RuntimeError("Durable task admission requires SQLite or PostgreSQL")


def _tenant_expression(record: Any) -> ColumnElement[str]:
    return case(
        (record.tenant_id != "", literal("tenant:") + record.tenant_id),
        else_=literal("actor:") + record.user_id,
    )


def admit_in_session(db: Session, run: AgentRun, record: Any) -> None:
    from app.db.models.agent import AgentTaskExecutionRecord as Record

    if record is not None and str(record.state) in ADMITTED_STATES:
        return  # Same original admission, including approval and safe resume.
    limits = TaskDispatchLimits.configured()
    tenant = "tenant:" + tenant_id_of_run(run) if tenant_id_of_run(run) else "actor:" + run.user_id
    rows = db.query(Record).filter(Record.state.in_(ADMITTED_STATES))
    if rows.count() >= limits.admitted:
        raise TaskQueueCapacityError("global")
    if rows.filter(_tenant_expression(Record) == tenant).count() >= limits.tenant_admitted:
        raise TaskQueueCapacityError("tenant")


def recheck_dispatch_policy(
    db: Session, record: Any, book: SessionBook, specs: dict[tuple[str, str], Any]
) -> dict[str, Any]:
    from app.application.agent_orchestrator.run_models import agent_run_from_dict
    from app.db.models.agent import AgentRunRecord

    body = book.get("agent", str(record.tenant_id or ""), str(record.run_id))
    policy = body.get("dispatch_policy") or {"class": "background"}
    if not isinstance(policy, dict) or policy.get("class") != "interactive":
        return {"class": "background"}
    saved = (
        db.get(AgentRunRecord, record.run_id)
        if inspect(db.connection()).has_table(AgentRunRecord.__tablename__)
        else None
    )
    if saved is not None:
        run = agent_run_from_dict(json.loads(saved.payload_json))
        if (
            run.user_id == record.user_id
            and tenant_id_of_run(run) == record.tenant_id
            and _task_id_of(run) == record.task_id
            and freeze_dispatch_policy(run, specs) == policy
        ):
            return dict(policy)
    body["dispatch_policy"] = {"class": "background"}
    book.put("agent", str(record.tenant_id or ""), str(record.run_id), body)
    return {"class": "background"}


def select_dispatch_candidates(
    db: Session,
    *,
    current: str,
    active: list[AgentTaskExecution],
    limits: TaskDispatchLimits,
    run_id: str | None,
    tenant_id: str | None,
    interactive_only: bool,
) -> tuple[list[AgentTaskExecutionRecord], ColumnElement[bool]]:
    """Apply capacity/fairness before the bounded scan; return its CAS predicate."""
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.db.models.task_lifecycle import TaskLifecycleRecord

    counts = Counter(dispatch_tenant(row) for row in active)
    background_counts = Counter(
        dispatch_tenant(row) for row in active if row.dispatch_class != "interactive"
    )
    tenant = _tenant_expression(AgentTaskExecutionRecord)
    payload = TaskLifecycleRecord.body_json
    if db.get_bind().dialect.name == "sqlite":
        dispatch_class = func.json_extract(
            case((func.json_valid(payload) == 1, payload), else_="{}"),
            "$.dispatch_policy.class",
        )
    else:
        dispatch_class = func.json_extract_path_text(payload.cast(JSON), "dispatch_policy", "class")
    interactive = func.coalesce(dispatch_class, "background") == "interactive"
    aged_before = (
        datetime.fromisoformat(current) - timedelta(seconds=limits.aging_seconds)
    ).isoformat()
    served = (
        db.query(
            tenant.label("tenant"),
            func.max(AgentTaskExecutionRecord.updated_at).label("at"),
        )
        .filter(
            AgentTaskExecutionRecord.execution_count > 0,
            # Use the existing updated_at index rather than scanning
            # every historical terminal row under the scheduling lock.
            AgentTaskExecutionRecord.updated_at >= aged_before,
        )
        .group_by(tenant)
        .subquery()
    )

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
    candidate_filter.append(
        tenant.not_in([key for key, count in counts.items() if count >= limits.tenant_running])
    )
    candidate_filter.append(
        or_(
            interactive,
            tenant.not_in(
                [
                    key
                    for key, count in background_counts.items()
                    if count >= max(1, limits.tenant_running - 1)
                ]
            ),
        )
    )
    if interactive_only or sum(background_counts.values()) >= max(1, limits.running - 1):
        candidate_filter.append(interactive)
    aged = AgentTaskExecutionRecord.available_at <= aged_before
    candidates = (
        db.query(AgentTaskExecutionRecord)
        .outerjoin(
            TaskLifecycleRecord,
            and_(
                TaskLifecycleRecord.module == "agent",
                TaskLifecycleRecord.tenant_id == AgentTaskExecutionRecord.tenant_id,
                TaskLifecycleRecord.task_id == AgentTaskExecutionRecord.run_id,
            ),
        )
        .outerjoin(served, served.c.tenant == tenant)
        .filter(*candidate_filter)
        .order_by(
            case(dict(counts), value=tenant, else_=0) if counts else literal(0),
            func.coalesce(served.c.at, ""),
            case((aged, 0), else_=1),
            case((aged, 0), else_=AgentTaskExecutionRecord.priority),
            AgentTaskExecutionRecord.available_at.asc(),
            AgentTaskExecutionRecord.created_at.asc(),
            AgentTaskExecutionRecord.run_id.asc(),
        )
        .limit(8)
        .all()
    )
    return candidates, eligible
