"""Read executed receipts through a separate connection before sibling tools finish."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.chat_trace import record_legacy_stream_tool_receipt
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.db.db_base import Base
from app.infrastructure.chat_stream_lifetime import (
    StreamLifetime,
    StreamReceiptPersistenceError,
    current_lifetime,
)
from app.legacy.chat import legacy_chat_adapter as adapter


@pytest.fixture
def audit_store(tmp_path):
    path = tmp_path / "receipts.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    run = AgentRun(user_id="receipt-owner", message="isolated tool receipt", status="running")
    run.metadata["runtime_context"] = {"tenant_id": 7}
    repository.save(run)
    set_agent_run_repository_for_tests(repository)
    with sqlite3.connect(path) as db:
        db.execute("create table receipt_probe(value text)")
    try:
        yield path, run
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


def read_audit(path, run):
    with sqlite3.connect(path) as db:
        row = db.execute(
            "select payload_json from agent_runs where run_id=?", (run.run_id,)
        ).fetchone()
        return json.loads(row[0])["metadata"].get("stream_tool_audit", [])


def tool(name):
    return SimpleNamespace(id=name, function=SimpleNamespace(name=name, arguments="{}"))


@pytest.mark.parametrize("sibling_fails", [False, True])
@pytest.mark.parametrize("storage_fails_once", [False, True])
def test_parallel_receipt_is_durable_before_sibling_finishes(
    audit_store, sibling_fails, storage_fails_once
):
    path, run = audit_store
    release, saved, entered = (threading.Event() for _ in range(3))
    attempts, executions = [], []
    lifetime = StreamLifetime()

    def persist(**receipt):
        attempts.append(receipt["sequence"])
        if storage_fails_once and len(attempts) == 1:
            raise OSError("transient audit outage")
        record_legacy_stream_tool_receipt(run, **receipt)
        saved.set()

    def execute(name, *args, **kwargs):
        executions.append(name)
        if name == "slow":
            entered.set()
            assert release.wait(5)
            if sibling_fails:
                raise ValueError("sibling failed after fast tool committed")
        with sqlite3.connect(path) as db:
            db.execute("insert into receipt_probe values(?)", (name,))
        return json.dumps({"success": True, "receipt": name})

    lifetime.observe_tools(persist)
    token = current_lifetime.set(lifetime)
    adapter.reset_planner_tool_dedup_state()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                copy_context().run,
                adapter.append_tool_messages,
                [],
                [tool("slow"), tool("fast")],
                workspace_root=None,
                execute_tool=execute,
            )
            try:
                assert entered.wait(3) and saved.wait(3)
                assert not future.done()
                audit = read_audit(path, run)
                assert [item["record"]["output"]["receipt"] for item in audit] == ["fast"]
                with sqlite3.connect(path) as db:
                    assert db.execute("select value from receipt_probe").fetchall() == [("fast",)]
            finally:
                release.set()
            if sibling_fails:
                with pytest.raises(ValueError, match="sibling failed"):
                    future.result(timeout=5)
            else:
                assert future.result(timeout=5) is None
        audit = read_audit(path, run)
        assert len(audit) == (1 if sibling_fails else 2)
        assert sorted(executions) == ["fast", "slow"]
        assert attempts.count(1) == (2 if storage_fails_once else 1)
    finally:
        current_lifetime.reset(token)


def test_receipt_outage_stops_tools_and_retries_only_persistence(audit_store):
    path, run = audit_store
    lifetime, unavailable, executions = StreamLifetime(), [True], []
    sequences = []

    def persist(**receipt):
        sequences.append(receipt["sequence"])
        if unavailable[0]:
            raise OSError("audit unavailable")
        record_legacy_stream_tool_receipt(run, **receipt)

    def execute(*args, **kwargs):
        executions.append("committed")
        with sqlite3.connect(path) as db:
            db.execute("insert into receipt_probe values('committed')")
        return '{"success": true}'

    lifetime.observe_tools(persist)
    lifetime.worker_started()
    token = current_lifetime.set(lifetime)
    adapter.reset_planner_tool_dedup_state()
    try:
        with pytest.raises(StreamReceiptPersistenceError):
            adapter.append_tool_messages(
                [],
                [tool("import_excel_to_database"), tool("never")],
                workspace_root=None,
                execute_tool=execute,
            )
        assert lifetime.stopped.is_set() and lifetime.reason == "tool_receipt_persistence_failed"
        assert read_audit(path, run) == [] and executions == ["committed"]
        unavailable[0] = False
        lifetime.worker_finished()
        assert len(read_audit(path, run)) == 1 and sequences == [1, 1, 1]
        with sqlite3.connect(path) as db:
            assert db.execute("select count(*) from receipt_probe").fetchone()[0] == 1
    finally:
        current_lifetime.reset(token)


@pytest.mark.parametrize("status", ["cancelled", "failed", "blocked", "paused"])
def test_unknown_control_summary_keeps_reconciliation_visible(status):
    from app.application.agent_orchestrator.business_harness import _result_summary

    run = AgentRun(user_id="owner", message="unknown business outcome", status=status)
    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    assert "已有调用的结果待核对" in _result_summary(run, [{"message": "已完成"}])
