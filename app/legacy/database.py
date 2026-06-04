"""Shim — removed after v11. Use ``app.infrastructure.db.sync_engine``."""

from app.infrastructure.db import sync_engine as _sync

dispose_sync_engine = _sync.dispose_sync_engine
get_database_url = _sync.get_database_url
get_db_status = _sync.get_db_status
get_sync_engine = _sync.get_sync_engine
resolve_mode = _sync.resolve_mode
set_mode = _sync.set_mode

__all__ = [
    "dispose_sync_engine",
    "get_database_url",
    "get_db_status",
    "get_sync_engine",
    "resolve_mode",
    "set_mode",
]
