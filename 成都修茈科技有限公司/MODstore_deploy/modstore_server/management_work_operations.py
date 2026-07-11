"""Idempotency and compensation ledger for management-employee side effects."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import uuid
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from modstore_server.models import (
    ManagementWorkEvent,
    ManagementWorkItem,
    ManagementWorkOperation,
    _add_column_if_missing,
    get_engine,
    get_session_factory,
)
from modstore_server.security_boundary import resolve_path_under_root


class ManagementOperationConflict(RuntimeError):
    pass


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY_ENGINES: weakref.WeakSet[Any] = weakref.WeakSet()


def _ensure_operation_schema() -> None:
    """Backfill the lease-binding column for databases created before v2."""

    engine = get_engine()
    if engine in _SCHEMA_READY_ENGINES:
        return
    with _SCHEMA_LOCK:
        if engine in _SCHEMA_READY_ENGINES:
            return
        _add_column_if_missing(
            engine,
            "management_work_operations",
            "execution_nonce",
            "VARCHAR(64) NOT NULL DEFAULT ''",
        )
        _SCHEMA_READY_ENGINES.add(engine)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _lease_execution_nonce(task_id: str, lease_token: str) -> str:
    """Derive a non-credential nonce that changes whenever the work lease changes."""

    return hashlib.sha256(
        f"{str(task_id or '').strip()}\0{str(lease_token or '')}".encode("utf-8")
    ).hexdigest()


def _current_execution(
    session: Any,
    *,
    task_id: str,
    employee_id: str,
    expected_attempt: int | None = None,
    expected_nonce: str = "",
    lock: bool = True,
) -> tuple[ManagementWorkItem, int, str]:
    """Return and, when requested, lock the currently authorized execution."""

    query = session.query(ManagementWorkItem).filter(ManagementWorkItem.task_id == str(task_id))
    if lock and session.bind is not None and session.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    work = query.first()
    if work is None:
        raise ManagementOperationConflict("management work item not found")
    if str(work.owner_employee_id or "") != str(employee_id or ""):
        raise ManagementOperationConflict("employee does not own management work item")
    if str(work.status or "") != "running":
        raise ManagementOperationConflict(f"management work item is {work.status}, not running")
    current_attempt = int(work.attempt_count or 0)
    if current_attempt <= 0:
        raise ManagementOperationConflict("management work item has no active attempt")
    if expected_attempt is not None and int(expected_attempt) != current_attempt:
        raise ManagementOperationConflict(
            f"management work attempt changed from {int(expected_attempt)} to {current_attempt}"
        )
    lease_token = str(work.lease_token or "")
    if not lease_token:
        raise ManagementOperationConflict("management work lease is missing")
    lease_expires_at = _as_utc(work.lease_expires_at)
    if lease_expires_at is not None and lease_expires_at <= _now():
        raise ManagementOperationConflict("management work lease has expired")
    current_nonce = _lease_execution_nonce(str(work.task_id), lease_token)
    if expected_nonce and not hmac.compare_digest(str(expected_nonce), current_nonce):
        raise ManagementOperationConflict("management work execution nonce changed")

    if lock:
        # PostgreSQL already holds a row lock via FOR UPDATE.  SQLite ignores
        # FOR UPDATE, so a conditional no-op UPDATE establishes the same
        # cancellation barrier before an operation row is inserted/changed.
        matched = (
            session.query(ManagementWorkItem)
            .filter(
                ManagementWorkItem.id == int(work.id),
                ManagementWorkItem.status == "running",
                ManagementWorkItem.owner_employee_id == str(employee_id),
                ManagementWorkItem.attempt_count == current_attempt,
                ManagementWorkItem.lease_token == lease_token,
            )
            .update(
                {ManagementWorkItem.status: ManagementWorkItem.status},
                synchronize_session=False,
            )
        )
        if matched != 1:
            raise ManagementOperationConflict(
                "management work execution changed while reserving operation"
            )
        session.flush()
    return work, current_attempt, current_nonce


def _validate_operation_caller(
    row: ManagementWorkOperation,
    *,
    execution_attempt: int,
    execution_nonce: str,
) -> None:
    if int(row.attempt or 0) != int(execution_attempt):
        raise ManagementOperationConflict("operation execution attempt changed")
    if not execution_nonce or not hmac.compare_digest(
        str(row.execution_nonce or ""), str(execution_nonce)
    ):
        raise ManagementOperationConflict("operation execution nonce changed")


def _dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def request_digest(value: Any) -> str:
    return hashlib.sha256(_dumps(value).encode("utf-8")).hexdigest()


def build_operation_key(
    *,
    task_id: str,
    task_revision: int,
    logical_step: str,
    kind: str,
    target: str,
) -> str:
    canonical = "\0".join(
        [
            str(task_id or "").strip(),
            str(max(1, int(task_revision or 1))),
            str(logical_step or "").strip().lower(),
            str(kind or "").strip().lower(),
            str(target or "").strip(),
        ]
    )
    return "mop_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize(row: ManagementWorkOperation) -> dict[str, Any]:
    return {
        "operation_id": str(row.operation_id),
        "operation_key": str(row.operation_key),
        "task_id": str(row.task_id),
        "employee_id": str(row.employee_id),
        "task_revision": int(row.task_revision or 1),
        "logical_step": str(row.logical_step or ""),
        "attempt": int(row.attempt or 0),
        "kind": str(row.kind),
        "target": str(row.target or ""),
        "request_digest": str(row.request_digest or ""),
        "status": str(row.status or ""),
        "reversible": bool(row.reversible),
        "external_ref": str(row.external_ref or ""),
        "result": _loads(row.result_json, {}),
        "error": str(row.error or ""),
        "compensation_status": str(row.compensation_status or ""),
        "compensation": _loads(row.compensation_json, {}),
        "lease_expires_at": (row.lease_expires_at.isoformat() if row.lease_expires_at else None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _event(
    session: Any,
    row: ManagementWorkOperation,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        ManagementWorkEvent(
            work_item_id=int(row.work_item_id),
            event_type=str(event_type)[:64],
            actor_type="employee",
            actor_id=str(row.employee_id or "")[:128],
            message=str(message or "")[:8000],
            payload_json=_dumps(
                {
                    "operation_id": row.operation_id,
                    "operation_key": row.operation_key,
                    "kind": row.kind,
                    "target": row.target,
                    **(payload or {}),
                }
            ),
        )
    )


def begin_operation(
    *,
    task_id: str,
    employee_id: str,
    kind: str,
    target: str,
    request: Any,
    logical_step: str,
    task_revision: int = 1,
    reversible: bool = False,
    compensation: dict[str, Any] | None = None,
    safe_retry: bool = False,
    lease_seconds: int = 30,
    execution_attempt: int | None = None,
    execution_nonce: str = "",
) -> dict[str, Any]:
    """Reserve an operation or replay its durable successful result."""

    _ensure_operation_schema()
    digest = request_digest(request)
    key = build_operation_key(
        task_id=task_id,
        task_revision=task_revision,
        logical_step=logical_step,
        kind=kind,
        target=target,
    )
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        work, current_attempt, current_nonce = _current_execution(
            session,
            task_id=task_id,
            employee_id=employee_id,
            expected_attempt=execution_attempt,
            expected_nonce=execution_nonce,
            lock=True,
        )
        existing = (
            session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.operation_key == key)
            .first()
        )
        if existing is not None:
            if str(existing.employee_id or "") != str(employee_id or ""):
                raise ManagementOperationConflict(
                    "operation belongs to a different management-work owner"
                )
            if str(existing.request_digest or "") != digest:
                raise ManagementOperationConflict("operation key request digest mismatch")
            status = str(existing.status or "")
            if status == "succeeded":
                previous_attempt = int(existing.attempt or 0)
                previous_nonce = str(existing.execution_nonce or "")
                existing.attempt = current_attempt
                existing.execution_nonce = current_nonce
                existing.updated_at = now
                _event(
                    session,
                    existing,
                    "operation.replayed",
                    "副作用已成功执行，重试直接复用原结果",
                    {
                        "previous_attempt": previous_attempt,
                        "current_attempt": current_attempt,
                        "execution_nonce_rotated": previous_nonce != current_nonce,
                    },
                )
                session.commit()
                session.refresh(existing)
                return {
                    "action": "replay",
                    "operation": _serialize(existing),
                    "result": _loads(existing.result_json, {}),
                    "execution_attempt": current_attempt,
                    "execution_nonce": current_nonce,
                }
            operation_lease = _as_utc(existing.lease_expires_at)
            lease_live = bool(operation_lease and operation_lease > now)
            if (
                status == "running"
                and not lease_live
                and safe_retry
                and str(existing.kind or "") == "file.write"
            ):
                spec = _loads(existing.compensation_json, {})
                raw_path = str(spec.get("path") or "")
                workspace_root = str(spec.get("workspace_root") or "")
                expected_after = str(spec.get("expected_after_sha256") or "")
                try:
                    path = resolve_path_under_root(
                        workspace_root,
                        raw_path,
                        require_relative=False,
                    )
                except (OSError, ValueError):
                    path = Path()
                    current_exists = False
                else:
                    current_exists = path.is_file()
                current_sha = (
                    _sha256_file(path, workspace_root=workspace_root) if current_exists else ""
                )
                if expected_after and current_sha == expected_after:
                    previous_attempt = int(existing.attempt or 0)
                    existing.status = "succeeded"
                    existing.attempt = current_attempt
                    existing.execution_nonce = current_nonce
                    existing.result_json = _dumps(
                        {
                            "ok": True,
                            "path": str(path),
                            "sha256": current_sha,
                            "reconciled_after_worker_exit": True,
                        }
                    )
                    existing.external_ref = str(path)
                    existing.compensation_status = (
                        "available" if existing.reversible else "not_required"
                    )
                    existing.compensation_json = _dumps({**spec, "after_sha256": current_sha})
                    existing.lease_expires_at = None
                    existing.completed_at = now
                    existing.updated_at = now
                    _event(
                        session,
                        existing,
                        "operation.reconciled",
                        "子进程退出后独立回读文件，确认操作已成功",
                        {
                            "previous_attempt": previous_attempt,
                            "current_attempt": current_attempt,
                        },
                    )
                    session.commit()
                    return {
                        "action": "replay",
                        "operation": _serialize(existing),
                        "result": _loads(existing.result_json, {}),
                        "execution_attempt": current_attempt,
                        "execution_nonce": current_nonce,
                    }
                before_exists = bool(spec.get("before_exists"))
                before_matches = (not before_exists and not current_exists) or (
                    before_exists
                    and current_exists
                    and bool(spec.get("before_sha256"))
                    and current_sha == str(spec.get("before_sha256"))
                )
                if not before_matches:
                    existing.status = "uncertain"
                    existing.error = "文件既不是登记的写入前状态，也不是预期写入后状态"
                    existing.compensation_status = (
                        "required" if existing.reversible else "unavailable"
                    )
                    existing.lease_expires_at = None
                    existing.updated_at = now
                    _event(
                        session,
                        existing,
                        "operation.uncertain",
                        existing.error,
                    )
                    session.commit()
                    return {
                        "action": "blocked",
                        "operation": _serialize(existing),
                        "reason": existing.error,
                    }
            reclaimable = (
                status == "failed"
                and not lease_live
                and not str(existing.external_ref or "")
                and safe_retry
            ) or (
                status == "running"
                and not lease_live
                and safe_retry
                and str(existing.kind or "") == "file.write"
            )
            if reclaimable:
                previous_attempt = int(existing.attempt or 0)
                existing.status = "running"
                existing.attempt = current_attempt
                existing.execution_nonce = current_nonce
                existing.error = ""
                if status == "failed":
                    # A known-no-effect failure may retry from the *current*
                    # preimage, not the stale preimage captured by the failed
                    # execution.
                    existing.reversible = bool(reversible)
                    existing.compensation_status = "available" if reversible else "not_required"
                    existing.compensation_json = _dumps(compensation or {})[:500_000]
                existing.lease_expires_at = now + timedelta(
                    seconds=max(5, min(int(lease_seconds or 30), 300))
                )
                existing.updated_at = now
                _event(
                    session,
                    existing,
                    "operation.reclaimed",
                    "回收上次未确认的本地操作租约并重新核验",
                    {
                        "previous_attempt": previous_attempt,
                        "current_attempt": current_attempt,
                    },
                )
                session.commit()
                session.refresh(existing)
                return {
                    "action": "execute",
                    "operation": _serialize(existing),
                    "execution_attempt": current_attempt,
                    "execution_nonce": current_nonce,
                }
            if status == "running" and not lease_live:
                existing.status = "uncertain"
                existing.error = "操作租约已过期，且无法独立证明请求未执行"
                existing.compensation_status = "required" if existing.reversible else "unavailable"
                existing.lease_expires_at = None
                existing.updated_at = now
                _event(
                    session,
                    existing,
                    "operation.uncertain",
                    existing.error,
                )
                session.commit()
                session.refresh(existing)
            return {
                "action": "blocked",
                "operation": _serialize(existing),
                "reason": (
                    "operation is still running"
                    if lease_live
                    else "operation outcome is uncertain or requires compensation"
                ),
            }

        row = ManagementWorkOperation(
            operation_id=f"mop_{uuid.uuid4().hex}",
            operation_key=key,
            work_item_id=int(work.id),
            task_id=str(task_id)[:64],
            employee_id=str(employee_id)[:128],
            task_revision=max(1, int(task_revision or 1)),
            logical_step=str(logical_step or "unspecified")[:128],
            attempt=current_attempt,
            execution_nonce=current_nonce,
            kind=str(kind or "unknown")[:64],
            target=str(target or "")[:512],
            request_digest=digest,
            status="running",
            reversible=bool(reversible),
            compensation_status="available" if reversible else "not_required",
            compensation_json=_dumps(compensation or {})[:500_000],
            lease_expires_at=now + timedelta(seconds=max(5, min(int(lease_seconds or 30), 300))),
            updated_at=now,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            winner = (
                session.query(ManagementWorkOperation)
                .filter(ManagementWorkOperation.operation_key == key)
                .one()
            )
            return {
                "action": "replay" if winner.status == "succeeded" else "blocked",
                "operation": _serialize(winner),
                "result": _loads(winner.result_json, {}),
                "reason": "operation was concurrently reserved",
            }
        _event(session, row, "operation.started", "已登记幂等副作用操作")
        session.commit()
        session.refresh(row)
        return {
            "action": "execute",
            "operation": _serialize(row),
            "execution_attempt": current_attempt,
            "execution_nonce": current_nonce,
        }


def _locked_current_operation(
    session: Any,
    operation_id: str,
    *,
    execution_attempt: int,
    execution_nonce: str,
) -> ManagementWorkOperation:
    initial = (
        session.query(ManagementWorkOperation)
        .filter(ManagementWorkOperation.operation_id == str(operation_id))
        .one()
    )
    _current_execution(
        session,
        task_id=str(initial.task_id),
        employee_id=str(initial.employee_id),
        expected_attempt=int(execution_attempt),
        expected_nonce=str(execution_nonce),
        lock=True,
    )
    query = session.query(ManagementWorkOperation).filter(
        ManagementWorkOperation.operation_id == str(operation_id)
    )
    if session.bind is not None and session.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    row = query.one()
    _validate_operation_caller(
        row,
        execution_attempt=int(execution_attempt),
        execution_nonce=str(execution_nonce),
    )
    return row


def assert_operation_execution_current(
    operation_id: str,
    *,
    execution_attempt: int,
    execution_nonce: str,
) -> dict[str, Any]:
    """Fail closed unless the operation still belongs to the active work lease."""

    _ensure_operation_schema()
    sf = get_session_factory()
    with sf() as session:
        row = lock_operation_execution_for_update(
            session,
            operation_id,
            execution_attempt=execution_attempt,
            execution_nonce=execution_nonce,
        )
        session.commit()
        return _serialize(row)


def lock_operation_execution_for_update(
    session: Any,
    operation_id: str,
    *,
    execution_attempt: int,
    execution_nonce: str,
) -> ManagementWorkOperation:
    """Lock an operation and its current work lease inside the caller transaction."""

    _ensure_operation_schema()
    row = _locked_current_operation(
        session,
        operation_id,
        execution_attempt=execution_attempt,
        execution_nonce=execution_nonce,
    )
    if str(row.status or "") != "running":
        raise ManagementOperationConflict(f"operation is {row.status}, not running")
    return row


def complete_operation(
    operation_id: str,
    *,
    execution_attempt: int,
    execution_nonce: str,
    result: dict[str, Any],
    external_ref: str = "",
    compensation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_operation_schema()
    now = _now()
    sf = get_session_factory()
    with sf() as session:
        row = _locked_current_operation(
            session,
            operation_id,
            execution_attempt=execution_attempt,
            execution_nonce=execution_nonce,
        )
        if row.status == "succeeded":
            return _serialize(row)
        if row.status != "running":
            raise ManagementOperationConflict(f"operation is {row.status}, not running")
        row.status = "succeeded"
        row.result_json = _dumps(result or {})[:500_000]
        row.external_ref = str(external_ref or "")[:256]
        row.compensation_json = _dumps(compensation or {})[:500_000]
        row.compensation_status = "available" if row.reversible else "not_required"
        row.error = ""
        row.lease_expires_at = None
        row.completed_at = now
        row.updated_at = now
        _event(
            session,
            row,
            "operation.succeeded",
            "副作用操作完成并写入幂等回执",
            {"external_ref": row.external_ref},
        )
        session.commit()
        session.refresh(row)
        return _serialize(row)


def fail_operation(
    operation_id: str,
    *,
    execution_attempt: int,
    execution_nonce: str,
    error: str,
    outcome_known_no_effect: bool,
) -> dict[str, Any]:
    _ensure_operation_schema()
    sf = get_session_factory()
    with sf() as session:
        row = _locked_current_operation(
            session,
            operation_id,
            execution_attempt=execution_attempt,
            execution_nonce=execution_nonce,
        )
        if row.status != "running":
            raise ManagementOperationConflict(f"operation is {row.status}, not running")
        row.status = "failed" if outcome_known_no_effect else "uncertain"
        row.error = str(error or "")[:8000]
        row.lease_expires_at = None
        row.compensation_status = (
            "not_required"
            if outcome_known_no_effect
            else ("required" if row.reversible else "unavailable")
        )
        row.updated_at = _now()
        _event(
            session,
            row,
            "operation.failed" if outcome_known_no_effect else "operation.uncertain",
            row.error or "副作用操作未完成",
        )
        session.commit()
        session.refresh(row)
        return _serialize(row)


def operation_by_key(operation_key: str) -> dict[str, Any] | None:
    _ensure_operation_schema()
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.operation_key == str(operation_key))
            .first()
        )
        return _serialize(row) if row is not None else None


def list_task_operations(task_id: str) -> list[dict[str, Any]]:
    _ensure_operation_schema()
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(ManagementWorkOperation)
            .filter(ManagementWorkOperation.task_id == str(task_id))
            .order_by(ManagementWorkOperation.id.asc())
            .all()
        )
        return [_serialize(row) for row in rows]


def _sha256_file(path: Path, *, workspace_root: str | Path) -> str:
    resolved = resolve_path_under_root(workspace_root, path, require_relative=False)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_file_compensation(
    path: Path,
    *,
    workspace_root: str | Path,
    max_bytes: int = 256_000,
) -> dict[str, Any]:
    """Capture a bounded preimage for safe compare-and-restore compensation."""

    root = resolve_path_under_root(workspace_root, ".", reject_symlinks=False)
    resolved = resolve_path_under_root(root, path, require_relative=False)
    if not resolved.exists():
        return {
            "kind": "file_restore",
            "path": str(resolved),
            "workspace_root": str(root),
            "before_exists": False,
            "reversible": True,
        }
    if not resolved.is_file():
        return {
            "kind": "file_restore",
            "path": str(resolved),
            "workspace_root": str(root),
            "before_exists": True,
            "reversible": False,
            "reason": "target is not a regular file",
        }
    size = resolved.stat().st_size
    payload: dict[str, Any] = {
        "kind": "file_restore",
        "path": str(resolved),
        "workspace_root": str(root),
        "before_exists": True,
        "before_size": int(size),
        "before_sha256": _sha256_file(resolved, workspace_root=root),
    }
    if size <= max(0, int(max_bytes)):
        payload["before_content_b64"] = base64.b64encode(resolved.read_bytes()).decode("ascii")
        payload["reversible"] = True
    else:
        payload["reversible"] = False
        payload["reason"] = "preimage exceeds compensation limit"
    return payload


def compensate_task_file_operations(task_id: str, *, reason: str) -> dict[str, Any]:
    """Safely restore completed file writes whose postimage is still unchanged."""

    _ensure_operation_schema()
    restored = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(ManagementWorkOperation)
            .filter(
                ManagementWorkOperation.task_id == str(task_id),
                ManagementWorkOperation.kind == "file.write",
                ManagementWorkOperation.status == "succeeded",
                ManagementWorkOperation.reversible.is_(True),
                ManagementWorkOperation.compensation_status.in_(["available", "required"]),
            )
            .order_by(ManagementWorkOperation.id.desc())
            .all()
        )
        for row in rows:
            spec = _loads(row.compensation_json, {})
            raw_path = str(spec.get("path") or "")
            workspace_root = str(spec.get("workspace_root") or "")
            after_sha = str(spec.get("after_sha256") or "")
            try:
                if not raw_path or not workspace_root or not after_sha:
                    raise ValueError("compensation record is incomplete")
                path = resolve_path_under_root(
                    workspace_root,
                    raw_path,
                    require_relative=False,
                )
                if (
                    not path.is_file()
                    or _sha256_file(
                        path,
                        workspace_root=workspace_root,
                    )
                    != after_sha
                ):
                    row.compensation_status = "conflict"
                    row.error = "文件已被后续操作修改，拒绝自动回滚"
                    skipped += 1
                    continue
                if spec.get("before_exists") is False:
                    path.unlink()
                elif spec.get("before_content_b64"):
                    before = base64.b64decode(str(spec["before_content_b64"]))
                    temporary = path.with_name(f".{path.name}.xcagi-rollback-{uuid.uuid4().hex}")
                    temporary.write_bytes(before)
                    os.replace(temporary, path)
                else:
                    raise ValueError("bounded preimage is unavailable")
                row.compensation_status = "compensated"
                row.compensation_json = _dumps({**spec, "reason": reason[:1000]})
                row.updated_at = _now()
                _event(
                    session,
                    row,
                    "operation.compensated",
                    "任务取消后已安全恢复文件写入",
                    {"reason": reason[:1000]},
                )
                restored += 1
            except Exception as exc:  # noqa: BLE001 - retain per-operation truth
                row.compensation_status = "failed"
                row.error = str(exc)[:8000]
                errors.append({"operation_id": str(row.operation_id), "error": str(exc)[:500]})
        session.commit()
    unresolved: list[dict[str, str]] = []
    for operation in list_task_operations(task_id):
        status = str(operation.get("status") or "")
        compensation_status = str(operation.get("compensation_status") or "")
        if status in {"running", "uncertain"} or compensation_status in {
            "required",
            "failed",
            "conflict",
            "unavailable",
        }:
            unresolved.append(
                {
                    "operation_id": str(operation.get("operation_id") or ""),
                    "kind": str(operation.get("kind") or ""),
                    "status": status,
                    "compensation_status": compensation_status,
                }
            )
        elif status == "succeeded" and not bool(operation.get("reversible")):
            unresolved.append(
                {
                    "operation_id": str(operation.get("operation_id") or ""),
                    "kind": str(operation.get("kind") or ""),
                    "status": status,
                    "compensation_status": "unavailable",
                }
            )
    return {
        "ok": not errors and skipped == 0 and not unresolved,
        "task_id": str(task_id),
        "restored": restored,
        "skipped": skipped,
        "errors": errors,
        "unresolved": unresolved,
    }


__all__ = [
    "ManagementOperationConflict",
    "assert_operation_execution_current",
    "begin_operation",
    "build_operation_key",
    "capture_file_compensation",
    "complete_operation",
    "compensate_task_file_operations",
    "fail_operation",
    "lock_operation_execution_for_update",
    "list_task_operations",
    "operation_by_key",
    "request_digest",
]
