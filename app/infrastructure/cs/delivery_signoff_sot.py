"""客户签收记录真相源：PostgreSQL（生产）| SQLite crm.sqlite3（legacy）。"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return (os.environ.get("DATABASE_URL") or "").strip().lower()


def signoff_backend() -> str:
    raw = (
        (
            os.environ.get("CS_SIGNOFF_BACKEND")
            or os.environ.get("CS_DELIVERY_SIGNOFF_BACKEND")
            or ""
        )
        .strip()
        .lower()
    )
    if raw in ("postgres", "postgresql", "pg", "fhd_pg"):
        return "postgres"
    if raw in ("sqlite", "local", "crm"):
        return "sqlite"
    if "postgresql" in _database_url():
        return "postgres"
    return "sqlite"


def is_postgres_signoff_sot() -> bool:
    return signoff_backend() == "postgres"


def signoff_storage_hint() -> str:
    if is_postgres_signoff_sot():
        return "postgresql:cs_delivery_signoffs"
    return "sqlite:crm.sqlite3/cs_delivery_signoffs"
