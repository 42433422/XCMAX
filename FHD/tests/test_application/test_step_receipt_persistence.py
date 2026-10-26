"""Committed synthetic effects and independent SQLite reads across optional sink failures."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.step_execution import StepExecution
from app.db.db_base import Base


@pytest.mark.parametrize("failed_sink", [None, "artifacts", "observation"])
@pytest.mark.parametrize("unknown", [False, True])
def test_receipt_is_durable_before_optional_sinks(
    tmp_path, monkeypatch, failed_sink, unknown
):
    def no_network(*args, **kwargs):
        raise AssertionError("synthetic receipt tests prohibit network/model access")

    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("socket.create_connection", no_network)
    path = tmp_path / "receipt.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    with engine.begin() as db:
        db.exec_driver_sql(
            "CREATE TABLE synthetic_effects(id INTEGER PRIMARY KEY, receipt TEXT)"
        )
    step = AgentStep("write", "synthetic", "write")
    run = AgentRun(
        user_id="synthetic", message="persist original receipt", steps=[step]
    )
    receipt = {"success": not unknown, "receipt_id": "original-committed-effect"}
    if unknown:
        receipt.update(outcome="unknown", retryable=False, reconciliation_required=True)
    observed = []

    def readback():
        with sqlite3.connect(path) as reopened:
            payload = json.loads(
                reopened.execute(
                    "SELECT payload_json FROM agent_runs WHERE run_id=?", (run.run_id,)
                ).fetchone()[0]
            )
            effects = reopened.execute(
                "SELECT receipt FROM synthetic_effects"
            ).fetchall()
        assert effects == [(receipt["receipt_id"],)]
        stored_step, stored_call = payload["steps"][0], payload["tool_calls"][0]
        assert (
            stored_step["status"]
            == stored_call["status"]
            == ("failed" if unknown else "completed")
        )
        assert stored_step["output"] == stored_call["output"]
        assert stored_step["finished_at"] == stored_call["finished_at"] != ""
        assert (
            stored_step["attempt_count"]
            == stored_call["metadata"]["attempt_count"]
            == 1
        )
        if unknown:
            assert stored_step["output"]["reconciliation_evidence"] == receipt
            assert payload["metadata"]["non_retryable"] is True
            assert (
                payload["metadata"]["recovery"]["state"]
                == "manual_reconciliation_required"
            )
        else:
            assert stored_step["output"] == receipt
        return payload

    def execute(*args, **kwargs):
        with sqlite3.connect(path) as business:
            business.execute(
                "INSERT INTO synthetic_effects(receipt) VALUES(?)",
                (receipt["receipt_id"],),
            )
        return receipt

    def sink(name):
        def apply(*args, **kwargs):
            readback()  # The receipt must already be visible to another connection.
            observed.append(name)
            if failed_sink == name:
                raise RuntimeError(f"synthetic {name} failure after commit")
            return {"observation_id": "synthetic-observation"}

        return apply

    dependencies = SimpleNamespace(
        action_spec=lambda *_: SimpleNamespace(
            cost_units=0, permission="", timeout_seconds=2
        ),
        validate=lambda *_: SimpleNamespace(ok=True),
        refresh_budget=lambda _: None,
    )
    execution = StepExecution(
        repo,
        SimpleNamespace(execute_with_deadline=execute),
        RunUsageLedger(dependencies),
        dependencies,
        attach_artifacts=sink("artifacts"),
        observe=sink("observation"),
    )
    try:
        if failed_sink:
            with pytest.raises(RuntimeError, match=f"synthetic {failed_sink} failure"):
                execution.execute_step(run, step, runtime_context={}, node_outputs={})
        else:
            execution.execute_step(run, step, runtime_context={}, node_outputs={})
        persisted = readback()
        assert observed == (
            ["artifacts"]
            if failed_sink == "artifacts"
            else ["artifacts", "observation"]
        )
        events = [event["event_type"] for event in persisted["events"]]
        if failed_sink is None:
            assert ("tool.failed" if unknown else "tool.completed") in events
        else:
            assert events == ["tool.started"]
        reopened_repo = SQLAlchemyAgentRunRepository(
            session_factory=sessionmaker(bind=engine)
        )
        assert reopened_repo.get(run.run_id).to_dict() == persisted
    finally:
        engine.dispose()
