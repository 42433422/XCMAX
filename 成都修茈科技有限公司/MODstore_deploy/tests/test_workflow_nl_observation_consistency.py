"""Real workflow/Skill transactions stay consistent with experimental observations."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from modstore_server import auth_service, retort_experiment_runtime
from modstore_server.customer_service_tools import json_loads
from modstore_server.eventing import db_outbox
from modstore_server.eventing.contracts import WORKFLOW_SANDBOX_COMPLETED
from modstore_server.models import (
    ESkill,
    ESkillVersion,
    OutboxEvent,
    User,
    WorkflowEdge,
    WorkflowNode,
    get_session_factory,
)
from tests import test_retort_workflow_experiment as experiment_fixtures
from tests.test_retort_experiment_lifecycle import start
from tests.test_retort_workflow_experiment import observations

experiment_run = experiment_fixtures.experiment_run
workflow_experiment = experiment_fixtures.workflow_experiment


@pytest.fixture
def workflow_with_skill(workflow_experiment):
    run = workflow_experiment
    start(run)
    run["skill_name"] = f"Observed skill {run['id']}"
    run["graph"] = {
        "skill_blueprints": [
            {
                "temp_skill_id": "observed_skill",
                "name": run["skill_name"],
                "domain": "formatting",
                "static_logic": {
                    "type": "template_transform",
                    "template": "Value: ${value}",
                    "output_var": "formatted",
                },
            }
        ],
        "workflow": {
            "nodes": [
                {"temp_id": "start", "node_type": "start", "config": {}},
                {
                    "temp_id": "format",
                    "node_type": "eskill",
                    "config": {"temp_skill_id": "observed_skill"},
                },
                {"temp_id": "end", "node_type": "end", "config": {}},
            ],
            "edges": [
                {"source_temp_id": "start", "target_temp_id": "format"},
                {"source_temp_id": "format", "target_temp_id": "end"},
            ],
        },
    }
    return run


def persisted_graph(run):
    """Read through a separate connection, not the generating session's identity map."""
    with get_session_factory()() as db:
        workflow_id = run["workflows"][run["users"][0]]
        skill = db.query(ESkill).filter_by(name=run["skill_name"]).first()
        return {
            "nodes": [row.id for row in db.query(WorkflowNode).filter_by(workflow_id=workflow_id)],
            "edges": [row.id for row in db.query(WorkflowEdge).filter_by(workflow_id=workflow_id)],
            "skill": skill.id if skill else None,
            "versions": (
                [row.id for row in db.query(ESkillVersion).filter_by(eskill_id=skill.id)]
                if skill
                else []
            ),
        }


@pytest.mark.asyncio
async def test_observation_write_failure_cannot_leave_saved_graph_reported_failed(
    workflow_with_skill, monkeypatch
):
    run = workflow_with_skill
    original = db_outbox.enqueue

    def unavailable(session, event_name, *args, **kwargs):
        if event_name == "experiment.observed":
            raise OperationalError("insert observation", {}, RuntimeError("outbox unavailable"))
        return original(session, event_name, *args, **kwargs)

    monkeypatch.setattr(db_outbox, "enqueue", unavailable)
    result, escaped = {}, None
    try:
        result = await run["generate"]()
    except OperationalError as exc:
        escaped = exc
    # Previously the finally block raised after all four tables were committed.
    assert persisted_graph(run) == {
        "nodes": [],
        "edges": [],
        "skill": None,
        "versions": [],
    }
    assert escaped is None
    assert result["ok"] is False
    assert result["error_code"] == "workflow_observation_commit_failed"
    assert result["experiment_observation"]["status"] == "not_recorded"
    assert observations(run) == []
    assert len(observations(run, "experiment.exposed")) == 1

    monkeypatch.setattr(db_outbox, "enqueue", original)
    retried = await run["generate"]()
    assert retried["ok"] is True and retried["sandbox_ok"] is True
    graph = persisted_graph(run)
    assert len(graph["nodes"]) == 3 and len(graph["edges"]) == 2
    assert graph["skill"] and len(graph["versions"]) == 1
    assert len(observations(run)) == 1


@pytest.mark.asyncio
async def test_committed_graph_survives_original_outbox_retry_without_regeneration(
    workflow_with_skill,
):
    run = workflow_with_skill
    result = await run["generate"]()
    assert result["ok"] is True and result["sandbox_ok"] is True
    graph = persisted_graph(run)
    with get_session_factory()() as db:
        row = (
            db.query(OutboxEvent)
            .filter_by(aggregate_id=run["id"], event_name="experiment.observed")
            .one()
        )
        event_id = row.event_id
        payload = json_loads(row.payload_json, {})
        assert row.status == "pending"
        assert payload["measurement_scope"] == "workflow_generation_static_validation"
        assert payload["success"] is True
        assert payload["workflow_id"] == run["workflows"][run["users"][0]]
        sandbox = (
            db.query(OutboxEvent)
            .filter_by(
                aggregate_id=str(payload["workflow_id"]),
                event_name=WORKFLOW_SANDBOX_COMPLETED,
            )
            .one()
        )
        assert sandbox.producer == "workflow"
        assert sandbox.idempotency_key == sandbox.event_id
        assert json_loads(sandbox.payload_json, {})["validate_only"] is True
    attempts = []

    def failing_delivery(envelope):
        if envelope["id"] == event_id:
            attempts.append(envelope["id"])
            return {"ok": False, "message": "observation sink temporarily unavailable"}
        return {"ok": True}

    assert db_outbox.drain(failing_delivery, publish_to_neuro_bus=False)["failed"] == 1
    with get_session_factory()() as db:
        row = db.query(OutboxEvent).filter_by(event_id=event_id).one()
        assert row.status == "pending" and row.attempts == 1
    assert persisted_graph(run) == graph
    assert result["experiment_observation"]["status"] == "queued"
    assert result["experiment_observation"]["event_id"] == event_id

    def accepted_delivery(envelope):
        if envelope["id"] == event_id:
            attempts.append(envelope["id"])
            assert envelope["data"] == payload
        return {"ok": True}

    db_outbox.drain(accepted_delivery, publish_to_neuro_bus=False)
    for _ in range(3):
        assert persisted_graph(run) == graph
    with get_session_factory()() as db:
        row = db.query(OutboxEvent).filter_by(event_id=event_id).one()
        assert row.status == "dispatched"
    assert attempts == [event_id, event_id]
    assert len(run["prompts"]) == len(observations(run)) == 1


@pytest.mark.asyncio
async def test_final_commit_failure_rolls_back_graph_skills_and_observation(
    workflow_with_skill, monkeypatch
):
    run = workflow_with_skill
    original = retort_experiment_runtime.record_observation

    def arm_commit_failure(assignment, **kwargs):
        original(assignment, **kwargs)
        kwargs["session"].info["fail_workflow_commit"] = True

    def fail_commit(session):
        if not session.in_nested_transaction() and session.info.pop("fail_workflow_commit", False):
            raise OperationalError("commit workflow", {}, RuntimeError("commit unavailable"))

    monkeypatch.setattr(retort_experiment_runtime, "record_observation", arm_commit_failure)
    event.listen(Session, "before_commit", fail_commit)
    try:
        result = await run["generate"]()
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert result["ok"] is False
    assert result["experiment_observation"] == {"status": "not_recorded"}
    assert persisted_graph(run) == {
        "nodes": [],
        "edges": [],
        "skill": None,
        "versions": [],
    }
    assert observations(run) == []
    assert len(observations(run, "experiment.exposed")) == 1


def test_management_workflow_http_status_matches_saved_state_and_polling_is_read_only(
    workflow_with_skill, client, monkeypatch, tmp_path
):
    run = workflow_with_skill
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))

    async def configured_model(*_args, **_kwargs):
        return "test", "test-model", None

    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model_auto",
        configured_model,
    )
    with get_session_factory()() as db:
        user = db.get(User, run["users"][0])
        token = auth_service.create_access_token(user.id, user.username, is_admin=True)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "target_type": "workflow",
        "target_id": str(run["workflows"][run["users"][0]]),
        "brief": "Create the original owned workflow and its formatting skill",
        "provider": "test",
        "model": "test-model",
    }
    original = db_outbox.enqueue

    def unavailable(session, event_name, *args, **kwargs):
        if event_name == "experiment.observed":
            raise OperationalError("insert observation", {}, RuntimeError("outbox unavailable"))
        return original(session, event_name, *args, **kwargs)

    def start_and_read():
        response = client.post("/api/agent/butler/orchestrate", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        for _ in range(20):
            snapshot = client.get(f"/api/workbench/sessions/{session_id}", headers=headers)
            assert snapshot.status_code == 200, snapshot.text
            if snapshot.json()["status"] != "running":
                return session_id, snapshot.json()
        pytest.fail("the bounded local workflow did not complete")

    monkeypatch.setattr(db_outbox, "enqueue", unavailable)
    _, failed = start_and_read()
    assert failed["status"] == "error"
    assert "工作流未保存" in failed["error"]
    assert persisted_graph(run) == {
        "nodes": [],
        "edges": [],
        "skill": None,
        "versions": [],
    }
    assert observations(run) == []

    monkeypatch.setattr(db_outbox, "enqueue", original)
    session_id, completed = start_and_read()
    assert completed["status"] == "done"
    result = completed["artifact"]["nl_result"]
    assert result["ok"] is True and result["sandbox_ok"] is True
    assert result["experiment_observation"]["status"] == "queued"
    graph = persisted_graph(run)
    assert len(graph["nodes"]) == 3 and len(graph["edges"]) == 2
    assert graph["skill"] and len(graph["versions"]) == 1
    for _ in range(3):
        response = client.get(f"/api/workbench/sessions/{session_id}", headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "done"
        assert persisted_graph(run) == graph
    assert len(run["prompts"]) == 2
    assert len(observations(run)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("observation_fails", [False, True])
async def test_cancellation_keeps_original_exception_and_no_graph(
    workflow_with_skill, monkeypatch, observation_fails
):
    run = workflow_with_skill
    run["exception"] = asyncio.CancelledError("original cancellation")
    original = db_outbox.enqueue

    def enqueue(session, event_name, *args, **kwargs):
        if observation_fails and event_name == "experiment.observed":
            raise OperationalError("insert observation", {}, RuntimeError("outbox unavailable"))
        return original(session, event_name, *args, **kwargs)

    monkeypatch.setattr(db_outbox, "enqueue", enqueue)
    with pytest.raises(asyncio.CancelledError, match="original cancellation") as caught:
        await run["generate"]()
    assert persisted_graph(run) == {
        "nodes": [],
        "edges": [],
        "skill": None,
        "versions": [],
    }
    assert [row["success"] for row in observations(run)] == ([] if observation_fails else [False])
    if observation_fails:
        assert "experiment_observation_not_recorded" in caught.value.__notes__
