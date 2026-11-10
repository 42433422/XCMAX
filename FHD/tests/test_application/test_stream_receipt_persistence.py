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






@pytest.mark.parametrize("status", ["cancelled", "failed", "blocked", "paused"])
def test_unknown_control_summary_keeps_reconciliation_visible(status):
    from app.application.agent_orchestrator.business_harness import _result_summary

    run = AgentRun(user_id="owner", message="unknown business outcome", status=status)
    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    assert "已有调用的结果待核对" in _result_summary(run, [{"message": "已完成"}])
