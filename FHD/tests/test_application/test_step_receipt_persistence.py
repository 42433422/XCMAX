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
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult
from app.db.db_base import Base


@pytest.mark.parametrize("failed_sink", [None, "artifacts", "observation"])
@pytest.mark.parametrize("result_state", ["completed", "unknown", "waiting_user"])
def test_receipt_is_durable_before_optional_sinks(tmp_path, monkeypatch, failed_sink, result_state):
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
    context = {"tenant_id": "7", "user_id": run.user_id, "actor_id": run.user_id}
    run.metadata["runtime_context"] = dict(context)
    unknown = result_state == "unknown"
    receipt = {"success": not unknown, "receipt_id": "original-committed-effect"}
    if unknown:
        receipt.update(outcome="unknown", retryable=False, reconciliation_required=True)
    elif result_state == "waiting_user":
        receipt.update(requires_user_decision=True, question="Continue with the proposed rows?")
    receipt["artifacts"] = [
        {"artifact_id": "original-table", "artifact_type": "table", "content": {"rows": []}}
    ]
    observed = []
    verified_calls = []
    dispatched = []

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
        assert stored_call["status"] == ("failed" if unknown else "completed")
        assert stored_step["status"] == ("failed" if unknown else result_state)
        if result_state == "waiting_user":
            assert payload["status"] == "waiting_user"
        assert stored_step["output"] == stored_call["output"]
        assert stored_step["finished_at"] == stored_call["finished_at"] != ""
        assert stored_step["attempt_count"] == stored_call["metadata"]["attempt_count"] == 1
        if unknown:
            assert {key: stored_step["output"][key] for key in receipt} == receipt
            assert stored_step["output"].get("error_code") != "tool_timeout_unknown"
            assert payload["metadata"]["non_retryable"] is True
            assert payload["metadata"]["recovery"]["state"] == "manual_reconciliation_required"
        else:
            assert stored_step["output"] == receipt
        return payload

    def execute(*args, **kwargs):
        dispatched.append(1)
        with sqlite3.connect(path) as business:
            business.execute(
                "INSERT INTO synthetic_effects(receipt) VALUES(?)",
                (receipt["receipt_id"],),
            )
        return receipt

    def verify_committed_effect(*, call, output, **kwargs):
        payload = readback()
        assert payload["tool_calls"][0]["metadata"]["verification"]["status"] == "pending"
        assert [event["event_type"] for event in payload["events"]] == ["tool.started"]
        with sqlite3.connect(path) as independent:
            row = independent.execute("SELECT id, receipt FROM synthetic_effects").fetchone()
        assert row == (1, output["receipt_id"])
        verified_calls.append(call.call_id)
        return {
            "status": "verified",
            "code": "committed_effect_matches",
            "checks": [
                {
                    "check_id": "original_effect",
                    "status": "passed",
                    "source": "separate_database_connection",
                    "evidence": {"row_id": row[0], "receipt_id": row[1]},
                }
            ],
        }

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        verify_committed_effect,
    )

    def sink(name):
        def apply(*args, **kwargs):
            readback()  # The receipt must already be visible to another connection.
            observed.append(name)
            if failed_sink == name:
                raise RuntimeError(f"synthetic {name} failure after commit")
            return {"observation_id": "synthetic-observation"}

        return apply

    spec = ToolActionSpecV2(
        tool_id=step.tool_id,
        action=step.action,
        timeout_seconds=2,
        output_schema={
            "type": "object",
            "required": ["success", "receipt_id"],
            "properties": {"success": {"type": "boolean"}, "receipt_id": {"type": "string"}},
        },
    )
    dependencies = SimpleNamespace(
        action_spec=lambda *_: spec,
        validate=lambda *_: ToolValidationResult(
            ok=True, tool_id=spec.tool_id, action=spec.action, spec=spec
        ),
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
        sink_reached = failed_sink and not (unknown and failed_sink == "artifacts")
        if sink_reached:
            with pytest.raises(RuntimeError, match=f"synthetic {failed_sink} failure"):
                execution.execute_step(run, step, runtime_context=context, node_outputs={})
        else:
            execution.execute_step(run, step, runtime_context=context, node_outputs={})
        persisted = readback()
        expected_sinks = ["observation"] if unknown else ["artifacts", "observation"]
        if not unknown and failed_sink == "artifacts":
            expected_sinks = ["artifacts"]
        assert observed == expected_sinks
        assert dispatched == [1]
        assert verified_calls == ([] if unknown else [run.tool_calls[0].call_id])
        events = [event["event_type"] for event in persisted["events"]]
        expected_events = ["tool.started"]
        if unknown or failed_sink != "artifacts":
            expected_events.append("verification.failed" if unknown else "verification.verified")
        if not sink_reached:
            expected_events.append("tool.failed" if unknown else "tool.completed")
        assert events == expected_events
        reopened_repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        assert reopened_repo.get(run.run_id).to_dict() == persisted
    finally:
        engine.dispose()
