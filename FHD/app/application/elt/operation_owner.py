"""Database-owned leases with fencing on writes made by an ETL worker's Session.

The fence update locks the run row until the business transaction commits. A
takeover therefore cannot interleave with a row write after its token check.
Separate-session/external batch effects are not transactional under this fence;
expired batch ownership is intentionally never automatically reclaimed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Table, and_, case, event, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.elt.errors import EltConflict, EltError
from app.application.elt.service_support import utcnow
from app.db.models.elt import EltRun, EltRunRow
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
LEASE_SECONDS = 300
_SESSION_KEY = "elt_operation_owner"
_SKIP_FENCE = "elt_internal_owner_dml"
# An owned process can disappear after dispatch but before its receipt. Its
# lease must not authorize a replacement, including transactional row adapters.
OWNED_EXECUTE = "owned_execute"
BATCH_KINDS = frozenset({"batch_execute", "batch_rollback", OWNED_EXECUTE})
TRANSACTION_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, *RECOVERABLE_ERRORS)
_RUN_TABLE = cast("Table", EltRun.__table__)
_ROW_RECEIPT_FIELDS = (
    "id",
    "execution_status",
    "match_ref",
    "after_json",
    "execution_error_code",
    "execution_error_message",
)


@dataclass(frozen=True)
class OperationOwner:
    run_id: str
    owner_user_id: int
    tenant_id: int
    kind: str
    token: str


def row_receipts(rows: list[EltRunRow]) -> list[tuple[Any, ...]]:
    return [tuple(getattr(row, field) for field in _ROW_RECEIPT_FIELDS) for row in rows]


def release_transaction(db: Session) -> bool:
    """End a failed SQLAlchemy transaction without detaching the worker's rows."""
    try:
        db.rollback()
    except TRANSACTION_ERRORS:
        # An after_commit observer may raise while the transaction is COMMITTED;
        # rollback is then illegal. Closing that transaction preserves the
        # Session identity map so independently confirmed rows can be refreshed.
        try:
            for transaction in (db.get_nested_transaction(), db.get_transaction()):
                if transaction is not None:
                    transaction.close()
        except TRANSACTION_ERRORS:
            return False
    return not db.in_transaction() and not db.in_nested_transaction()


def commit_rows(
    db: Session,
    run: EltRun,
    owner: OperationOwner,
    before: tuple[int, list[tuple[Any, ...]]],
    rows: list[EltRunRow],
    *,
    session_factory: Callable[[], Session],
) -> None:
    """Recover a lost SQL commit ACK by reading the atomic ledger, never by writing again."""
    expected = (run.executed_rows, row_receipts(rows))
    bind = db.get_bind()
    try:
        db.commit()
    except TRANSACTION_ERRORS as exc:
        released = release_transaction(db)
        try:
            with session_factory() as check:
                if check is db or check.get_bind() is not bind:
                    raise EltError("ELT_OUTCOME_UNKNOWN", "无法独立核对原写入数据库")
                current = (
                    check.query(EltRun)
                    .filter_by(
                        id=owner.run_id,
                        tenant_id=owner.tenant_id,
                        owner_user_id=owner.owner_user_id,
                        operation_token=owner.token,
                        operation_kind=owner.kind,
                    )
                    .one_or_none()
                )
                saved = (
                    check.query(EltRunRow)
                    .filter(
                        EltRunRow.run_id == owner.run_id,
                        EltRunRow.tenant_id == owner.tenant_id,
                        EltRunRow.owner_user_id == owner.owner_user_id,
                        EltRunRow.id.in_([item[0] for item in expected[1]]),
                    )
                    .order_by(EltRunRow.id)
                    .all()
                )
                observed = (current.executed_rows, row_receipts(saved)) if current else None
        except TRANSACTION_ERRORS as read_error:
            raise EltError(
                "ELT_OUTCOME_UNKNOWN", "提交回执丢失且无法独立核对，已停止重复执行"
            ) from read_error
        if not released:
            raise EltError("ELT_OUTCOME_UNKNOWN", "原事务连接无法安全恢复，已停止重复执行") from exc
        db.expire_all()
        if observed == expected:
            return
        if observed == before:
            raise exc
        raise EltError("ELT_OUTCOME_UNKNOWN", "提交回执与原事务不一致，已停止重复执行") from exc


def _clock(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return func.clock_timestamp()
    return func.strftime("%Y-%m-%d %H:%M:%f", "now")


def _expiry(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return _clock(db) + timedelta(seconds=LEASE_SECONDS)
    return func.strftime("%Y-%m-%d %H:%M:%f", "now", f"+{LEASE_SECONDS} seconds")


def _scope(owner: OperationOwner) -> list[Any]:
    columns = EltRun.__table__.c
    return [
        columns.id == owner.run_id,
        columns.tenant_id == owner.tenant_id,
        columns.owner_user_id == owner.owner_user_id,
    ]


def _dml(db: Session, statement: Any):
    with db.no_autoflush:
        return db.execute(statement, execution_options={_SKIP_FENCE: True})


def claim_operation(
    db: Session,
    run: EltRun,
    kind: str,
    *,
    allowed_statuses: set[str],
    require_unrolled_back: bool = False,
) -> OperationOwner:
    owner = OperationOwner(run.id, run.owner_user_id, tenant_id_for_write(), kind, str(uuid4()))
    columns = EltRun.__table__.c
    available = or_(
        columns.operation_token.is_(None),
        and_(
            columns.operation_lease_until <= _clock(db),
            columns.operation_kind.not_in(BATCH_KINDS),
        ),
    )
    conditions = [
        *_scope(owner),
        available,
        columns.status.in_(allowed_statuses),
        columns.status != "outcome_unknown",
    ]
    if require_unrolled_back:
        conditions.append(columns.rollback_status.is_(None))
    elif kind in {"rollback", "batch_rollback"}:
        conditions.append(
            or_(
                columns.rollback_status.is_(None),
                columns.rollback_status.not_in(["completed", "outcome_unknown"]),
            )
        )
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(*conditions)
        .values(
            operation_kind=kind, operation_token=owner.token, operation_lease_until=_expiry(db)
        ),
    )
    if result.rowcount != 1:
        raise EltConflict("ELT_RUN_BUSY", "本次运行已有活动任务或结果尚待核对，请稍后查看处理状态")
    return owner


def activate_operation(db: Session, run: EltRun, kind: str, token: str) -> OperationOwner:
    owner = OperationOwner(run.id, run.owner_user_id, tenant_id_for_write(), kind, token)
    queued_kind = (
        "execute_start"
        if kind == OWNED_EXECUTE
        else "execute_queue"
        if kind in {"execute", "batch_execute"}
        else "preview_queue"
    )
    queued_kinds = {queued_kind, "preview_start"} if kind == "preview" else {queued_kind}
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            _RUN_TABLE.c.operation_token == token,
            _RUN_TABLE.c.operation_kind.in_(queued_kinds),
            _RUN_TABLE.c.operation_lease_until > _clock(db),
        )
        .values(operation_kind=kind, operation_lease_until=_expiry(db)),
    )
    if result.rowcount != 1:
        raise EltConflict(
            "ELT_OPERATION_LEASE_LOST", "任务已被其他 worker 领取或执行权已失效，已停止重复执行"
        )
    return owner


def freeze_background_operation(db: Session, owner: OperationOwner) -> OperationOwner:
    """Only one server process may dispatch this queued token to an owned child."""
    kind = "execute_start" if owner.kind == "execute_queue" else "preview_start"
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            _RUN_TABLE.c.operation_token == owner.token,
            _RUN_TABLE.c.operation_kind == owner.kind,
            _RUN_TABLE.c.operation_lease_until > _clock(db),
        )
        .values(operation_kind=kind, operation_lease_until=_expiry(db)),
    )
    if result.rowcount != 1:
        raise EltConflict("ELT_RUN_BUSY", "任务已提交或执行权已失效，已停止重复提交")
    return replace(owner, kind=kind)


def bind_owner(db: Session, owner: OperationOwner) -> None:
    db.info[_SESSION_KEY] = owner


def unbind_owner(db: Session) -> None:
    db.info.pop(_SESSION_KEY, None)


def fence_operation(db: Session, owner: OperationOwner, *, record_progress: bool = True) -> None:
    if tenant_id_for_write() != owner.tenant_id:
        raise EltConflict("ELT_OPERATION_LEASE_LOST", "任务租户上下文已改变，已停止写入")
    columns = EltRun.__table__.c
    values = {"operation_lease_until": _expiry(db)}
    if not record_progress:
        values["updated_at"] = columns.updated_at
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            columns.operation_kind == owner.kind,
            columns.operation_token == owner.token,
            columns.operation_lease_until > _clock(db),
        )
        .values(**values),
    )
    if result.rowcount != 1:
        raise EltConflict(
            "ELT_OPERATION_LEASE_LOST", "任务执行权已失效，已停止写入，请刷新运行状态"
        )


@contextmanager
def keep_preview_lease(owner: OperationOwner, new_session: Callable[[], Session]) -> Iterator[None]:
    """Keep ownership during a blocking read phase, bounded by the stale-run window."""
    from app.application.elt.stale_watchdog import stale_after_seconds

    stop = Event()
    deadline = monotonic() + stale_after_seconds()

    def heartbeat() -> None:
        while not stop.wait(LEASE_SECONDS / 3) and monotonic() < deadline:
            try:
                with new_session() as db:
                    fence_operation(db, owner, record_progress=False)
                    db.commit()
            except EltConflict:
                return
            except RECOVERABLE_ERRORS:
                logger.warning(
                    "Unable to renew ELT preview lease for %s", owner.run_id, exc_info=True
                )

    thread = Thread(target=copy_context().run, args=(heartbeat,), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def finish_operation(db: Session, owner: OperationOwner) -> None:
    db.flush()
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(*_scope(owner), EltRun.__table__.c.operation_token == owner.token)
        .values(operation_kind=None, operation_token=None, operation_lease_until=None),
    )
    if result.rowcount != 1:
        raise EltConflict("ELT_OPERATION_LEASE_LOST", "任务执行权已转移，不能覆盖当前运行结果")
    unbind_owner(db)


def fail_operation(
    db: Session,
    owner: OperationOwner,
    *,
    code: str,
    message: str,
    outcome_unknown: bool = False,
    receipt_json: str | None = None,
    not_started: bool = False,
) -> bool:
    """A stale worker may never overwrite a replacement owner's status or token."""
    db.rollback()
    unbind_owner(db)
    values: dict[str, Any] = {
        "error_code": "ELT_OUTCOME_UNKNOWN" if outcome_unknown else code,
        "error_message": (
            "执行结果无法确认，已停止自动重试，请核对实际结果后人工处理"
            if outcome_unknown
            else message[:500]
        ),
    }
    if receipt_json is not None:
        values["receipt_json"] = receipt_json
    if owner.kind in {"rollback", "batch_rollback"}:
        values["rollback_status"] = "outcome_unknown" if outcome_unknown else "failed"
    if outcome_unknown or owner.kind not in {"rollback", "batch_rollback"}:
        values["status"] = values["stage"] = "outcome_unknown" if outcome_unknown else "failed"
    if not outcome_unknown:
        values.update(operation_kind=None, operation_token=None, operation_lease_until=None)
    columns = EltRun.__table__.c
    values["executed_at"] = case(
        (and_(columns.executed_rows > 0, columns.executed_at.is_(None)), utcnow()),
        else_=columns.executed_at,
    )
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(*_scope(owner), columns.operation_token == owner.token)
        .values(**values),
    )
    if result.rowcount == 1:
        _audit_terminal_failure(
            db,
            owner,
            outcome="outcome_unknown"
            if outcome_unknown
            else "not_started"
            if not_started
            else "failed",
            code=values["error_code"],
        )
    db.commit()
    return bool(result.rowcount == 1)


def has_active_owner(run: EltRun) -> bool:
    deadline = run.operation_lease_until
    if not run.operation_token or deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return deadline > datetime.now(UTC)


def recover_stale_owner(db: Session, run: EltRun) -> bool:
    if (
        not run.operation_token
        or run.status == "outcome_unknown"
        or run.rollback_status == "outcome_unknown"
        or run.tenant_id is None
        or run.operation_kind is None
        or has_active_owner(run)
    ):
        return False
    owner = OperationOwner(
        run.id, run.owner_user_id, run.tenant_id, run.operation_kind, run.operation_token
    )
    unknown = owner.kind in BATCH_KINDS
    values: dict[str, Any] = {
        "error_code": "ELT_OUTCOME_UNKNOWN" if unknown else "ELT_EXECUTION_INTERRUPTED",
        "error_message": (
            "外部批处理结果无法确认，请核对实际结果后人工处理"
            if unknown
            else "任务执行权已过期，可刷新后重试未完成的步骤"
        ),
    }
    if owner.kind in {"rollback", "batch_rollback"}:
        values["rollback_status"] = "outcome_unknown" if unknown else "failed"
    if unknown or owner.kind != "rollback":
        values["status"] = values["stage"] = "outcome_unknown" if unknown else "interrupted"
    if not unknown:
        values.update(operation_kind=None, operation_token=None, operation_lease_until=None)
    columns = EltRun.__table__.c
    values["executed_at"] = case(
        (and_(columns.executed_rows > 0, columns.executed_at.is_(None)), utcnow()),
        else_=columns.executed_at,
    )
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            columns.operation_token == owner.token,
            columns.operation_lease_until <= _clock(db),
        )
        .values(**values),
    )
    if result.rowcount:
        _audit_terminal_failure(
            db,
            owner,
            outcome="outcome_unknown" if unknown else "interrupted",
            code=values["error_code"],
        )
        db.commit()
        db.refresh(run)
        return True
    return False


def _audit_terminal_failure(db: Session, owner: OperationOwner, *, outcome: str, code: str) -> None:
    from app.application.elt.audit import record_elt_audit

    row = db.execute(
        select(
            EltRun.upload_id,
            EltRun.target_type,
            EltRun.file_sha256,
            EltRun.executed_rows,
            EltRun.executed_at,
        ).where(EltRun.id == owner.run_id)
    ).one()
    record_elt_audit(
        db,
        actor=owner.owner_user_id,
        action="elt_exception",
        payload={
            "run_id": owner.run_id,
            "upload_id": row.upload_id,
            "target_type": row.target_type,
            "file_sha256": row.file_sha256,
            "outcome": outcome,
            "error_code": code,
            "operation_kind": owner.kind,
            "executed_rows": int(row.executed_rows or 0),
            "executed_at": (
                row.executed_at
                if isinstance(row.executed_at, str) or row.executed_at is None
                else row.executed_at.isoformat()
            ),
        },
    )


@event.listens_for(Session, "before_flush")
def _fence_orm_flush(db: Session, _context, _instances) -> None:
    owner = db.info.get(_SESSION_KEY)
    if owner is not None:
        fence_operation(db, owner)


@event.listens_for(Session, "do_orm_execute")
def _fence_session_dml(state) -> None:
    if state.execution_options.get(_SKIP_FENCE):
        return
    owner = state.session.info.get(_SESSION_KEY)
    if owner is not None and (state.is_insert or state.is_update or state.is_delete):
        fence_operation(state.session, owner)
