"""Adaptive per-model concurrency for billed model calls.

Vendors do not publish a stable concurrency ceiling, and an upstream ``429`` lands
in the journal as an unresolved attempt that still holds wallet money. This module
keeps one shared limit per upstream model in the database, so every worker obeys
the same number:

* acquire a short lease before dispatch, release it when the attempt ends;
* a vendor ``429`` halves the limit and starts a cooldown;
* a run of successes grows the limit back, never past its measured maximum.

A missing table or a database error fails open: a schema rollout must never take
the chat path down.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from modstore_server.db.llm_chat import LlmModelConcurrency, LlmModelLease

logger = logging.getLogger(__name__)

SUCCESS_STREAK_TO_GROW = 20
LEASE_GRACE_S = 120
_DEFAULT_LIMIT = 4
_DEFAULT_MAX_LIMIT = 8
_DEFAULT_COOLDOWN_S = 2.0
_MAX_COOLDOWN_S = 60.0


@dataclass(frozen=True)
class Lease:
    """A held admission slot; ``enforced`` is false when the guard failed open."""

    key: str
    lease_id: str
    enforced: bool


def concurrency_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def retry_after_seconds(error: BaseException, default: float = _DEFAULT_COOLDOWN_S) -> float:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    raw = headers.get("retry-after") if headers is not None else None
    try:
        seconds = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        seconds = default
    return min(_MAX_COOLDOWN_S, max(1.0, seconds))


def is_throttled(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 429


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


class ConcurrencyController:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        default_limit: int = _DEFAULT_LIMIT,
        default_max_limit: int = _DEFAULT_MAX_LIMIT,
        poll_s: float = 0.15,
    ) -> None:
        self.enabled = _env_flag("MODSTORE_MODEL_CONCURRENCY", True) if enabled is None else enabled
        self.default_limit = default_limit
        self.default_max_limit = max(default_max_limit, default_limit)
        self.poll_s = poll_s
        self._disabled = Lease("", "", False)
        self._skip_until = 0.0

    async def acquire(
        self, db: Session, key: str, *, wait_s: float, timeout_s: float
    ) -> Lease | None:
        """Take one slot, waiting at most ``wait_s``; ``None`` means saturated."""
        if not self.enabled or time.monotonic() < self._skip_until:
            return self._disabled
        deadline = datetime.now(UTC) + timedelta(seconds=max(0.0, wait_s))
        while True:
            try:
                lease_id = self._acquire_once(db, key, timeout_s)
            except SQLAlchemyError as exc:
                db.rollback()
                self._skip_until = time.monotonic() + 60
                logger.warning("model concurrency guard failed open key=%s error=%s", key, exc)
                return self._disabled
            if lease_id is not None:
                return Lease(key, lease_id, True)
            if datetime.now(UTC) >= deadline:
                return None
            await asyncio.sleep(self.poll_s)

    def release(self, db: Session, lease: Lease) -> None:
        if not lease.enforced:
            return
        try:
            deleted = (
                db.query(LlmModelLease)
                .filter(LlmModelLease.lease_id == lease.lease_id)
                .delete(synchronize_session=False)
            )
            db.commit()
            if not deleted:
                logger.info("model concurrency lease already gone key=%s", lease.key)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.warning("model concurrency release failed key=%s error=%s", lease.key, exc)

    def report_throttled(
        self, db: Session, key: str, retry_after: float = _DEFAULT_COOLDOWN_S
    ) -> None:
        if not self.enabled:
            return
        try:
            row = self._locked_row(db, key)
            previous = int(row.limit_value)
            row.limit_value = max(int(row.min_limit), previous // 2)
            row.success_streak = 0
            row.cooldown_until = datetime.now(UTC) + timedelta(seconds=retry_after)
            row.updated_at = datetime.now(UTC)
            db.commit()
            if row.limit_value != previous:
                logger.warning(
                    "model concurrency throttled key=%s limit %s -> %s cooldown=%ss",
                    key,
                    previous,
                    row.limit_value,
                    retry_after,
                )
        except SQLAlchemyError as exc:
            db.rollback()
            logger.warning("model concurrency throttle record failed key=%s error=%s", key, exc)

    def report_success(self, db: Session, key: str) -> None:
        if not self.enabled:
            return
        try:
            row = self._locked_row(db, key)
            now = datetime.now(UTC)
            cooling = row.cooldown_until is not None and _aware(row.cooldown_until) > now
            streak = int(row.success_streak or 0) + 1
            if cooling or streak < SUCCESS_STREAK_TO_GROW:
                row.success_streak = streak
            else:
                previous = int(row.limit_value)
                row.limit_value = min(int(row.max_limit), previous + 1)
                row.success_streak = 0
                if row.limit_value != previous:
                    logger.info(
                        "model concurrency recovered key=%s limit %s -> %s",
                        key,
                        previous,
                        row.limit_value,
                    )
            row.updated_at = now
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            logger.warning("model concurrency success record failed key=%s error=%s", key, exc)

    def current_limit(self, db: Session, key: str) -> int | None:
        row = db.query(LlmModelConcurrency).filter_by(model_key=key).one_or_none()
        return None if row is None else int(row.limit_value)

    def inflight(self, db: Session, key: str) -> int:
        now = datetime.now(UTC)
        return (
            db.query(LlmModelLease)
            .filter(LlmModelLease.model_key == key, LlmModelLease.expires_at > now)
            .count()
        )

    def seed(self, db: Session, key: str, limit: int) -> None:
        """Create or set the measured ceiling for one model (migration/testing)."""
        limit = max(1, limit)
        row = db.query(LlmModelConcurrency).filter_by(model_key=key).one_or_none()
        if row is None:
            db.add(
                LlmModelConcurrency(
                    model_key=key,
                    limit_value=limit,
                    min_limit=1,
                    max_limit=limit,
                )
            )
        else:
            row.limit_value = limit
            row.max_limit = limit
        db.commit()

    def _locked_row(self, db: Session, key: str) -> LlmModelConcurrency:
        row = db.query(LlmModelConcurrency).filter_by(model_key=key).with_for_update().one_or_none()
        if row is not None:
            return row
        db.add(
            LlmModelConcurrency(
                model_key=key,
                limit_value=self.default_limit,
                min_limit=1,
                max_limit=self.default_max_limit,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        row = db.query(LlmModelConcurrency).filter_by(model_key=key).with_for_update().one_or_none()
        if row is None:
            raise SQLAlchemyError(f"concurrency row missing for {key}")
        return row

    def _acquire_once(self, db: Session, key: str, timeout_s: float) -> str | None:
        now = datetime.now(UTC)
        row = self._locked_row(db, key)
        (
            db.query(LlmModelLease)
            .filter(LlmModelLease.model_key == key, LlmModelLease.expires_at <= now)
            .delete(synchronize_session=False)
        )
        inflight = db.query(LlmModelLease).filter(LlmModelLease.model_key == key).count()
        cooling = row.cooldown_until is not None and _aware(row.cooldown_until) > now
        if cooling or inflight >= int(row.limit_value):
            db.commit()
            return None
        lease_id = uuid4().hex
        db.add(
            LlmModelLease(
                lease_id=lease_id,
                model_key=key,
                acquired_at=now,
                expires_at=now + timedelta(seconds=max(timeout_s, 0.0) + LEASE_GRACE_S),
            )
        )
        db.commit()
        return lease_id


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


controller = ConcurrencyController()

__all__ = [
    "ConcurrencyController",
    "Lease",
    "concurrency_key",
    "controller",
    "is_throttled",
    "retry_after_seconds",
]
