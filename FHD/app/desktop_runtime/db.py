"""Database helpers for the desktop runtime."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .database_profile import configured_remote_database_url
from .desktop_runtime_paths import ensure_desktop_dirs, sqlite_database_url


def configure_sqlite_defaults(data_dir: str | os.PathLike[str] | None = None) -> str:
    """Apply the validated desktop profile, defaulting to local SQLite."""

    dirs = ensure_desktop_dirs(data_dir)
    url = sqlite_database_url(dirs["root"])
    os.environ["DATABASE_URL"] = (
        configured_remote_database_url(dirs["root"])
        or os.environ.get("XCAGI_DESKTOP_DATABASE_URL")
        or url
    )
    os.environ["VECTOR_DB_URL"] = (
        os.environ.get("XCAGI_DESKTOP_VECTOR_DB_URL") or os.environ["DATABASE_URL"]
    )
    os.environ.setdefault("DATABASE_PATH", str(dirs["data"]))
    return os.environ["DATABASE_URL"]


def database_file(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return ensure_desktop_dirs(data_dir)["data"] / "xcagi.db"


@dataclass(frozen=True)
class DatabaseCheck:
    state: Literal["healthy", "corrupt", "unavailable"]
    detail: str = ""
    sqlite_errorcode: int | None = None


def check_database(db_path: Path, *, full: bool = False) -> DatabaseCheck:
    """Only SQLite corruption evidence authorizes replacing a database.

    Busy, locked, unavailable storage and interrupted checks are inconclusive;
    they must never authorize restoring an older snapshot over committed data.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        rows = conn.execute("PRAGMA integrity_check" if full else "PRAGMA quick_check").fetchall()
        if rows == [("ok",)]:
            return DatabaseCheck("healthy")
        if rows:
            return DatabaseCheck("corrupt", str(rows[0][0]))
        return DatabaseCheck("unavailable", "SQLite check returned no result")
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", None)
        corrupt = code is not None and code & 0xFF in {
            sqlite3.SQLITE_CORRUPT,
            sqlite3.SQLITE_NOTADB,
        }
        return DatabaseCheck("corrupt" if corrupt else "unavailable", str(exc), code)
    finally:
        if conn is not None:
            conn.close()


def integrity_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA integrity_check，返回 True 当且仅当结果为 'ok'。"""
    return check_database(db_path, full=True).state == "healthy"


def quick_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA quick_check（启动时用，比 integrity_check 快）。"""
    return check_database(db_path).state == "healthy"
