"""Database helpers for the desktop runtime."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .paths import ensure_desktop_dirs, sqlite_database_url


def configure_sqlite_defaults(data_dir: str | os.PathLike[str] | None = None) -> str:
    """Return and export the SQLite URL used by desktop mode."""

    dirs = ensure_desktop_dirs(data_dir)
    url = sqlite_database_url(dirs["root"])
    os.environ["DATABASE_URL"] = os.environ.get("XCAGI_DESKTOP_DATABASE_URL") or url
    os.environ["VECTOR_DB_URL"] = (
        os.environ.get("XCAGI_DESKTOP_VECTOR_DB_URL") or os.environ["DATABASE_URL"]
    )
    os.environ.setdefault("DATABASE_PATH", str(dirs["data"]))
    return os.environ["DATABASE_URL"]


def database_file(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return ensure_desktop_dirs(data_dir)["data"] / "xcagi.db"


def _pragma_ok(db_path: Path, pragma: str) -> bool:
    """跑指定 PRAGMA 校验，结果恰为 'ok' 时返回 True。"""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute(pragma).fetchone()
        return bool(result) and result[0] == "ok"
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def integrity_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA integrity_check，返回 True 当且仅当结果为 'ok'。"""
    return _pragma_ok(db_path, "PRAGMA integrity_check")


def quick_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA quick_check（启动时用，比 integrity_check 快）。"""
    return _pragma_ok(db_path, "PRAGMA quick_check")
