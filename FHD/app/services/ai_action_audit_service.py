"""AI action-audit schema verification."""

from __future__ import annotations

import logging

from app.db import engine
from app.db.schema_contract import assert_tables_present

logger = logging.getLogger(__name__)


def ensure_ai_action_audit_table() -> None:
    """Fail closed if the Alembic-owned audit table is unavailable."""
    assert_tables_present(engine, {"ai_action_audit"})
    logger.info("ai_action_audit Alembic schema verified")
