"""Compat module path: debt19 renamed paths.py → desktop_runtime_paths.py."""

from __future__ import annotations

from .desktop_runtime_paths import (  # noqa: F401
    clear_database_recovery_marker,
    configure_desktop_environment,
    ensure_desktop_dirs,
    get_desktop_data_dir,
    get_desktop_mode,
    is_desktop_mode,
    sqlite_database_url,
)

__all__ = [
    "get_desktop_mode",
    "is_desktop_mode",
    "get_desktop_data_dir",
    "ensure_desktop_dirs",
    "sqlite_database_url",
    "clear_database_recovery_marker",
    "configure_desktop_environment",
]
