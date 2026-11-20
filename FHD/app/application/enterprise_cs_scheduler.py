"""Resume enterprise CS turns from the existing IM message log."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db import HostSessionLocal, get_host_engine
from app.db.models.im import ImCustomerServiceAutomationState as CsState
from app.db.models.im import ImMessage
from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)
_CS_LOCK_NAMESPACE = 28414672
_turn_locks = [asyncio.Lock() for _ in range(4)]
_SCAN_GRACE = timedelta(seconds=20)


@contextmanager
def _turn_session(conversation_id: int):
    engine = get_host_engine()
    if engine.dialect.name != "postgresql":
        with HostSessionLocal() as db:
            yield db
        return
    # A session-level lock survives commit and is released if the worker dies.
    with engine.connect() as connection:
        keys = {"namespace": _CS_LOCK_NAMESPACE, "conversation": conversation_id}
        claimed = connection.scalar(
            text("SELECT pg_try_advisory_lock(:namespace, :conversation)"), keys
        )
        connection.commit()
        try:
            if not claimed:
                yield None
            else:
                with Session(bind=connection, autoflush=False) as db:
                    yield db
        finally:
            if claimed and not connection.invalidated:
                connection.rollback()
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :conversation)"), keys
                )
                connection.commit()


async def process_enterprise_cs_customer_message(
    conversation_id: int,
    customer_user_id: int,
    message_id: int,
    body: str,
    *,
    market_token: str = "",
):
    from app.application.enterprise_cs_automation import (
        RETRY_DELAY_SECONDS,
        EnterpriseCsAutomationService,
    )

    async with _turn_locks[conversation_id % len(_turn_locks)]:
        with _turn_session(conversation_id) as db:
            if db is None:
                return {"handled": False, "reason": "busy"}
            row = db.get(CsState, conversation_id)
            watermark = row.last_customer_message_id if row else 0
            if message_id > watermark:
                oldest = db.scalar(
                    select(func.min(ImMessage.id)).where(
                        ImMessage.conversation_id == conversation_id,
                        ImMessage.origin == "customer",
                        ImMessage.id > watermark,
                    )
                )
                if oldest is not None and oldest != message_id:
                    return {"handled": False, "reason": "earlier_message_pending"}
                if (
                    row
                    and row.status == "ai_retrying"
                    and (row.updated_at > utc_now_naive() - timedelta(seconds=RETRY_DELAY_SECONDS))
                ):
                    return {"handled": False, "reason": "retry_scheduled"}
            return await EnterpriseCsAutomationService(db).handle_customer_message(
                conversation_id=conversation_id,
                customer_user_id=customer_user_id,
                message_id=message_id,
                body=body,
                market_token=market_token,
            )


async def recover_enterprise_cs_messages() -> None:
    from app.application.enterprise_cs_automation import RETRY_DELAY_SECONDS, _enabled

    if not _enabled():
        return
    now = utc_now_naive()
    with HostSessionLocal() as db:
        oldest_ids = (
            select(func.min(ImMessage.id))
            .where(
                ImMessage.origin == "customer",
                ImMessage.id > func.coalesce(CsState.last_customer_message_id, 0),
                or_(
                    CsState.status.is_(None),
                    CsState.status.not_in(("human_active", "ai_retrying")),
                    (CsState.status == "ai_retrying")
                    & (CsState.updated_at <= now - timedelta(seconds=RETRY_DELAY_SECONDS)),
                ),
            )
            .outerjoin(CsState, CsState.conversation_id == ImMessage.conversation_id)
            .group_by(ImMessage.conversation_id)
        )
        pending = db.execute(
            select(ImMessage.conversation_id, ImMessage.sender_user_id, ImMessage.id)
            .where(ImMessage.id.in_(oldest_ids), ImMessage.created_at <= now - _SCAN_GRACE)
            .order_by(ImMessage.id)
            .limit(16)
        ).all()
    for conversation_id, user_id, message_id in pending:
        try:
            # Recovery jobs carry only message identity. A ticket write still
            # requires a fresh account-bound credential from the request.
            await process_enterprise_cs_customer_message(conversation_id, user_id, message_id, "")
        except BOUNDARY_ERRORS:
            logger.exception("Enterprise CS recovery failed for message %s", message_id)


def start_enterprise_cs_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        recover_enterprise_cs_messages,
        "interval",
        seconds=10,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC),
    )
    scheduler.start()
    return scheduler
