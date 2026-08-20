"""Persistence adapter for shipment-template usage audit records."""

from __future__ import annotations

import logging

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def log_template_usage(template_id: str | None, *, action: str, result_text: str) -> None:
    template_key = str(template_id or "").strip()
    database_id: int | None = None
    if template_key.startswith("db:"):
        try:
            database_id = int(template_key.split(":", 1)[1])
        except ValueError:
            database_id = None
    elif template_key.isdigit():
        database_id = int(template_key)
    if database_id is None:
        return

    try:
        from sqlalchemy import text

        from app.db.session import get_db

        with get_db() as db:
            db.execute(
                text(
                    """
                    INSERT INTO template_usage_log (template_id, action, result)
                    VALUES (:template_id, :action, :result)
                    """
                ),
                {
                    "template_id": database_id,
                    "action": action[:64],
                    "result": str(result_text or "")[:500],
                },
            )
            db.commit()
    except RECOVERABLE_ERRORS as exc:
        logger.debug("template_usage_log skip: %s", exc)
