"""Behavioral contracts between database selection, schema repair and startup."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy
from sqlalchemy import create_engine, inspect, text

import app.db as database
from app.db import init_db
from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id


def test_auth_resolves_a_proxy_but_column_repair_uses_the_supplied_engine(monkeypatch):
    real_engine = create_engine("sqlite:///:memory:")
    proxy = MagicMock()
    global_engine = MagicMock(return_value=real_engine)
    monkeypatch.setattr(database, "_get_engine", global_engine)
    assert init_db._resolve_auth_bootstrap_engine(proxy) is real_engine
    global_engine.assert_called_once_with()
    global_engine.reset_mock()
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["sessions"]
    inspector.get_columns.return_value = [{"name": "market_refresh_token"}]
    inspect_engine = MagicMock(return_value=inspector)
    monkeypatch.setattr(sqlalchemy, "inspect", inspect_engine)

    init_db.ensure_sessions_market_refresh_token_column(proxy)

    inspect_engine.assert_called_once_with(proxy)
    global_engine.assert_not_called()
    proxy.begin.assert_not_called()
    real_engine.dispose()


def test_explicit_url_selects_the_database_before_the_supplied_engine(monkeypatch):
    chosen = create_engine("sqlite:///:memory:")
    other = create_engine("sqlite:///:memory:")
    for engine in (chosen, other):
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE sessions (id INTEGER PRIMARY KEY)"))
    create = MagicMock(return_value=chosen)
    monkeypatch.setattr(database, "_create_engine_for_url", create)
    monkeypatch.setattr(database, "_get_engine", MagicMock(side_effect=AssertionError("global")))

    init_db.ensure_sessions_market_refresh_token_column(other, database_url=" sqlite:///chosen.db ")

    create.assert_called_once_with("sqlite:///chosen.db")
    assert "market_refresh_token" in {
        column["name"] for column in inspect(chosen).get_columns("sessions")
    }
    assert "market_refresh_token" not in {
        column["name"] for column in inspect(other).get_columns("sessions")
    }
    chosen.dispose()
    other.dispose()


_SQLITE_ONLY = (
    "ensure_sqlite_auth_bootstrap",
    "ensure_sqlite_rbac_bootstrap",
    "ensure_sqlite_inventory_bootstrap",
    "ensure_sqlite_enterprise_business_bootstrap",
)
_COMMON = (
    "ensure_user_preferences_bootstrap",
    "ensure_neuro_event_log_bootstrap",
    "ensure_sqlite_im_bootstrap",
    "ensure_employee_run_log_bootstrap",
    "ensure_ai_conversation_bootstrap",
    "ensure_mobile_push_bootstrap",
)


@pytest.mark.parametrize("url", ["sqlite:///desktop.db", "postgresql://server/main"])
def test_runtime_bootstrap_uses_late_bound_steps_in_dependency_order(monkeypatch, url):
    calls = []
    engine = object()
    names = (
        *_SQLITE_ONLY,
        *_COMMON,
        "ensure_sqlite_elt_bootstrap",
        "ensure_erp_bootstrap",
        "ensure_postgresql_auth_bootstrap",
    )
    for name in names:

        def record(actual_engine, *, database_url, swallow_errors=None, _name=name):
            calls.append((_name, actual_engine, database_url, swallow_errors))

        monkeypatch.setattr(init_db, name, record)

    init_db.ensure_runtime_auth_bootstrap(engine, database_url=f" {url} ")

    first = list(_SQLITE_ONLY) if url.startswith("sqlite") else ["ensure_postgresql_auth_bootstrap"]
    last = (
        ["ensure_sqlite_elt_bootstrap", "ensure_erp_bootstrap"]
        if url.startswith("sqlite")
        else ["ensure_erp_bootstrap"]
    )
    assert [name for name, *_ in calls] == first + list(_COMMON) + last
    assert all(actual is engine and actual_url == url for _, actual, actual_url, _ in calls)
    assert all(
        swallow is (None if name == "ensure_postgresql_auth_bootstrap" else False)
        for name, _, _, swallow in calls
    )


@pytest.mark.parametrize("required", [False, True])
def test_only_access_token_repair_requires_the_column_after_a_ddl_failure(monkeypatch, required):
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    engine.begin.side_effect = OSError("DDL unavailable")
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["sessions"]
    inspector.get_columns.return_value = [{"name": "id"}]
    monkeypatch.setattr(sqlalchemy, "inspect", MagicMock(return_value=inspector))
    if required:
        with pytest.raises(RuntimeError, match="缺少 market_access_token"):
            init_db.ensure_sessions_market_access_token_column(engine)
    else:
        init_db.ensure_sessions_market_refresh_token_column(engine)


def test_mod_seed_copies_preserve_existing_content_and_use_first_seed(monkeypatch, tmp_path):
    work = tmp_path / "work"
    seeds = [tmp_path / "first", tmp_path / "second"]
    for directory, value in zip(seeds, (1, 2), strict=True):
        directory.mkdir()
        with sqlite3.connect(directory / "products.db") as connection:
            connection.execute("CREATE TABLE seed (value INTEGER)")
            connection.execute("INSERT INTO seed VALUES (?)", (value,))
    monkeypatch.setattr(init_db, "get_app_data_dir", lambda: str(work))
    monkeypatch.setattr(init_db, "_iter_seed_dirs", lambda: [str(path) for path in seeds])

    init_db.initialize_databases(["products.db"])
    init_db.ensure_sqlite_per_mod_database_copies(["alpha", "beta", "alpha"], ["products.db"])
    token = set_request_active_mod_id("alpha")
    try:
        active_path = Path(init_db.get_db_path())
        assert active_path.name == "products__alpha.db"
        with sqlite3.connect(active_path) as connection:
            connection.execute("UPDATE seed SET value = 9")
    finally:
        reset_request_active_mod_id(token)
    init_db.initialize_databases(["products.db"])
    init_db.ensure_sqlite_per_mod_database_copies(["alpha", "beta"], ["products.db"])
    for filename, expected in (
        ("products.db", 1),
        ("products__alpha.db", 9),
        ("products__beta.db", 1),
    ):
        with sqlite3.connect(work / filename) as connection:
            assert connection.execute("SELECT value FROM seed").fetchall() == [(expected,)]


class _PostgresSequenceOnSQLite:
    """Exercise bootstrap order on a real schema; this is not a PostgreSQL SQL test."""

    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def begin(self):
        with self.engine.begin() as connection:
            yield _PortableConnection(connection)

    def connect(self):
        return self.engine.connect()


class _PortableConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=None):
        sql = str(statement).replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        sql = sql.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN").replace("JSONB", "TEXT")
        return self.connection.execute(text(sql), parameters or {})


@pytest.mark.parametrize("existing_empty", [False, True])
def test_postgresql_sequence_prepares_existing_profile_columns_before_admin_seed(
    monkeypatch, existing_empty
):
    """The fresh PostgreSQL CREATE/seed sequence must not require a later lifespan repair."""
    underlying = create_engine("sqlite:///:memory:")
    if existing_empty:
        with underlying.begin() as connection:
            connection.execute(
                text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
                    display_name VARCHAR, email VARCHAR, role VARCHAR, is_active BOOLEAN,
                    mfa_enabled BOOLEAN, tier VARCHAR(32), industry_id VARCHAR(32),
                    created_at TIMESTAMP
                )
            """)
            )
    postgres = _PostgresSequenceOnSQLite(underlying)
    monkeypatch.setattr(init_db, "_resolve_auth_bootstrap_engine", lambda *args, **kwargs: postgres)
    monkeypatch.setattr(
        sqlalchemy,
        "inspect",
        lambda candidate: inspect(underlying if candidate is postgres else candidate),
    )
    monkeypatch.setenv("ADMIN_USERNAME", "sequence-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-seed-password")

    init_db.ensure_postgresql_auth_bootstrap(postgres)

    with underlying.connect() as connection:
        assert connection.execute(text("SELECT username FROM users")).fetchall() == [
            ("sequence-admin",)
        ]
        assert connection.execute(
            text("SELECT failed_login_attempts, email_verified FROM users")
        ).fetchone() == (0, 0)
    with underlying.begin() as connection:
        connection.execute(
            text("UPDATE users SET display_name = 'retained', password = 'existing-hash'")
        )
    init_db.ensure_postgresql_auth_bootstrap(postgres)
    with underlying.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
        assert connection.execute(text("SELECT display_name, password FROM users")).fetchone() == (
            "retained",
            "existing-hash",
        )
    underlying.dispose()


def test_im_migration_step_has_only_its_historical_schema_and_preserves_rows():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import IntegrityError

    from app.db.schema_migrations.im_message_provenance import apply_message_provenance

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE im_messages (id INTEGER PRIMARY KEY, body TEXT)"))
        connection.execute(text("INSERT INTO im_messages VALUES (1, 'retained')"))
        for _ in range(2):
            apply_message_provenance(Operations(MigrationContext.configure(connection)))
    init_db.ensure_im_customer_service_columns(engine)
    inspector = inspect(engine)
    assert inspector.get_table_names() == ["im_messages"]
    columns = {column["name"]: column for column in inspector.get_columns("im_messages")}
    assert set(columns) == {"id", "body", "origin", "operator_user_id"}
    assert columns["origin"]["nullable"] is False
    assert str(columns["origin"]["type"]) == "VARCHAR(32)"
    assert columns["origin"]["default"] == "'user'"
    assert columns["operator_user_id"]["nullable"] is True
    assert str(columns["operator_user_id"]["type"]) == "INTEGER"
    assert columns["operator_user_id"]["default"] is None
    assert [
        (index["name"], index["column_names"], index["unique"])
        for index in inspector.get_indexes("im_messages")
    ] == [("ix_im_messages_operator_user_id", ["operator_user_id"], 0)]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM im_messages")).fetchall() == [
            (1, "retained", "user", None)
        ]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO im_messages (id, origin) VALUES (2, NULL)"))
    engine.dispose()


def test_postgresql_im_migration_compiles_concurrent_safe_ddl(monkeypatch):
    """Offline PostgreSQL compilation verifies guards, not live concurrent execution."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.schema_migrations.im_message_provenance import apply_message_provenance

    inspector = MagicMock()
    inspector.get_table_names.return_value = ["im_messages"]
    inspector.get_columns.return_value = [{"name": "id"}]
    inspector.get_indexes.return_value = []
    monkeypatch.setattr(sqlalchemy, "inspect", lambda bind: inspector)
    output = StringIO()
    operations = Operations(
        MigrationContext.configure(
            url="postgresql://", opts={"as_sql": True, "output_buffer": output}
        )
    )
    for _ in range(2):
        apply_message_provenance(operations)
    statements = output.getvalue()
    assert len([statement for statement in statements.split(";") if statement.strip()]) == 6
    assert (
        statements.count("ADD COLUMN IF NOT EXISTS origin VARCHAR(32) DEFAULT 'user' NOT NULL") == 2
    )
    assert statements.count("ADD COLUMN IF NOT EXISTS operator_user_id INTEGER") == 2
    assert statements.count("CREATE INDEX IF NOT EXISTS ix_im_messages_operator_user_id") == 2
    assert "im_cs_automation_states" not in statements
    assert "alembic_version" not in statements


def test_existing_im_revision_keeps_its_upgrade_and_downgrade_behavior():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.util import load_python_file

    directory = Path(init_db.__file__).parents[2] / "alembic" / "versions"
    revision = load_python_file(str(directory), "2026_08_31_enterprise_cs_ai.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE im_conversations (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE im_messages (id INTEGER PRIMARY KEY, body TEXT)"))
        connection.execute(text("INSERT INTO im_messages VALUES (1, 'retained')"))
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
            revision.upgrade()
            assert set(inspect(connection).get_table_names()) == {
                "im_conversations",
                "im_messages",
                "im_cs_automation_states",
            }
            assert connection.execute(text("SELECT body, origin FROM im_messages")).fetchone() == (
                "retained",
                "user",
            )
            revision.downgrade()
        assert set(inspect(connection).get_table_names()) == {"im_conversations", "im_messages"}
        assert connection.execute(text("SELECT * FROM im_messages")).fetchall() == [(1, "retained")]
    engine.dispose()
