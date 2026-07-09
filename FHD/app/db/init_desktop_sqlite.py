"""
Desktop SQLite path helpers and business table bootstrap.

Split from ``init_db.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.db._init_db_facade import module as _init_db_facade
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

DEFAULT_DB_FILES: tuple[str, ...] = (
    "products.db",
    "inventory.db",
    "voice_learning.db",
    "error_collection.db",
)

_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _is_desktop_mode_env() -> bool:
    return (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in _TRUTHY_ENV_VALUES


def refresh_config_database_urls(config: Any | None = None) -> None:
    """Refresh database URL fields on a Config-like object from current environment."""
    if config is None:
        return
    for attr, env_name in (
        ("DATABASE_URL", "DATABASE_URL"),
        ("VECTOR_DB_URL", "VECTOR_DB_URL"),
        ("DATABASE_PATH", "DATABASE_PATH"),
    ):
        value = os.environ.get(env_name)
        if value:
            setattr(config, attr, value)


def _desktop_data_root(data_dir: str | None = None) -> Path:
    raw = data_dir or os.environ.get("XCAGI_DATA_DIR") or get_app_data_dir()
    return Path(raw).expanduser()


def _ensure_sqlite_business_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_name TEXT NOT NULL DEFAULT '',
                contact_person TEXT,
                contact_phone TEXT,
                address TEXT,
                is_active BOOLEAN DEFAULT 1,
                tenant_id INTEGER,
                unit_code TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                model_number TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT '',
                purchase_unit_id INTEGER,
                tenant_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def ensure_desktop_sqlite_business_tables_all_files(data_dir: str | None = None) -> None:
    """Ensure desktop SQLite databases have the business tables needed at startup."""
    root = _desktop_data_root(data_dir)
    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    candidates = {path for path in data_root.glob("*.db") if path.is_file()}
    candidates.update(path for path in root.glob("*.db") if path.is_file())
    if not candidates:
        candidates.add(data_root / "xcagi.db")
    for db_path in sorted(candidates):
        _ensure_sqlite_business_tables(db_path)


def ensure_runtime_database_environment() -> str:
    """Select the runtime database URL, forcing desktop mode onto local SQLite."""
    if _is_desktop_mode_env():
        root = _init_db_facade()._desktop_data_root()
        data_root = root / "data"
        db_path = data_root / "xcagi.db"
        url = f"sqlite:///{db_path}"
        data_root.mkdir(parents=True, exist_ok=True)
        os.environ["DATABASE_URL"] = url
        os.environ["DATABASE_PATH"] = str(data_root)
        _init_db_facade().ensure_desktop_sqlite_business_tables_all_files(str(root))
        try:
            from app.config import Config

            refresh_config_database_urls(Config)
        except RECOVERABLE_ERRORS:
            pass
        return url
    return os.environ.get("DATABASE_URL", "")

def get_db_path(db_name: str = "products.db") -> str:
    """
    获取主数据库（或指定 db）路径。

    当请求上下文存在 ``X-XCAGI-Active-Mod-Id``（SQLite 场景）时，与 ORM 的
    ``DATABASE_URL`` 改写一致，使用带 Mod 后缀的文件名（如 ``products__taiyangniao_pro.db``）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.request_active_mod_ctx import get_request_active_mod_id

    mod_id = get_request_active_mod_id()
    fname = sqlite_filename_with_mod_suffix(db_name, mod_id) if mod_id else db_name
    return os.path.join(_init_db_facade().get_app_data_dir(), fname)


def get_distillation_db_path() -> str:
    return get_db_path("distillation.db")
