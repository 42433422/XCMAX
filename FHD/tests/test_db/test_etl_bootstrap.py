from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.db.init_db import ensure_sqlite_etl_bootstrap


def test_desktop_etl_tables_are_created_idempotently(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'desktop.db'}")

    ensure_sqlite_etl_bootstrap(engine, swallow_errors=False)
    ensure_sqlite_etl_bootstrap(engine, swallow_errors=False)

    tables = set(inspect(engine).get_table_names())
    assert {
        "etl_uploads",
        "etl_templates",
        "etl_template_versions",
        "etl_runs",
        "etl_run_rows",
        "etl_target_configs",
    }.issubset(tables)
