from __future__ import annotations

from pathlib import Path

from modstore_server.db import base
from modstore_server import models_db


def test_pytest_sqlite_flag_wins_over_production_database_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("MODSTORE_DB_PATH", str(db_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/modstore")
    monkeypatch.setenv("MODSTORE_PYTEST_USE_SQLITE", "1")

    expected = f"sqlite:///{db_path}"
    assert base.database_url() == expected
    assert models_db.database_url() == expected
