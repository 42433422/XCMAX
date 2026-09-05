"""Database-owned leases with fencing on writes made by an ETL worker's Session.

The fence update locks the run row until the business transaction commits. A
takeover therefore cannot interleave with a row write after its token check.
Separate-session/external batch effects are not transactional under this fence;
expired batch ownership is intentionally never automatically reclaimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Table, and_, event, func, or_, update
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict
from app.db.models.etl import EtlRun
from app.infrastructure.tenant_scope import tenant_id_for_write

LEASE_SECONDS = 300
_SESSION_KEY = "etl_operation_owner"
_SKIP_FENCE = "etl_internal_owner_dml"
BATCH_KINDS = frozenset({"batch_execute", "batch_rollback"})
_RUN_TABLE = cast("Table", EtlRun.__table__)


@dataclass(frozen=True)
class OperationOwner:
    run_id: str
    owner_user_id: int
    tenant_id: int
    kind: str
    token: str


def _clock(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return func.clock_timestamp()
    return func.strftime("%Y-%m-%d %H:%M:%f", "now")


def _expiry(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return _clock(db) + timedelta(seconds=LEASE_SECONDS)
    return func.strftime("%Y-%m-%d %H:%M:%f", "now", f"+{LEASE_SECONDS} seconds")


def _scope(owner: OperationOwner) -> list[Any]:
    columns = EtlRun.__table__.c
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
    run: EtlRun,
    kind: str,
    *,
    allowed_statuses: set[str],
    require_unrolled_back: bool = False,
) -> OperationOwner:
    owner = OperationOwner(run.id, run.owner_user_id, tenant_id_for_write(), kind, str(uuid4()))
    columns = EtlRun.__table__.c
    available = or_(
        columns.operation_token.is_(None),
        and_(
            columns.operation_lease_until <= _clock(db),
            columns.operation_kind.not_in(BATCH_KINDS),
        ),
    )
    conditions = [*_scope(owner), available, columns.status.in_(allowed_statuses)]
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
        raise EtlConflict("ETL_RUN_BUSY", "本次运行已有活动任务或结果尚待核对，请稍后查看处理状态")
    return owner


def activate_operation(db: Session, run: EtlRun, kind: str, token: str) -> OperationOwner:
    owner = OperationOwner(run.id, run.owner_user_id, tenant_id_for_write(), kind, token)
    queued_kind = "execute_queue" if kind in {"execute", "batch_execute"} else "preview_queue"
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            _RUN_TABLE.c.operation_token == token,
            _RUN_TABLE.c.operation_kind == queued_kind,
            _RUN_TABLE.c.operation_lease_until > _clock(db),
        )
        .values(operation_kind=kind, operation_lease_until=_expiry(db)),
    )
    if result.rowcount != 1:
        raise EtlConflict(
            "ETL_OPERATION_LEASE_LOST", "任务已被其他 worker 领取或执行权已失效，已停止重复执行"
        )
    return owner


def bind_owner(db: Session, owner: OperationOwner) -> None:
    db.info[_SESSION_KEY] = owner


def unbind_owner(db: Session) -> None:
    db.info.pop(_SESSION_KEY, None)


def fence_operation(db: Session, owner: OperationOwner) -> None:
    if tenant_id_for_write() != owner.tenant_id:
        raise EtlConflict("ETL_OPERATION_LEASE_LOST", "任务租户上下文已改变，已停止写入")
    columns = EtlRun.__table__.c
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(
            *_scope(owner),
            columns.operation_kind == owner.kind,
            columns.operation_token == owner.token,
            columns.operation_lease_until > _clock(db),
        )
        .values(operation_lease_until=_expiry(db)),
    )
    if result.rowcount != 1:
        raise EtlConflict(
            "ETL_OPERATION_LEASE_LOST", "任务执行权已失效，已停止写入，请刷新运行状态"
        )


def finish_operation(db: Session, owner: OperationOwner) -> None:
    db.flush()
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(*_scope(owner), EtlRun.__table__.c.operation_token == owner.token)
        .values(operation_kind=None, operation_token=None, operation_lease_until=None),
    )
    if result.rowcount != 1:
        raise EtlConflict("ETL_OPERATION_LEASE_LOST", "任务执行权已转移，不能覆盖当前运行结果")
    unbind_owner(db)


def fail_operation(
    db: Session,
    owner: OperationOwner,
    *,
    code: str,
    message: str,
    outcome_unknown: bool = False,
) -> bool:
    """A stale worker may never overwrite a replacement owner's status or token."""
    db.rollback()
    unbind_owner(db)
    values: dict[str, Any] = {
        "error_code": "ETL_OUTCOME_UNKNOWN" if outcome_unknown else code,
        "error_message": (
            "外部批处理结果无法确认，已停止自动重试，请核对实际结果后人工处理"
            if outcome_unknown
            else message[:500]
        ),
    }
    if owner.kind in {"rollback", "batch_rollback"}:
        values["rollback_status"] = "outcome_unknown" if outcome_unknown else "failed"
    if outcome_unknown or owner.kind not in {"rollback", "batch_rollback"}:
        values["status"] = values["stage"] = "outcome_unknown" if outcome_unknown else "failed"
    if not outcome_unknown:
        values.update(operation_kind=None, operation_token=None, operation_lease_until=None)
    result = _dml(
        db,
        update(_RUN_TABLE)
        .where(*_scope(owner), EtlRun.__table__.c.operation_token == owner.token)
        .values(**values),
    )
    db.commit()
    return bool(result.rowcount == 1)


def has_active_owner(run: EtlRun) -> bool:
    deadline = run.operation_lease_until
    if not run.operation_token or deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return deadline > datetime.now(UTC)


def recover_stale_owner(db: Session, run: EtlRun) -> bool:
    if (
        not run.operation_token
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
        "error_code": "ETL_OUTCOME_UNKNOWN" if unknown else "ETL_EXECUTION_INTERRUPTED",
        "error_message": "外部批处理结果无法确认，请核对实际结果后人工处理"
        if unknown
        else "任务执行权已过期，可刷新后重试未完成的步骤",
    }
    if owner.kind in {"rollback", "batch_rollback"}:
        values["rollback_status"] = "outcome_unknown" if unknown else "failed"
    if unknown or owner.kind != "rollback":
        values["status"] = values["stage"] = "outcome_unknown" if unknown else "interrupted"
    if not unknown:
        values.update(operation_kind=None, operation_token=None, operation_lease_until=None)
    columns = EtlRun.__table__.c
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
        db.commit()
        db.refresh(run)
        return True
    return False


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
