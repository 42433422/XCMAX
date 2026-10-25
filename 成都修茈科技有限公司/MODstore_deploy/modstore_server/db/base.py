"""Compat path ``modstore_server.db.base`` → canonical ``db_base``.

AST / freeze tests that open ``db/base.py`` by filesystem path should use
``db/db_base.py`` after the debt19 rename. This module keeps import paths
working.
"""

from __future__ import annotations

from .db_base import (  # noqa: F401
    Base,
    _add_column_if_missing,
    _engine,
    _SessionFactory,
    _sqlite_add_column_if_missing,
    database_url,
    default_db_path,
    get_engine,
    get_session_factory,
    init_db,
    init_default_plan_templates,
)

__all__ = [
    "Base",
    "_SessionFactory",
    "_add_column_if_missing",
    "_engine",
    "_sqlite_add_column_if_missing",
    "database_url",
    "default_db_path",
    "get_engine",
    "get_session_factory",
    "init_db",
    "init_default_plan_templates",
]
