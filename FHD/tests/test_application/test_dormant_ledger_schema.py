"""SQLite schema-only preparation, not ledger/executor readiness."""

import importlib
import multiprocessing
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory

from app.db.schema_migrations import business_action_ledger as schema


@pytest.fixture
def connection(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'ledger-schema.sqlite'}")
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def operations(conn):
    return Operations(MigrationContext.configure(conn))


def dump(conn):
    return list(conn.connection.driver_connection.iterdump())


def seed(conn):
    names = [name for name, _ in schema._COLUMNS]
    values = dict.fromkeys(names, "synthetic")
    values["receipt_json"] = '{"outcome":"unknown","retryable":false}'
    conn.execute(
        sa.text(
            "INSERT INTO agent_business_actions ("
            + ",".join(names)
            + ") VALUES ("
            + ",".join(":" + name for name in names)
            + ")"
        ),
        values,
    )


def test_default_optin_import_and_missing_schema_are_dormant(connection):
    from app.db.db_base import Base

    before = dump(connection)
    tables = set(Base.metadata.tables)
    importlib.reload(schema)
    assert set(Base.metadata.tables) == tables
    assert schema.TABLE_NAME not in Base.metadata.tables
    assert schema.prepare_business_action_schema(operations(connection)) is False
    assert dump(connection) == before
    with pytest.raises(schema.LedgerSchemaError, match="missing"):
        schema.validate_business_action_schema(operations(connection))
    for value in ["true", 1, None, [], object()]:
        with pytest.raises(schema.LedgerSchemaError, match="boolean"):
            schema.prepare_business_action_schema(operations(connection), opt_in=value)
    assert dump(connection) == before


def test_explicit_creation_exact_validation_and_retained_rollback(connection):
    op = operations(connection)
    assert schema.prepare_business_action_schema(op, opt_in=True)
    assert len(sa.inspect(connection).get_columns(schema.TABLE_NAME)) == 14
    seed(connection)
    before = dump(connection)
    schema.validate_business_action_schema(op)
    schema.prepare_business_action_schema(op, opt_in=True)
    schema.retain_business_action_schema(op)
    assert dump(connection) == before
    assert "alembic_version" not in sa.inspect(connection).get_table_names()


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_column",
        "wrong_length",
        "wrong_type",
        "nullable",
        "server_default",
        "wrong_pk",
        "unique",
        "check",
        "foreign_key",
        "index",
        "expression_index",
        "trigger",
    ],
)
def test_incompatible_schema_never_altered(connection, mutation):
    op = operations(connection)
    columns = []
    constraints = []
    for name, length in schema._COLUMNS:
        kind = sa.String(length) if length else sa.Text()
        if name == "user_id" and mutation == "wrong_length":
            kind = sa.String(99)
        if name == "user_id" and mutation == "wrong_type":
            kind = sa.Integer()
        primary = name == ("user_id" if mutation == "wrong_pk" else "action_key")
        columns.append(
            sa.Column(
                name,
                kind,
                primary_key=primary,
                nullable=name == "user_id" and mutation == "nullable",
                server_default="wrong"
                if name == "user_id" and mutation == "server_default"
                else None,
            )
        )
    if mutation == "extra_column":
        columns.append(sa.Column("extra", sa.Text()))
    if mutation == "unique":
        constraints.append(sa.UniqueConstraint("user_id"))
    if mutation == "check":
        constraints.append(sa.CheckConstraint("state != 'forbidden'"))
    if mutation == "foreign_key":
        op.create_table("parent", sa.Column("id", sa.String(128), primary_key=True))
        constraints.append(sa.ForeignKeyConstraint(["user_id"], ["parent.id"]))
        connection.exec_driver_sql("INSERT INTO parent VALUES ('synthetic')")
    op.create_table(schema.TABLE_NAME, *columns, *constraints)
    if mutation == "index":
        op.create_index("unexpected", schema.TABLE_NAME, ["user_id"])
    if mutation == "expression_index":
        connection.exec_driver_sql(
            "CREATE INDEX unexpected_expr ON agent_business_actions(lower(user_id))"
        )
    if mutation == "trigger":
        connection.exec_driver_sql(
            "CREATE TRIGGER unexpected_trigger AFTER INSERT ON agent_business_actions BEGIN SELECT 1; END"
        )
    seed(connection)
    before = dump(connection)
    for invoke in [schema.prepare_business_action_schema, schema.retain_business_action_schema]:
        with pytest.raises(schema.LedgerSchemaError):
            invoke(
                op, **({"opt_in": True} if invoke == schema.prepare_business_action_schema else {})
            )
        assert dump(connection) == before


def test_view_is_not_ledger_and_unsupported_dialect_is_rejected(connection, monkeypatch):
    connection.exec_driver_sql("CREATE VIEW agent_business_actions AS SELECT 1 AS action_key")
    before = dump(connection)
    with pytest.raises(schema.LedgerSchemaError):
        schema.prepare_business_action_schema(operations(connection), opt_in=True)
    assert dump(connection) == before
    monkeypatch.setattr(connection.dialect, "name", "postgresql")
    with pytest.raises(schema.LedgerSchemaError, match="SQLite"):
        schema.prepare_business_action_schema(operations(connection), opt_in=True)
    assert dump(connection) == before


def _check_autogenerate_in_spawned_process(database_url, output):
    # Run the real env module, including its connection setup, against only this
    # synthetic database. Never extract or execute a rewritten subset of source.
    os.environ["DATABASE_URL"] = database_url
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    script = ScriptDirectory.from_config(config)
    metadata = sa.MetaData()
    sa.Table("new_unrelated", metadata, sa.Column("id", sa.Integer(), primary_key=True))

    def inspect_migrations(_revision, context):
        diffs = compare_metadata(context, metadata)
        output.send([(item[0], item[1].name) for item in diffs])
        return []  # Inspect only; no migration is authorized by this test.

    with EnvironmentContext(config, script, fn=inspect_migrations, dont_mutate=True):
        script.run_env()
    output.close()


def test_autogenerate_retains_only_optin_table_without_masking_unrelated_diff(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'autogenerate.sqlite'}"
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        schema.prepare_business_action_schema(operations(connection), opt_in=True)
        connection.exec_driver_sql("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        before = dump(connection)
    context = multiprocessing.get_context("spawn")
    received, sending = context.Pipe(duplex=False)
    worker = context.Process(
        target=_check_autogenerate_in_spawned_process, args=(database_url, sending)
    )
    worker.start()
    sending.close()
    try:
        assert received.poll(30), "fresh Alembic environment import timed out"
        diffs = received.recv()
        worker.join(30)
        assert worker.exitcode == 0
        assert ("remove_table", schema.TABLE_NAME) not in diffs
        assert ("remove_table", "unrelated") in diffs
        assert ("add_table", "new_unrelated") in diffs
        with engine.connect() as connection:
            assert dump(connection) == before
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(10)
        received.close()
        engine.dispose()


def test_actual_desktop_bootstrap_does_not_create_or_modify_ledger(tmp_path, monkeypatch):
    import app.db as host_db
    from app.db.db_base import Base
    from app.desktop_runtime import migrate

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bootstrap.sqlite'}")
    # Inject only the explicitly selected synthetic engine/config path; execute
    # real bootstrap import and unrestricted Base.metadata.create_all unchanged.
    monkeypatch.setattr(migrate, "configure_desktop_environment", lambda path: None)
    monkeypatch.setattr(host_db, "dispose_and_recreate_engine", lambda: None)
    monkeypatch.setattr(host_db, "get_runtime_engine", lambda: engine)
    try:
        migrate.bootstrap_sqlite_schema(tmp_path)
        assert schema.TABLE_NAME not in sa.inspect(engine).get_table_names()
        assert schema.TABLE_NAME not in Base.metadata.tables
        with engine.begin() as conn:
            schema.prepare_business_action_schema(operations(conn), opt_in=True)
            seed(conn)
            receipt = conn.exec_driver_sql("SELECT * FROM agent_business_actions").all()
        migrate.bootstrap_sqlite_schema(tmp_path)
        with engine.begin() as conn:
            assert conn.exec_driver_sql("SELECT * FROM agent_business_actions").all() == receipt
            schema.validate_business_action_schema(operations(conn))
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["table", "view", "trigger"])
def test_temporary_shadows_and_triggers_fail_closed(connection, kind):
    op = operations(connection)
    schema.prepare_business_action_schema(op, opt_in=True)
    if kind == "table":
        connection.exec_driver_sql("CREATE TEMP TABLE agent_business_actions (id INTEGER)")
    elif kind == "view":
        connection.exec_driver_sql("CREATE TEMP VIEW agent_business_actions AS SELECT 1 AS id")
    else:
        connection.exec_driver_sql(
            "CREATE TEMP TRIGGER temp_ledger_trigger AFTER INSERT ON main.agent_business_actions BEGIN SELECT 1; END"
        )
    with pytest.raises(schema.LedgerSchemaError):
        schema.validate_business_action_schema(op)
