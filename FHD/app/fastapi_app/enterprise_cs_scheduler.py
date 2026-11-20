"""Resume enterprise CS turns from the existing IM message log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select

from app.application.enterprise_cs_automation import (
    RETRY_DELAY_SECONDS,
    _enabled,
    process_enterprise_cs_customer_message,
)
from app.db import HostSessionLocal
from app.db.models.im import ImCustomerServiceAutomationState as CsState
from app.db.models.im import ImMessage
from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)
_SCAN_GRACE = timedelta(seconds=20)


async def recover_enterprise_cs_messages() -> None:
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
                    CsState.status.not_in(
                        (
                            "human_active",
                            "ai_retrying",
                            "ai_waiting_session",
                            "ai_intake_waiting_session",
                        )
                    ),
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
            await process_enterprise_cs_customer_message(
                conversation_id, user_id, message_id, "", defer_missing_credential=True
            )
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
