"""Desktop runtime helpers for XCAGI.

The desktop build keeps the existing FastAPI + Vue contract intact, but swaps
in local defaults before the application imports database/cache modules.
"""

from __future__ import annotations

from .database_profile import (
    is_valid_remote_database_url,
    load_or_create_profile,
    profile_path,
    redact_database_url,
    resolve_storage_mode,
    save_profile,
)
from .deployment_modes import (
    build_sqlite_to_postgres_sync_plan,
    default_mode_id,
    load_database_storage_catalog,
    load_deployment_catalog,
    load_or_create_deployment_profile,
    mode_by_id,
    resolve_effective_mode_id,
    save_deployment_profile,
)
from .paths import (
    configure_desktop_environment,
    ensure_desktop_dirs,
    get_desktop_data_dir,
    get_desktop_mode,
    is_desktop_mode,
)

__all__ = [
    "configure_desktop_environment",
    "ensure_desktop_dirs",
    "build_sqlite_to_postgres_sync_plan",
    "default_mode_id",
    "get_desktop_data_dir",
    "get_desktop_mode",
    "is_desktop_mode",
    "is_valid_remote_database_url",
    "load_database_storage_catalog",
    "load_deployment_catalog",
    "load_or_create_deployment_profile",
    "load_or_create_profile",
    "mode_by_id",
    "profile_path",
    "redact_database_url",
    "resolve_effective_mode_id",
    "resolve_storage_mode",
    "save_deployment_profile",
    "save_profile",
]
