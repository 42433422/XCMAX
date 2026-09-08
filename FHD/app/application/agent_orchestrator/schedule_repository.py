"""SQL-only recurring schedule store. Never fall back to process memory."""

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from sqlalchemy import Table, or_
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.task_execution_models import _deadline
from app.db.models.agent_schedule import AgentScheduleRecord as Record


class ScheduleRepository:
    def __init__(self, session_factory: Callable[[], Session] | None = None):
        self._factory = session_factory
        self._bind: object | None = None
        self._lock = threading.RLock()

    @contextmanager
    def session(self) -> Iterator[Session]:
        from app.db import HostSessionLocal

        db = (self._factory or HostSessionLocal)()
        try:
            with self._lock:
                bind = db.get_bind()
                if bind is not self._bind:
                    from app.db.models.schedule_authorization import (
                        ScheduleAuthorizationRecord,
                        ScheduleAuthorizationUseRecord,
                    )

                    cast(Table, Record.__table__).create(bind, checkfirst=True)
                    cast(Table, ScheduleAuthorizationRecord.__table__).create(bind, checkfirst=True)
                    cast(Table, ScheduleAuthorizationUseRecord.__table__).create(
                        bind, checkfirst=True
                    )
                    self._bind = bind
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _data(row: Record) -> dict[str, Any]:
        return {
            "schedule_id": row.schedule_id,
            "user_id": row.user_id,
            "tenant_id": row.tenant_id,
            "state": row.state,
            "next_run_at": row.next_run_at,
            "last_task_id": row.last_task_id,
            "last_error": row.last_error,
            "payload": json.loads(row.payload_json),
            "lease_owner": row.lease_owner,
        }

    def create(
        self, *, user_id: str, tenant_id: str, request_id: str, payload: dict[str, Any], due: str
    ) -> dict[str, Any]:
        if not user_id or not tenant_id or not request_id or len(request_id) > 160:
            raise ValueError("周期任务需要账号、租户与稳定请求 ID")
        key = hashlib.sha256(json.dumps([tenant_id, user_id, request_id]).encode()).hexdigest()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(f"{encoded}:{due}".encode()).hexdigest()
        with self.session() as db:
            row = db.get(Record, key)
            if row is not None:
                if row.fingerprint != fingerprint:
                    raise ValueError("请求 ID 已绑定到不同周期任务")
                return {**self._data(row), "deduplicated": True}
            now = utc_now_iso()
            row = Record(
                schedule_id=key,
                user_id=user_id,
                tenant_id=tenant_id,
                state="active",
                payload_json=encoded,
                fingerprint=fingerprint,
                next_run_at=due,
                created_at=now,
                updated_at=now,
                lease_owner="",
                lease_expires_at="",
                last_task_id="",
                last_error="",
            )
            db.add(row)
            db.flush()
            return {**self._data(row), "deduplicated": False}

    def list_owned(self, user_id: str, tenant_id: str) -> list[dict[str, Any]]:
        with self.session() as db:
            rows = (
                db.query(Record)
                .filter_by(user_id=user_id, tenant_id=tenant_id)
                .order_by(Record.created_at.desc())
                .limit(200)
                .all()
            )
            return [self._data(row) for row in rows]

    def get_owned(self, schedule_id: str, user_id: str, tenant_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = (
                db.query(Record)
                .filter_by(schedule_id=schedule_id, user_id=user_id, tenant_id=tenant_id)
                .one_or_none()
            )
            return self._data(row) if row else None

    def control(self, schedule_id: str, user_id: str, tenant_id: str, action: str) -> bool:
        states = {"pause": "paused", "resume": "active", "cancel": "cancelled"}
        if action not in states:
            raise ValueError("无效调度控制")
        with self.session() as db:
            count = (
                db.query(Record)
                .filter(
                    Record.schedule_id == schedule_id,
                    Record.user_id == user_id,
                    Record.tenant_id == tenant_id,
                    Record.state != "cancelled",
                )
                .update(
                    {"state": states[action], "updated_at": utc_now_iso()},
                    synchronize_session=False,
                )
            )
            return count == 1

    def claim(self, owner: str, *, now: str, lease_seconds: float = 60) -> dict[str, Any] | None:
        with self.session() as db:
            eligible = (
                Record.state == "active",
                Record.next_run_at <= now,
                or_(Record.lease_owner == "", Record.lease_expires_at <= now),
            )
            rows = db.query(Record).filter(*eligible).order_by(Record.next_run_at).limit(8).all()
            for row in rows:
                changed = (
                    db.query(Record)
                    .filter(Record.schedule_id == row.schedule_id, *eligible)
                    .update(
                        {"lease_owner": owner, "lease_expires_at": _deadline(now, lease_seconds)},
                        synchronize_session=False,
                    )
                )
                if changed == 1:
                    db.refresh(row)
                    return self._data(row)
        return None

    def finish(
        self, schedule_id: str, owner: str, *, next_run_at: str, task_id: str = "", error: str = ""
    ) -> bool:
        with self.session() as db:
            values: dict[Any, Any] = {
                "lease_owner": "",
                "lease_expires_at": "",
                "last_error": error,
                "updated_at": utc_now_iso(),
            }
            if not error:
                values.update(next_run_at=next_run_at, last_task_id=task_id)
            else:
                # Avoid flooding retries; resume is explicit and retains the same occurrence ID.
                db.query(Record).filter_by(
                    schedule_id=schedule_id,
                    lease_owner=owner,
                    state="active",
                ).update({"state": "paused"}, synchronize_session=False)
            return (
                db.query(Record)
                .filter_by(schedule_id=schedule_id, lease_owner=owner)
                .update(values, synchronize_session=False)
                == 1
            )
