"""Independent connections must agree on one atomic Agent storage bootstrap."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)


@pytest.fixture(params=["sqlite", "postgresql"])
def schema_engines(request, tmp_path):
    """Never use production tables: each PostgreSQL case owns a fresh schema."""
    admin = None
    schema = "agent_bootstrap_" + uuid.uuid4().hex
    if request.param == "postgresql":
        url = os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL")
        if not url:
            pytest.skip("requires an explicit test PostgreSQL service")
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        options = {"options": f"-csearch_path={schema} -cstatement_timeout=10000"}
    else:
        url = f"sqlite:///{tmp_path / 'agent-bootstrap.sqlite'}"
        options = {"timeout": 10}
    engines = [create_engine(url, connect_args=options, poolclass=NullPool) for _ in range(2)]
    try:
        yield engines
    finally:
        for engine in engines:
            engine.dispose()
        if admin is not None:
            with admin.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()


@pytest.mark.parametrize(
    "repository_type", [SQLAlchemyAgentRunRepository, SQLAlchemyTaskExecutionRepository]
)
def test_parallel_agent_schema_creation_waits_before_inspection(schema_engines, repository_type):
    first_engine, second_engine = schema_engines
    repositories = [repository_type(session_factory=sessionmaker(bind=e)) for e in schema_engines]
    first_creating, release, second_started, second_ddl = Event(), Event(), Event(), Event()

    def hold_first(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("CREATE TABLE") and not first_creating.is_set():
            first_creating.set()
            assert release.wait(10), "bootstrap DDL barrier timed out"

    def observe_second(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().upper()
        if sql.startswith("CREATE TABLE"):
            second_ddl.set()
            second_started.set()
        elif sql.startswith("BEGIN IMMEDIATE") or "PG_ADVISORY_XACT_LOCK" in sql:
            second_started.set()

    event.listen(first_engine, "before_cursor_execute", hold_first)
    event.listen(second_engine, "before_cursor_execute", observe_second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(repositories[0]._ensure_schema)
        try:
            assert first_creating.wait(10)
            second = pool.submit(repositories[1]._ensure_schema)
            assert second_started.wait(10)
            assert not second_ddl.is_set(), "second connection raced the missing-table check"
        finally:
            release.set()
        first.result(timeout=15)
        second.result(timeout=15)
    assert inspect(first_engine).get_table_names()
    assert repositories[0]._schema_ready and repositories[1]._schema_ready


@pytest.mark.parametrize(
    "repository_type", [SQLAlchemyAgentRunRepository, SQLAlchemyTaskExecutionRepository]
)
def test_failed_agent_schema_bootstrap_rolls_back_then_retries(schema_engines, repository_type):
    engine, reader = schema_engines
    repository = repository_type(session_factory=sessionmaker(bind=engine))
    created = []

    def fail_after_first_table(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("CREATE TABLE"):
            created.append(statement)
            if len(created) == 2:
                raise RuntimeError("injected schema creation failure")

    event.listen(engine, "before_cursor_execute", fail_after_first_table)
    try:
        with pytest.raises(RuntimeError, match="injected schema creation failure"):
            repository._ensure_schema()
    finally:
        event.remove(engine, "before_cursor_execute", fail_after_first_table)
    assert repository._schema_ready is False
    assert inspect(reader).get_table_names() == []
    repository._ensure_schema()
    assert repository._schema_ready is True
    assert len(inspect(reader).get_table_names()) == 3


def test_schema_lock_timeout_rolls_back_and_allows_later_retry(schema_engines):
    holder, _ = schema_engines
    postgres = holder.dialect.name == "postgresql"
    with holder.connect() as conn:
        schema = conn.exec_driver_sql("SELECT current_schema()").scalar_one() if postgres else ""
    options = (
        {"options": f"-csearch_path={schema} -clock_timeout=50"} if postgres else {"timeout": 0.05}
    )
    # One pooled connection lets us also verify SET LOCAL does not leak settings.
    candidate = create_engine(holder.url, connect_args=options, pool_size=1, max_overflow=0)
    repository = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=candidate))
    try:
        with holder.begin() as conn:
            conn.exec_driver_sql(
                "SELECT pg_advisory_xact_lock("
                "hashtext('xcagi.schema.bootstrap'), hashtext(current_schema()))"
                if postgres
                else "BEGIN IMMEDIATE"
            )
            started = time.monotonic()
            with pytest.raises(OperationalError) as caught:
                repository._ensure_schema()
            assert time.monotonic() - started < 2
            if postgres:
                assert caught.value.orig.sqlstate == "55P03"
            else:
                assert caught.value.orig.sqlite_errorcode == 5  # SQLITE_BUSY
            assert repository._schema_ready is False
            assert inspect(candidate).get_table_names() == []
        repository._ensure_schema()
        assert len(inspect(candidate).get_table_names()) == 3
        if postgres:
            with candidate.connect() as conn:
                assert conn.exec_driver_sql("SHOW lock_timeout").scalar_one() == "50ms"
    finally:
        candidate.dispose()


@pytest.mark.parametrize(
    "repository_type", [SQLAlchemyAgentRunRepository, SQLAlchemyTaskExecutionRepository]
)
def test_connection_bound_bootstrap_does_not_commit_or_cache_outer_transaction(
    schema_engines, repository_type
):
    engine, reader = schema_engines
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE caller_data (value INTEGER)")
    with engine.connect() as conn:
        repository = repository_type(session_factory=sessionmaker(bind=conn))
        conn.exec_driver_sql("INSERT INTO caller_data VALUES (1)")
        repository._ensure_schema()
        assert conn.in_transaction()
        assert len(inspect(conn).get_table_names()) == 4
        with reader.connect() as independent:
            assert independent.exec_driver_sql("SELECT COUNT(*) FROM caller_data").scalar() == 0
        conn.rollback()
        assert inspect(reader).get_table_names() == ["caller_data"]
        # Reuse the same repository and Connection after the caller rolls back
        # the DDL. A cached schema-ready bit must not suppress real creation.
        repository._ensure_schema()
        assert len(inspect(conn).get_table_names()) == 4
        conn.commit()
        assert len(inspect(reader).get_table_names()) == 4


def test_borrowed_schema_failure_preserves_caller_writes(schema_engines):
    engine, reader = schema_engines
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE caller_data (value INTEGER)")
    attempted = []

    def fail_second_table(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("CREATE TABLE"):
            attempted.append(statement)
            if len(attempted) == 2:
                raise RuntimeError("injected schema creation failure")

    with engine.connect() as conn:
        conn.exec_driver_sql("INSERT INTO caller_data VALUES (1)")
        repository = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=conn))
        event.listen(engine, "before_cursor_execute", fail_second_table)
        try:
            with pytest.raises(RuntimeError, match="injected schema creation failure"):
                repository._ensure_schema()
        finally:
            event.remove(engine, "before_cursor_execute", fail_second_table)
        assert conn.in_transaction()
        assert inspect(conn).get_table_names() == ["caller_data"]
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM caller_data").scalar() == 1
        conn.commit()
    with reader.connect() as independent:
        assert independent.exec_driver_sql("SELECT COUNT(*) FROM caller_data").scalar() == 1
