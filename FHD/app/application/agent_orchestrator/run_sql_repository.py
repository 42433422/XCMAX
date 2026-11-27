"""SQLAlchemy persistence for Agent runs, tasks, events, and controls."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict
from typing import cast

from sqlalchemy import JSON, String, Table, and_, case, func, literal, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.agent_orchestrator import run_terminal_metrics
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    RunContextScope,
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
    TaskControlAction,
    TaskControlCommand,
    mod_id_of_run,
    task_from_run,
    tenant_id_of_run,
)

_TASK_ID_PATH = "$.metadata.task_context.task_id"
_TENANT_PATH = "$.metadata.runtime_context.tenant_id"
_MOD_PATH = "$.metadata.runtime_context._mod_authorization.mod_id"


def _sqlite_identity_columns(column, *paths: str):
    strict_json = func.json_valid(column) == 1
    # Multi-path JSON1 extraction preserves scalar types. Non-strict rows use
    # the existing mapper, which accepts Python JSON values such as NaN.
    return (
        case((strict_json, func.json_extract(column, *paths))).label("identity_json"),
        case((~strict_json, column)).label("payload_json"),
    )


def _sqlite_identity_candidates(column, path: str, expected: str):
    # Only reject definite mismatches in SQL. The mapper compares uncommon
    # non-string identities using the same conversion as existing task records.
    return case(
        (
            func.json_valid(column) == 1,
            or_(
                func.coalesce(func.json_extract(column, path), "") == expected,
                func.json_type(column, path).not_in(("text", "null")),
            ),
        ),
        else_=True,
    )


def _runtime_scope_candidates(column, scope: RunContextScope, dialect: str):
    """Reject definite scope mismatches before transferring/hydrating full runs.

    Keep nonstandard legacy payloads and ambiguous scalar conversions for the
    ordinary mapper and Python predicates; no recent-history window is imposed.
    PostgreSQL 16 is the supported server image in docker-compose.yml.
    """
    if dialect == "sqlite":
        valid = func.json_valid(column) == 1
        sqlite_payload = case((valid, column), else_="{}")

        def field(key):
            path = f"$.metadata.runtime_context.{key}"
            value = func.json_extract(sqlite_payload, path)
            kind = func.json_type(sqlite_payload, path)
            kind = case(
                (and_(kind == "integer", func.typeof(value) != "integer"), "real"),
                else_=kind,
            )
            return value, kind

        revision = field("_conversation_revision")[0] == scope.revision
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        valid = func.pg_input_is_valid(column, "jsonb")
        # Guard the cast itself: SQL planners may reorder WHERE expressions.
        postgres_payload = sql_cast(case((valid, column), else_="{}"), JSON)

        def field(key):
            path = ("metadata", "runtime_context", key)
            value = func.json_extract_path_text(postgres_payload, *path)
            kind = func.json_typeof(func.json_extract_path(postgres_payload, *path))
            return value, case(
                (kind == "string", "text"),
                (
                    and_(kind == "number", value.op("~")(r"^(0|-?[1-9][0-9]*)$")),
                    "integer",
                ),
                (kind == "boolean", value),
                else_=kind,
            )

        raw_revision = func.json_extract_path(
            postgres_payload, "metadata", "runtime_context", "_conversation_revision"
        )
        revision = sql_cast(raw_revision, JSONB) == sql_cast(
            literal(str(int(scope.revision))), JSONB
        )
        if scope.revision in (0, 1):
            revision = or_(
                revision,
                sql_cast(raw_revision, JSONB)
                == sql_cast(literal("true" if scope.revision else "false"), JSONB),
            )
    else:
        return True

    predicates = [revision]
    for keys, expected in (
        (("tenant_id",), scope.tenant_id),
        (("mod_id", "active_mod_id"), scope.mod_id),
        (("session_id", "conversation_id"), scope.session_id),
    ):
        fields = [field(key) for key in keys]
        values = [
            case(
                (kind == "text", func.nullif(value, "")),
                (kind == "integer", func.nullif(sql_cast(value, String), "0")),
                (kind == "true", "True"),
            )
            for value, kind in fields
        ]
        if keys == ("tenant_id",):
            # Continuation uses str(saved.get("tenant_id")), without the
            # truthy fallback used by Mod/session aliases and active views.
            value, kind = fields[0]
            values = [
                case(
                    (kind == "text", value),
                    (kind == "integer", sql_cast(value, String)),
                    (kind == "true", "True"),
                    (kind == "false", "False"),
                    else_="None",
                )
            ]
        predicates.append(
            or_(
                func.coalesce(*values, "") == expected,
                *(kind.not_in(("text", "integer", "true", "false", "null")) for _, kind in fields),
            )
        )
    return case((valid, and_(*predicates)), else_=True)


def _explicit_task_id(run: AgentRun) -> str:
    context = run.metadata.get("task_context")
    return str(context.get("task_id") or "") if isinstance(context, dict) else ""


def same_run_generation(run: AgentRun, previous: AgentRun) -> bool:
    def context(value):
        return {
            key: item
            for key, item in (value.metadata.get("runtime_context") or {}).items()
            # Tool observations are appended while registered child runs write
            # their original parent links. They do not create a new authority
            # generation or authorize discarding those concurrent receipts.
            if key not in {"run_id", "agent_run_id", "untrusted_sources", "context_summary"}
        }

    return (run.run_id, run.user_id, run.created_at, context(run)) == (
        previous.run_id,
        previous.user_id,
        previous.created_at,
        context(previous),
    )


def _planning_generation(run: AgentRun) -> str:
    context = run.metadata.get("runtime_context") or {}
    return str(context.get("_planning_clarification_snapshot") or "") or next(
        (
            event.event_id
            for event in reversed(run.events)
            if event.event_type == "run.clarification_resumed"
            and event.data.get("kind") == "planning_scope"
        ),
        "",
    )


def _valid_planning_replacement(run: AgentRun, previous: AgentRun) -> bool:
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.clarification import (
        find_waiting_step,
        is_planning_clarification,
    )

    waiting = find_waiting_step(previous)
    event = run.events[-1] if run.events else None
    return bool(
        waiting is not None
        and is_planning_clarification(previous, waiting)
        and run.plan_id == previous.plan_id
        and not run.tool_calls
        and (run.metadata.get("runtime_context") or {}).get("_planning_clarification_snapshot")
        == canonical_hash(previous.to_dict())
        and event is not None
        and event.event_type == "run.clarification_resumed"
        and event.data.get("kind") == "planning_scope"
        and event.data.get("step_id") == waiting.step_id
    )


def preserve_run_evidence(
    run: AgentRun,
    previous: AgentRun | None,
    *,
    allow_safe_retry: bool = False,
    allow_planning_replacement: bool = False,
    allow_verified_xiaox_recovery: bool = False,
) -> None:
    """Keep receipts across mutable context updates; only a verified CAS replaces a plan."""
    if previous is None:
        return
    from app.application.agent_orchestrator.verification_integrity import (
        preserve_verification_receipts,
        unchanged_receipt_observation,
        verified_pending_settlement,
    )

    preserve_verification_receipts(run, previous)
    if (run.run_id, run.user_id, run.created_at, tenant_id_of_run(run), mod_id_of_run(run)) != (
        previous.run_id,
        previous.user_id,
        previous.created_at,
        tenant_id_of_run(previous),
        mod_id_of_run(previous),
    ):
        raise ValueError("run identity cannot change")
    generation, prior_generation = _planning_generation(run), _planning_generation(previous)
    if generation or prior_generation:
        if generation != prior_generation:
            if not allow_planning_replacement or not _valid_planning_replacement(run, previous):
                raise ValueError(
                    "planning generation replacement requires the original snapshot CAS"
                )
            return
    old = previous.metadata
    settled_pending = allow_planning_replacement and verified_pending_settlement(run, previous)
    settled_xiaox = bool(
        allow_verified_xiaox_recovery
        and previous.metadata.get("runtime_type") == "xiaox"
        and previous.status in {"running", "waiting_user", "unknown"}
        and (old.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        and not old.get("stream_interruption")
        and not run.metadata.get("recovery")
        and not run.metadata.get("non_retryable")
        and (run.final_output.get("xiaox_result") or {}).get("exit_status")
        == "continuation_pending"
        and any(event.event_type == "runtime.reconciliation.verified" for event in run.events)
    )
    if allow_verified_xiaox_recovery and not settled_xiaox:
        raise ValueError("Xiaox recovery requires the verified original child transition")
    if old.get("non_retryable") and not (settled_pending or settled_xiaox):
        run.metadata["non_retryable"] = True
    recovery = {
        **({} if settled_pending or settled_xiaox else copy.deepcopy(old.get("recovery") or {})),
        **(run.metadata.get("recovery") or {}),
    }
    if (old.get("recovery") or {}).get(
        "state"
    ) == "manual_reconciliation_required" and not settled_xiaox:
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
    children = copy.deepcopy(old.get("child_results") or {})
    terminal = {"completed", "failed", "cancelled", "rejected"}
    for child_id, receipt in (run.metadata.get("child_results") or {}).items():
        if (
            not isinstance(receipt, dict)
            or receipt.get("parent_run_id") != run.run_id
            or receipt.get("tenant_id") != tenant_id_of_run(run)
        ):
            raise ValueError("child result does not belong to this parent run")
        prior = children.get(child_id)
        if prior is not None:
            if any(
                prior.get(key) != receipt.get(key)
                for key in ("parent_task_id", "parent_run_id", "tenant_id", "employee_id")
            ):
                raise ValueError("child result identity cannot change")
            if prior.get("status") in terminal:
                if receipt.get("status") not in terminal:
                    continue
                if prior != receipt:
                    raise ValueError("terminal child result cannot change")
        children[child_id] = receipt
    if children:
        run.metadata["child_results"] = children
    from app.application.agent_orchestrator.result_verification import (
        latest_step_call,
        preview_continuation_params,
    )

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
            preview_call = latest_step_call(previous, item) if field == "steps" else None
            preview_pause = bool(
                preview_call is not None
                and replacement is not None
                and replacement.status == "waiting_user"
                and replacement.output == preview_call.output
                and replacement.params == preview_continuation_params(previous, item, preview_call)
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
                    and not preview_pause
                )
            ) and getattr(replacement, "attempt_count", 0) <= getattr(item, "attempt_count", 0):
                # Keep the executor's step/call object alive: repair and result
                # processing retain this reference across repository checkpoints.
                observation = (
                    unchanged_receipt_observation(item, replacement)
                    if field == "tool_calls"
                    else None
                )
                replacement.__dict__.update(copy.deepcopy(item.__dict__))
                if observation is not None:
                    replacement.metadata["verification"] = observation
            combined[key] = replacement
        combined.update(incoming)
        setattr(run, field, list(combined.values()))
    events = {event.event_id: copy.deepcopy(event) for event in previous.events}
    for event in run.events:
        events.setdefault(event.event_id, event)
    run.events = list(events.values())
    if not (allow_safe_retry or settled_xiaox) and (
        (previous.status in terminal and run.status != previous.status)
        or (
            previous.status == "unknown"
            and run.status != previous.status
            and (
                old.get("non_retryable")
                or (old.get("recovery") or {}).get("state") == "manual_reconciliation_required"
            )
        )
        or (
            previous.status in {"paused", "blocked"}
            and run.status in {"queued", "planning", "running", "retrying"}
            and (
                old.get("stream_interruption")
                or old.get("non_retryable")
                or (old.get("recovery") or {}).get("state") == "manual_reconciliation_required"
            )
        )
    ):
        run.status, run.error = previous.status, previous.error
        run.final_output = {**run.final_output, **copy.deepcopy(previous.final_output)}
    if run.status == "cancelled" and (
        run.metadata.get("non_retryable")
        or recovery.get("state") == "manual_reconciliation_required"
    ):
        run.error = "任务已停止继续执行；已有调用结果仍需人工核对"
    if any(call.metadata.get("verification_contract") for call in run.tool_calls):
        from app.application.agent_orchestrator.result_verification import project_verification

        # The visible verdict follows the receipts actually retained above,
        # including rejected attempts to rewrite an unknown execution.
        project_verification(run)


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

    @property
    def allows_schema_setup(self) -> bool:
        """Native checkpoints share the repository's explicit provisioning policy."""
        return self._auto_create

    def save(self, run: AgentRun) -> AgentRun:
        self._ensure_schema()
        with self._session_scope() as db:
            self.save_in_session(db, run)
        return self.get(run.run_id) or copy.deepcopy(run)

    def create_task_run(self, run: AgentRun, *, initial_only: bool = True) -> tuple[AgentRun, bool]:
        """Publish once; False admits an exact attempt/child under its existing task."""
        if not initial_only:
            from app.db.models.agent import AgentRunRecord

            try:
                with self.transaction() as db:
                    self._lock_task_record(db, task_from_run(run))
                    record = db.get(AgentRunRecord, run.run_id)
                    if record is not None:
                        current = self._record_to_run(record)
                        # The run may already belong to another task. Do not leave
                        # an admission-only task row or save a losing snapshot.
                        db.rollback()
                        if current is None:
                            raise ValueError("任务账本缺少执行记录")
                        return current, False
                    self.save_in_session(db, run)
            except IntegrityError:
                # Distinct task scopes can race on the same deterministic run ID.
                # The unique run row wins; the losing transaction creates nothing.
                current = self.get(run.run_id)
                if current is None:
                    raise
                return current, False
            return copy.deepcopy(run), True
        with self.transaction() as db:
            created = self._insert_task_record(db, task_from_run(run))
            if not created:
                from app.db.models.agent import AgentRunRecord, AgentTaskRecord

                task = (
                    db.query(AgentTaskRecord)
                    .filter_by(
                        tenant_id=tenant_id_of_run(run),
                        user_id=run.user_id,
                        task_id=self._run_task_id(run),
                    )
                    .one()
                )
                record = db.get(AgentRunRecord, task.active_run_id) if task.active_run_id else None
                current = self._record_to_run(record) if record is not None else None
                if current is None:
                    raise ValueError("任务账本缺少执行记录")
                return current, False
            self.save_in_session(db, run)
        return copy.deepcopy(run), True

    def save_stream_interruption_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        return valid_stream_interruption_update(run, previous) and self.save_if_unchanged(
            run, previous
        )

    def save_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        """CAS the complete snapshot, retaining the row lock through task persistence."""
        with self.transaction() as db:
            return self.save_if_unchanged_in_session(db, run, previous)

    def save_control_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        return valid_control_update(run, previous) and self.save_if_unchanged(run, previous)

    def save_stream_tool_audit_if_unchanged(self, run: AgentRun, previous: AgentRun) -> bool:
        return valid_stream_tool_audit_update(run, previous) and self.save_if_unchanged(
            run, previous
        )

    def save_if_unchanged_in_session(
        self,
        db: Session,
        run: AgentRun,
        previous: AgentRun,
        *,
        allow_verified_xiaox_recovery: bool = False,
    ) -> bool:
        from app.db.models.agent import AgentRunRecord

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
        self.save_in_session(
            db,
            run,
            allow_planning_replacement=True,
            allow_verified_xiaox_recovery=allow_verified_xiaox_recovery,
        )
        return True

    def save_in_session(
        self,
        db: Session,
        run: AgentRun,
        *,
        allow_safe_retry: bool = False,
        allow_planning_replacement: bool = False,
        allow_verified_xiaox_recovery: bool = False,
    ) -> None:
        """Lock then persist in the caller's transaction, preserving concurrent receipts."""
        from app.application.agent_orchestrator.business_harness import (
            ensure_terminal_business_result,
        )
        from app.db.models.agent import AgentRunRecord

        db.query(AgentRunRecord).filter(AgentRunRecord.run_id == run.run_id).update(
            {AgentRunRecord.status: AgentRunRecord.status}, synchronize_session=False
        )
        record = db.get(AgentRunRecord, run.run_id, populate_existing=True)
        previous = self._record_to_run(record) if record is not None else None
        if allow_safe_retry:
            from app.application.agent_orchestrator.run_lifecycle import validate_safe_retry_update

            if previous is None:
                raise ValueError("原任务不存在，不能续跑")
            validate_safe_retry_update(run, previous)
        from app.application.agent_orchestrator.catalog_authority_retention import (
            preserve_catalog_run_authority,
        )

        catalog_fenced = preserve_catalog_run_authority(db, run, previous)
        preserve_run_evidence(
            run,
            previous,
            allow_safe_retry=allow_safe_retry,
            allow_planning_replacement=allow_planning_replacement,
            allow_verified_xiaox_recovery=allow_verified_xiaox_recovery,
        )
        if catalog_fenced:
            # A signed permanent dispatch fence supersedes a previous failure;
            # the generic terminal-state guard still retains its original receipt.
            run.status = "cancelled"
        ensure_terminal_business_result(run)
        run_terminal_metrics.record_terminal_transition(run, previous, db)
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
        # Different run rows can belong to one task. Serialize the shared
        # projection as well as the run so an older attempt cannot win last.
        existing_task = self._task_record_to_model(self._lock_task_record(db, task_from_run(run)))
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
        matches: Callable[[AgentRun], bool] | None = None,
        runtime_scope: RunContextScope | None = None,
        status: str | None = None,
    ) -> list[AgentRun]:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            query = db.query(AgentRunRecord)
            if user_id is not None:
                query = query.filter(AgentRunRecord.user_id == str(user_id))
            if status is not None:
                query = query.filter(AgentRunRecord.status == status)
            if runtime_scope is not None:
                query = query.filter(
                    _runtime_scope_candidates(
                        AgentRunRecord.payload_json, runtime_scope, db.get_bind().dialect.name
                    )
                )
            query = query.order_by(AgentRunRecord.updated_at.desc())
            if tenant_id is None and mod_id is None and matches is None and runtime_scope is None:
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
                    and (runtime_scope is None or runtime_scope.matches(run))
                    and (matches is None or matches(run))
                ):
                    result.append(run)
                    if len(result) >= limit:
                        break
            return result

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[AgentRun]:
        """Resolve a durable task without relying on a recent-run window.

        ``task_id`` currently lives in the versioned AgentRun payload. SQLite
        preselects candidate runs before the mapper compares task identities.
        """
        self._ensure_schema()
        wanted_task = str(task_id or "")
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            query = db.query(AgentRunRecord).filter(AgentRunRecord.user_id == str(user_id or ""))
            if db.get_bind().dialect.name == "sqlite":
                query = query.filter(
                    _sqlite_identity_candidates(
                        AgentRunRecord.payload_json, _TASK_ID_PATH, wanted_task
                    )
                )
            records = query.order_by(
                AgentRunRecord.created_at.asc(), AgentRunRecord.run_id.asc()
            ).all()
            runs: list[AgentRun] = []
            for record in records:
                run = self._record_to_run(record)
                if run is None:
                    continue
                context = run.metadata.get("task_context")
                if isinstance(context, dict) and str(context.get("task_id") or "") == wanted_task:
                    runs.append(run)
            return runs

    def storage_identity(self) -> object:
        """Bind view caches to the actual database, including desktop DB switches."""
        with self._session_scope(read_only=True) as db:
            return db.get_bind()

    def list_run_scopes(self, *, user_id: str) -> dict[str, list[tuple[str, str, str]]]:
        """Read current authorization scopes without hydrating unrelated payload fields."""
        user_id = str(user_id or "")
        self._ensure_schema()
        scopes: dict[str, list[tuple[str, str, str]]] = {}
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            if db.get_bind().dialect.name == "sqlite":
                # 只解析任务归属字段，避免构建每条运行的完整对象。
                rows = (
                    db.query(
                        *_sqlite_identity_columns(
                            AgentRunRecord.payload_json,
                            "$.user_id",
                            _TASK_ID_PATH,
                            _TENANT_PATH,
                            _MOD_PATH,
                        )
                    )
                    .filter(AgentRunRecord.user_id == user_id)
                    .all()
                )
                for row in rows:
                    if row.identity_json is None:
                        run = self._record_to_run(row)
                        if run is None or not (task_id := _explicit_task_id(run)):
                            continue
                        scope = (run.user_id, tenant_id_of_run(run), mod_id_of_run(run))
                    else:
                        raw_user, raw_task, raw_tenant, raw_mod = json.loads(row.identity_json)
                        task_id = str(raw_task or "")
                        scope = (str(raw_user or ""), str(raw_tenant or ""), str(raw_mod or ""))
                    if task_id:
                        scopes.setdefault(task_id, []).append(scope)
                return scopes
        for run in self.list_task_runs_for_user(user_id=user_id):
            if task_id := _explicit_task_id(run):
                scopes.setdefault(task_id, []).append(
                    (run.user_id, tenant_id_of_run(run), mod_id_of_run(run))
                )
        return scopes

    def recent_task_refs(
        self, *, user_id: str | None = None, tenant_id: str | None = None, limit: int = 200
    ) -> list[tuple[str, str, str]]:
        """Read recent (run_id, task_id, tenant_id) with SQLite projections."""
        limit = max(0, int(limit))
        if not limit:
            return []
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            if db.get_bind().dialect.name == "sqlite":
                query = db.query(
                    AgentRunRecord.run_id,
                    *_sqlite_identity_columns(
                        AgentRunRecord.payload_json, _TASK_ID_PATH, _TENANT_PATH
                    ),
                )
                if user_id is not None:
                    query = query.filter(AgentRunRecord.user_id == str(user_id))
                query = query.order_by(AgentRunRecord.updated_at.desc())
                if tenant_id is not None:
                    query = query.filter(
                        _sqlite_identity_candidates(
                            AgentRunRecord.payload_json, _TENANT_PATH, tenant_id
                        )
                    )
                else:
                    query = query.limit(limit)
                refs: list[tuple[str, str, str]] = []
                matched = 0
                for row in query.yield_per(100):
                    if row.identity_json is None:
                        run = self._record_to_run(row)
                        if run is None:
                            continue
                        task_id, run_tenant = _explicit_task_id(run), tenant_id_of_run(run)
                    else:
                        raw_task, raw_tenant = json.loads(row.identity_json)
                        task_id, run_tenant = str(raw_task or ""), str(raw_tenant or "")
                    if tenant_id is not None and run_tenant != tenant_id:
                        continue
                    if task_id:
                        refs.append((row.run_id, task_id, run_tenant))
                    matched += 1
                    if matched >= limit:
                        break
                return refs
        return [
            (run.run_id, task_id, tenant_id_of_run(run))
            for run in self.list_recent(user_id=user_id, tenant_id=tenant_id, limit=limit)
            if (task_id := _explicit_task_id(run))
        ]

    def task_keys(self, *, user_id: str) -> set[tuple[str, str]]:
        """Existing (tenant_id, task_id) pairs so callers need no per-run lookup."""
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentTaskRecord

            rows = (
                db.query(AgentTaskRecord.tenant_id, AgentTaskRecord.task_id)
                .filter(AgentTaskRecord.user_id == str(user_id or ""))
                .all()
            )
            return {(str(tenant or ""), str(task_id or "")) for tenant, task_id in rows}

    def list_task_runs_for_user(self, *, user_id: str) -> list[AgentRun]:
        """All runs of one principal, hydrated once (used by scope filtering)."""
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.agent import AgentRunRecord

            records = (
                db.query(AgentRunRecord).filter(AgentRunRecord.user_id == str(user_id or "")).all()
            )
            return [
                run
                for run in (self._record_to_run(record) for record in records)
                if run is not None
            ]

    def save_task(self, task: AgentTask) -> AgentTask:
        self._ensure_schema()
        with self._session_scope() as db:
            current = self._task_record_to_model(self._lock_task_record(db, task))
            if (current.active_run_id, current.attempt, current.updated_at) != (
                task.active_run_id,
                task.attempt,
                task.updated_at,
            ):
                return current
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
            action=cast(TaskControlAction, str(action)),
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
        with closing(session_factory()) as db, ExitStack() as rollback:
            # Failed reads also roll back; inactive sessions only need closing.
            rollback.callback(lambda: db.rollback() if db.is_active else None)
            yield db
            if not read_only:
                db.commit()
            rollback.pop_all()

    def _ensure_schema(self) -> None:
        # 就绪状态按 bind（引擎实例）键控：引擎缓存按 URL 解析，测试/多库环境下
        # DATABASE_URL 可能被切换（如桌面 runtime 直接改写 env），裸布尔会把
        # "A 库已建表"错误外推到 B 库（no such table: agent_runs）。
        # 与 task_execution_sql_repository._ensure_schema 的 bind-identity 模式一致。
        if not self._auto_create:
            return
        with self._schema_lock:
            with self._session_scope(read_only=True) as db:
                from app.db.bootstrap.orm_tables import _serialized_schema_bind
                from app.db.db_base import Base
                from app.db.models.agent import (
                    AgentRunRecord,
                    AgentTaskCommandRecord,
                    AgentTaskRecord,
                )

                bind = db.get_bind()
                if self._schema_ready and self._schema_bind is bind:
                    return
                with _serialized_schema_bind(bind) as schema_bind:
                    Base.metadata.create_all(
                        bind=schema_bind,
                        tables=[
                            cast(Table, AgentRunRecord.__table__),
                            cast(Table, AgentTaskRecord.__table__),
                            cast(Table, AgentTaskCommandRecord.__table__),
                        ],
                        checkfirst=True,
                    )
                self._schema_bind = bind
            # DDL on a caller-owned Connection can still be rolled back later.
            self._schema_ready = isinstance(bind, Engine)

    @staticmethod
    def _run_task_id(run: AgentRun | None) -> str:
        if run is None:
            return ""
        context = run.metadata.get("task_context")
        if isinstance(context, dict):
            return str(context.get("task_id") or run.run_id)
        return run.run_id

    @staticmethod
    def _task_record_values(task: AgentTask) -> dict:
        values = asdict(task)
        values["metadata_json"] = json.dumps(
            values.pop("metadata"), ensure_ascii=False, default=str
        )
        for key in (
            "active_run_id",
            "root_run_id",
            "conversation_id",
            "workspace_id",
            "workspace_path",
            "archived_at",
        ):
            values[key] = values[key] or None
        return values

    @classmethod
    def _insert_task_record(cls, db: Session, task: AgentTask) -> bool:
        from app.db.models.agent import AgentTaskRecord

        values = cls._task_record_values(task)
        dialect = db.get_bind().dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise ValueError(f"Unsupported task repository dialect: {dialect}")
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        statement = (
            insert(AgentTaskRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "user_id", "task_id"])
        )
        if dialect == "postgresql":
            # psycopg resets rowcount when implicit RETURNING closes its cursor.
            return (
                db.execute(statement.returning(AgentTaskRecord.id)).scalar_one_or_none() is not None
            )
        return cast(CursorResult, db.execute(statement)).rowcount == 1

    @classmethod
    def _lock_task_record(cls, db: Session, task: AgentTask):
        from app.db.models.agent import AgentTaskRecord

        cls._insert_task_record(db, task)
        query = db.query(AgentTaskRecord).filter_by(
            tenant_id=task.tenant_id, user_id=task.user_id, task_id=task.task_id
        )
        query.update(
            {AgentTaskRecord.updated_at: AgentTaskRecord.updated_at}, synchronize_session=False
        )
        return query.populate_existing().one()

    @classmethod
    def _save_task_record(cls, db: Session, task: AgentTask) -> None:
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
        values = cls._task_record_values(task)
        if record is None:
            db.add(AgentTaskRecord(**values))
        else:
            for key, value in values.items():
                setattr(record, key, value)

    _task_record_to_model = staticmethod(_task_record_to_model)
    _command_record_to_model = staticmethod(_command_record_to_model)
    _record_to_run = staticmethod(_record_to_run)


__all__ = ["SQLAlchemyAgentRunRepository"]
