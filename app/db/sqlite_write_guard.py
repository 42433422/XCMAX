"""Compatibility shim — implementation lives in ``app.db.session_cache`` (T28)."""

from __future__ import annotations

from app.db.session_cache import sqlite_write_guard

__all__ = ["sqlite_write_guard"]
