"""Lazy access to ``app.db.init_db`` for monkeypatch-compatible lookups."""

from __future__ import annotations

from typing import Any


def module() -> Any:
    import app.db.init_db as init_db_module

    return init_db_module
