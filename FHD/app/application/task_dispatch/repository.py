"""工单仓储（SQLAlchemy）。

沿用 ``SQLAlchemyAgentRunRepository`` 的模式：可注入 session_factory（测试用
内存 SQLite），``_ensure_schema`` 懒建本表（兼容 ``FHD_SKIP_ALEMBIC`` 的桌面库）。
读写均返回 ``dict``（``WorkOrder.to_dict()``），避免 session 关闭后的 DetachedInstance。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkOrderRepository:
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

    # ── CRUD ────────────────────────────────────────────────────────────
    def create(self, **fields: Any) -> dict[str, Any]:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.work_order import WorkOrder

            record = WorkOrder(**fields)
            db.add(record)
            db.flush()
            return record.to_dict()

    def get(self, work_order_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.work_order import WorkOrder

            record = db.get(WorkOrder, str(work_order_id or ""))
            return record.to_dict() if record is not None else None

    def update(self, work_order_id: str, **changes: Any) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_scope() as db:
            from app.db.models.work_order import WorkOrder

            record = db.get(WorkOrder, str(work_order_id or ""))
            if record is None:
                return None
            for key, value in changes.items():
                setattr(record, key, value)
            db.flush()
            return record.to_dict()

    def list_recent(
        self, *, requester_user_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.work_order import WorkOrder

            query = db.query(WorkOrder)
            if requester_user_id is not None:
                query = query.filter(WorkOrder.requester_user_id == str(requester_user_id))
            records = query.order_by(WorkOrder.created_at.desc()).limit(max(0, int(limit))).all()
            return [record.to_dict() for record in records]

    def list_pending(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """待执行工单（pending/dispatched，FIFO）；供 worker 抽干、重启恢复。"""
        from app.application.task_dispatch.status import WorkOrderStatus

        self._ensure_schema()
        with self._session_scope(read_only=True) as db:
            from app.db.models.work_order import WorkOrder

            records = (
                db.query(WorkOrder)
                .filter(
                    WorkOrder.status.in_(
                        [WorkOrderStatus.PENDING.value, WorkOrderStatus.DISPATCHED.value]
                    )
                )
                .order_by(WorkOrder.created_at.asc())
                .limit(max(0, int(limit)))
                .all()
            )
            return [record.to_dict() for record in records]

    # ── infra ───────────────────────────────────────────────────────────
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
                from app.db.models.work_order import WorkOrder

                Base.metadata.create_all(
                    bind=db.get_bind(),
                    tables=[WorkOrder.__table__],
                    checkfirst=True,
                )
            self._schema_ready = True


_work_order_repository: WorkOrderRepository | None = None


def get_work_order_repository() -> WorkOrderRepository:
    global _work_order_repository
    if _work_order_repository is None:
        _work_order_repository = WorkOrderRepository()
    return _work_order_repository
