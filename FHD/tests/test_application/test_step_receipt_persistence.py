"""Committed synthetic effects and independent SQLite reads across optional sink failures."""

import copy
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
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult
from app.db.db_base import Base


@pytest.mark.parametrize("failed_sink", [None, "artifacts", "observation"])
@pytest.mark.parametrize("unknown", [False, True])
def test_receipt_is_durable_before_optional_sinks(tmp_path, monkeypatch, failed_sink, unknown):
    def no_network(*args, **kwargs):
        raise AssertionError("synthetic receipt tests prohibit network/model access")

    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("socket.create_connection", no_network)
    path = tmp_path / "receipt.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE synthetic_effects(id INTEGER PRIMARY KEY, receipt TEXT)")
    step = AgentStep("write", "synthetic", "write")
    run = AgentRun(user_id="synthetic", message="persist original receipt", steps=[step])
    receipt = {
        "success": not unknown,
        "receipt_id": "original-committed-effect",
        "artifacts": [
            {
                "artifact_id": "synthetic-receipt",
                "artifact_type": "json",
                "content": {"receipt_id": "original-committed-effect"},
            }
        ],
    }
    if unknown:
        receipt.update(outcome="unknown", retryable=False, reconciliation_required=True)
    original_receipt = copy.deepcopy(receipt)
    expected_output = (
        {**original_receipt, "message": "任务尚未完成"} if unknown else original_receipt
    )
    observed = []
    verified = []

    def readback():
        with sqlite3.connect(path) as reopened:
            payload = json.loads(
                reopened.execute(
                    "SELECT payload_json FROM agent_runs WHERE run_id=?", (run.run_id,)
                ).fetchone()[0]
            )
            effects = reopened.execute("SELECT receipt FROM synthetic_effects").fetchall()
        assert effects == [(receipt["receipt_id"],)]
        stored_step, stored_call = payload["steps"][0], payload["tool_calls"][0]
        assert (
            stored_step["status"] == stored_call["status"] == ("failed" if unknown else "completed")
        )
        assert stored_step["output"] == stored_call["output"]
        assert stored_step["finished_at"] == stored_call["finished_at"] != ""
        assert stored_step["attempt_count"] == stored_call["metadata"]["attempt_count"] == 1
        assert stored_step["output"] == expected_output
        if unknown:
            assert payload["metadata"]["non_retryable"] is True
            assert payload["metadata"]["recovery"]["state"] == "manual_reconciliation_required"
        return payload

    def verify_committed_effect(*, run, step, call, output, context):
        assert (step.tool_id, step.action) == ("synthetic", "write")
        assert context["run_id"] == run.run_id
        assert call.metadata["verification_contract"]["read_only"] is False
        assert output == original_receipt
        persisted = readback()
        report = persisted["tool_calls"][0]["metadata"]["verification"]
        assert report["status"] == "pending" and report["accepted"] is False
        verified.append(call.call_id)
        return {
            "status": "verified",
            "code": "synthetic_effect_read_back",
            "checks": [
                {
                    "check_id": "committed_effect",
                    "status": "passed",
                    "source": "separate_sqlite_connection",
                    "evidence": {"receipt_id": persisted["steps"][0]["output"]["receipt_id"]},
                }
            ],
        }

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        verify_committed_effect,
    )

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

    spec = ToolActionSpecV2(tool_id="synthetic", action="write", timeout_seconds=2)
    dependencies = SimpleNamespace(
        action_spec=lambda *_: spec,
        validate=lambda *_: ToolValidationResult(True, spec.tool_id, spec.action, spec=spec),
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
    node_outputs = {}
    expected_sinks = ["observation"] if unknown else ["artifacts", "observation"]
    raises = failed_sink in expected_sinks
    try:
        if raises:
            with pytest.raises(RuntimeError, match=f"synthetic {failed_sink} failure"):
                execution.execute_step(run, step, runtime_context={}, node_outputs=node_outputs)
        else:
            execution.execute_step(run, step, runtime_context={}, node_outputs=node_outputs)
        persisted = readback()
        assert observed == (
            ["artifacts"] if raises and failed_sink == "artifacts" else expected_sinks
        )
        assert verified == ([] if unknown else [run.tool_calls[0].call_id])
        assert receipt == original_receipt
        assert node_outputs == (
            {step.node_id: original_receipt} if not unknown and not raises else {}
        )
        events = [event["event_type"] for event in persisted["events"]]
        expected_events = ["tool.started"]
        if not (raises and failed_sink == "artifacts"):
            expected_events.append("verification.failed" if unknown else "verification.verified")
        if not raises:
            expected_events.append("tool.failed" if unknown else "tool.completed")
        assert events == expected_events
        report = persisted["tool_calls"][0]["metadata"]["verification"]
        assert report["status"] == (
            "failed" if unknown else "pending" if failed_sink == "artifacts" else "verified"
        )
        assert report["accepted"] is (not unknown and failed_sink != "artifacts")
        reopened_repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        assert reopened_repo.get(run.run_id).to_dict() == persisted
    finally:
        engine.dispose()
