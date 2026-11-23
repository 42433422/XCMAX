"""Per-run graph composition and SQL session cleanup."""

import asyncio
import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime


def test_each_graph_uses_its_own_dispatcher():
    first, second = Mock(return_value={"success": True}), Mock(return_value={"success": True})
    plan = PlanGraph(
        plan_id="composition",
        intent="test",
        nodes=[
            WorkflowNode(
                node_id="read",
                tool_id="products",
                action="query",
                params={},
                risk="low",
                idempotent=True,
            )
        ],
    )
    assert XCAGILangGraphRuntime(tool_dispatcher=first).run(plan).success
    assert XCAGILangGraphRuntime(tool_dispatcher=second).run(plan).success
    assert first.call_count == second.call_count == 1


@pytest.mark.parametrize("failure", [RuntimeError, KeyError, TypeError, AssertionError, OSError])
def test_run_repository_closes_and_rolls_back_failed_session(failure):
    session = Mock()
    repo = SQLAlchemyAgentRunRepository(session_factory=lambda: session, auto_create=False)
    error = failure("injected storage failure")
    with pytest.raises(failure) as caught:
        with repo._session_scope():
            raise error
    assert caught.value is error
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.fixture
def sql_run_repository(tmp_path):
    database = tmp_path / "run-transactions.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE entries (value TEXT)")
    session = Session(engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=lambda: session, auto_create=False)
    try:
        yield repo, session, engine, database
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        OSError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        asyncio.CancelledError,
    ],
)
def test_run_repository_failure_discards_writes_and_preserves_error(
    sql_run_repository, failure, read_only
):
    repo, session, engine, database = sql_run_repository
    error = failure("failure after writing")
    with pytest.raises(failure) as caught:
        with repo._session_scope(read_only=read_only) as transaction:
            transaction.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
            raise error
    assert caught.value is error
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (0,)


@pytest.mark.parametrize("read_only", [False, True])
def test_run_repository_success_obeys_commit_policy(sql_run_repository, read_only):
    repo, session, engine, database = sql_run_repository
    with repo._session_scope(read_only=read_only) as transaction:
        transaction.execute(text("INSERT INTO entries VALUES ('written')"))
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT value FROM entries").fetchall() == (
            [] if read_only else [("written",)]
        )


@pytest.mark.parametrize("read_only", [False, True])
def test_run_repository_failure_rolls_back_a_joined_transaction(sql_run_repository, read_only):
    _, _, engine, database = sql_run_repository
    error = TypeError("invalid run update")
    with engine.connect() as connection, connection.begin() as transaction:
        session = Session(connection, join_transaction_mode="rollback_only")
        repo = SQLAlchemyAgentRunRepository(session_factory=lambda: session, auto_create=False)
        with pytest.raises(TypeError) as caught:
            with repo._session_scope(read_only=read_only) as db:
                db.execute(text("INSERT INTO entries VALUES ('must be rolled back')"))
                raise error
        assert caught.value is error
        assert transaction.is_active is False
        assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (0,)


@pytest.mark.parametrize("hook", ["before_commit", "after_commit"])
def test_run_repository_commit_hook_failure_preserves_error_and_closes(sql_run_repository, hook):
    repo, session, engine, database = sql_run_repository
    error = TypeError("commit hook failed")

    def fail_commit(_session):
        raise error

    event.listen(session, hook, fail_commit)
    with pytest.raises(TypeError) as caught:
        with repo._session_scope() as db:
            db.execute(text("INSERT INTO entries VALUES ('uncommitted')"))
    assert caught.value is error
    assert session.in_transaction() is False
    assert engine.pool.checkedout() == 0
    with closing(sqlite3.connect(database)) as reader:
        assert reader.execute("SELECT count(*) FROM entries").fetchone() == (
            int(hook == "after_commit"),
        )
