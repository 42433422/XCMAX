from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.db.init_db import ensure_mobile_push_bootstrap


def test_mobile_push_tables_are_created_idempotently(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'push.db'}")

    ensure_mobile_push_bootstrap(engine, swallow_errors=False)
    ensure_mobile_push_bootstrap(engine, swallow_errors=False)

    tables = set(inspect(engine).get_table_names())
    assert "mobile_device_tokens" in tables
    assert "mobile_notification_outbox" in tables
