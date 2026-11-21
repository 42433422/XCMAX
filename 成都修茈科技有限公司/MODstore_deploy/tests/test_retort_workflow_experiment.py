"""Real workflow generation, SQL/outbox and GrowthBook allocation with an isolated model."""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

import tests.test_retort_experiment_lifecycle as lifecycle_tests
from modstore_server import retort_evolution as evolution
from modstore_server import retort_experiment_runtime as runtime
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server import workflow_nl_graph as generator
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    User,
    Workflow,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_NL_MEASUREMENT,
    WORKFLOW_NL_RESOURCE,
)
from tests.test_retort_experiment_lifecycle import Clock, reapprove, start

experiment_run = lifecycle_tests.experiment_run


@pytest.fixture
def workflow_experiment(experiment_run, monkeypatch):
    run = experiment_run
    life = run["spec"]["lifecycle"]
    life.pop("employee_id")
    life.update(
        surface="workflow_nl_prompt",
        resource_id=WORKFLOW_NL_RESOURCE,
        measurement_scope=WORKFLOW_NL_MEASUREMENT,
        control_prompt=generator.SYSTEM_PROMPT,
        treatment_prompt=generator.SYSTEM_PROMPT + "\n检查每个节点的必填配置。",
    )
    lifecycle.freeze_experiment_policy(run["spec"])
    reapprove(run)
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda *_: ("test", "test-model", None),
    )
    monkeypatch.setattr(generator, "_catalog_lines", lambda *_: "")
    monkeypatch.setattr(generator, "_eskill_catalog_lines", lambda *_: "")
    run["workflows"], run["prompts"] = {}, []
    with get_session_factory()() as db:
        for user_id in [*run["users"], run["outsider"]]:
            workflow = Workflow(user_id=user_id, name="Original owned workflow")
            db.add(workflow)
            db.flush()
            run["workflows"][user_id] = workflow.id
        db.commit()
    run["graph"] = {
        "nodes": [
            {"temp_id": "start", "node_type": "start", "config": {}},
            {"temp_id": "end", "node_type": "end", "config": {}},
        ],
        "edges": [{"source_temp_id": "start", "target_temp_id": "end"}],
    }

    async def model(_db, user_id, _provider, _model, messages, **_kwargs):
        run["prompts"].append((user_id, messages[0]["content"]))
        if run.get("exception"):
            raise run["exception"]
        return run.get("model_result") or {"ok": True, "content": json_dumps(run["graph"])}

    monkeypatch.setattr(generator, "chat_dispatch_via_session", model)

    async def generate(user_id=None, *, workflow_id=None):
        user_id = user_id or run["users"][0]
        with get_session_factory()() as db:
            return await generator.apply_nl_workflow_graph(
                db,
                db.get(User, user_id),
                workflow_id=workflow_id or run["workflows"][user_id],
                brief="Private original workflow request",
                provider="test",
                model="test-model",
            )

    run["generate"] = generate
    return run


def observations(run, name="experiment.observed"):
    with get_session_factory()() as db:
        return [
            json_loads(row.payload_json, {})
            for row in db.query(OutboxEvent)
            .filter_by(aggregate_id=run["id"], event_name=name)
            .order_by(OutboxEvent.id)
        ]


@pytest.mark.asyncio
async def test_owned_generation_consumes_assignment_and_records_static_result(workflow_experiment):
    run = workflow_experiment
    start(run)
    assert observations(run, "experiment.exposed") == []
    for user_id in run["users"]:
        result = await run["generate"](user_id)
        assert result["ok"] is True and result["sandbox_ok"] is True
    recorded = observations(run)
    assert len(recorded) == len(run["users"])
    assert len(observations(run, "experiment.exposed")) == len(recorded)
    for observation, (user_id, prompt) in zip(recorded, run["prompts"], strict=True):
        assert observation["success"] is True
        assert observation["surface"] == "workflow_nl_prompt"
        assert observation["resource_id"] == WORKFLOW_NL_RESOURCE
        assert observation["measurement_scope"] == WORKFLOW_NL_MEASUREMENT
        assert observation["user_id"] == user_id
        assert observation["workflow_id"] == run["workflows"][user_id]
        assert observation["value_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        assert observation["duration_ms"] >= 0
        assert "Private original workflow request" not in json_dumps(observation)
        assert prompt not in json_dumps(observation)


@pytest.mark.asyncio
async def test_observation_commit_failure_rolls_back_graph_and_retry_creates_once(
    workflow_experiment, monkeypatch
):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from modstore_server.models import WorkflowEdge, WorkflowNode

    run = workflow_experiment
    start(run)
    original_record = runtime.record_observation
    original_commit = Session.commit
    failed = False

    def observe(*args, session=None, **kwargs):
        if session is not None:
            session.info["commit_observation"] = True
        return original_record(*args, session=session, **kwargs)

    def commit(session):
        nonlocal failed
        if session.info.pop("commit_observation", False) and not failed:
            failed = True
            raise OperationalError("COMMIT", {}, RuntimeError("observation storage unavailable"))
        return original_commit(session)

    monkeypatch.setattr(runtime, "record_observation", observe)
    monkeypatch.setattr(Session, "commit", commit)
    result = await run["generate"]()
    assert failed and result["ok"] is False
    workflow_id = run["workflows"][run["users"][0]]
    with get_session_factory()() as db:
        assert db.query(WorkflowNode).filter_by(workflow_id=workflow_id).count() == 0
        assert db.query(WorkflowEdge).filter_by(workflow_id=workflow_id).count() == 0
    assert [row["success"] for row in observations(run)] == [False]
    result = await run["generate"]()
    assert result["ok"] is True and result["sandbox_ok"] is True
    with get_session_factory()() as db:
        assert db.query(WorkflowNode).filter_by(workflow_id=workflow_id).count() == 2
        assert db.query(WorkflowEdge).filter_by(workflow_id=workflow_id).count() == 1
    assert [row["success"] for row in observations(run)] == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["model", "json", "static_validation", "exception", "cancel"])
async def test_generation_failure_cannot_be_counted_as_improvement(workflow_experiment, fault):
    run = workflow_experiment
    start(run)
    if fault == "model":
        run["model_result"] = {"ok": False, "error": "provider unavailable"}
    elif fault == "json":
        run["model_result"] = {"ok": True, "content": "not JSON"}
    elif fault == "static_validation":
        run["graph"]["nodes"].insert(
            1, {"temp_id": "broken", "node_type": "openapi_operation", "config": {}}
        )
        run["graph"]["edges"] = [
            {"source_temp_id": "start", "target_temp_id": "broken"},
            {"source_temp_id": "broken", "target_temp_id": "end"},
        ]
    else:
        run["exception"] = (
            RuntimeError("stream interrupted") if fault == "exception" else asyncio.CancelledError()
        )
    if run.get("exception"):
        with pytest.raises(type(run["exception"])):
            await run["generate"]()
    else:
        result = await run["generate"]()
        if fault == "static_validation":
            assert result["ok"] is True and result["sandbox_ok"] is False
            assert result["validation_errors"]
        else:
            assert result["ok"] is False
    assert len(run["prompts"]) == 1
    assert len(observations(run)) == 1
    assert observations(run)[0]["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    ["cohort", "ownership", "authority", "acceptance", "version", "lease", "tracking", "policy"],
)
async def test_actual_generator_enforces_original_experiment_boundaries(
    workflow_experiment, monkeypatch, fault
):
    run = workflow_experiment
    start(run)
    life = run["spec"]["lifecycle"]
    # Even a deployed candidate must fall back to the approved control when a gate closes.
    monkeypatch.setattr(generator, "SYSTEM_PROMPT", life["treatment_prompt"])
    if fault in {"authority", "acceptance", "policy"}:
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, run["id"])
            if fault == "authority":
                db.get(User, row.user_id).is_admin = False
            elif fault == "acceptance":
                snapshot = json_loads(row.snapshot_json, {})
                snapshot["approval"]["digest"] = "0" * 64
                row.snapshot_json = json_dumps(snapshot)
            else:
                effects = json_loads(row.effects_json, {})
                effects["customer_feedback"]["growthbook"]["lifecycle"]["coverage"] = 0.25
                row.effects_json = json_dumps(effects)
            db.commit()
    elif fault == "version":
        monkeypatch.setattr(runtime, "_identity", lambda: {"git_sha": "b" * 40})
    elif fault == "lease":
        Clock.value += timedelta(minutes=16)
    elif fault == "tracking":

        def unavailable(_assignment):
            raise RuntimeError("outbox unavailable")

        monkeypatch.setattr(runtime, "begin_observation", unavailable)
    if fault in {"tracking", "policy"}:
        with pytest.raises((RuntimeError, ValueError)):
            await run["generate"]()
        assert run["prompts"] == []
    elif fault == "ownership":
        result = await run["generate"](workflow_id=run["workflows"][run["outsider"]])
        assert result["ok"] is False and run["prompts"] == []
    else:
        await run["generate"](run["outsider"] if fault == "cohort" else None)
        assert run["prompts"][-1][1] == life["control_prompt"]
    assert observations(run) == []


@pytest.mark.asyncio
async def test_final_readback_promotes_and_withdrawal_changes_real_generator(workflow_experiment):
    run = workflow_experiment
    start(run)
    Clock.value += timedelta(hours=2)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    await run["generate"]()
    assert run["prompts"][-1][1] == run["spec"]["lifecycle"]["control_prompt"]
    assert run["advance"]()["decision"] == "promote"
    await run["generate"]()
    assert run["prompts"][-1][1] == run["spec"]["lifecycle"]["treatment_prompt"]
    run["advance"](reject=True)
    await run["generate"]()
    assert run["prompts"][-1][1] == run["spec"]["lifecycle"]["control_prompt"]
    assert run["advance"](reject=True)["decision"] == "rollback"


@pytest.mark.asyncio
async def test_failed_approval_closes_streamed_result_before_database_reuse(workflow_experiment):
    import sqlite3

    from modstore_server.models import get_engine

    run = workflow_experiment
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        effects["authorization"]["digest"] = "0" * 64
        row.effects_json = json_dumps(effects)
        # An early match in a larger stream leaves unread rows at the exception.
        for _ in range(101):
            db.add(
                RetortEvolutionRun(
                    id=str(uuid4()),
                    user_id=row.user_id,
                    protocol_json="{}",
                    created_at=row.created_at - timedelta(days=1),
                    effects_json=json_dumps({"note": WORKFLOW_NL_RESOURCE}),
                )
            )
        db.commit()
    with pytest.raises(ValueError, match="experiment_approval_mismatch") as error:
        await run["generate"]()
    # Retain the traceback as the API/logger would, while another connection
    # requests a write transaction. Session.close alone does not close a cursor.
    assert error.traceback
    with sqlite3.connect(get_engine().url.database, timeout=0) as connection:
        connection.execute("BEGIN EXCLUSIVE")
    assert run["prompts"] == []


@pytest.mark.parametrize(
    "patch",
    [
        {"surface": "unwired_surface"},
        {"resource_id": "arbitrary"},
        {"measurement_scope": "business_success"},
    ],
)
def test_freeze_never_approves_an_unwired_or_mislabelled_surface(workflow_experiment, patch):
    spec = deepcopy(workflow_experiment["spec"])
    spec["lifecycle"].update(patch)
    with pytest.raises(ValueError, match="invalid_feedback_experiment_lifecycle"):
        lifecycle.freeze_experiment_policy(spec)


def test_workflow_surface_reservation_is_serialized_without_colliding_with_employee(
    workflow_experiment, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    run = workflow_experiment
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "example/product")
    with get_session_factory()() as db:
        # Other tests seed approved rows directly; only this test exercises admission.
        db.query(RetortEvolutionRun).filter(
            RetortEvolutionRun.id != run["id"],
            RetortEvolutionRun.effects_json.contains('"workflow_nl_prompt"'),
        ).update({"status": "cancelled"})
        db.commit()
    request = {
        "title": "Workflow generation experiment",
        "goal": "Validate the approved generator prompt",
        "repository": "example/product",
        "source_sha": "a" * 40,
        "criterion_ids": ["shared-engine-B2"],
        "container_image": "example/test@sha256:" + "c" * 64,
        "checks": [
            {
                "id": "restore",
                "criterion_ids": ["shared-engine-B2"],
                "files": {"check.py": "b" * 64},
                "argv": ["python", "check.py"],
                "timeout_seconds": 10,
            }
        ],
    }
    source = {"growthbook": run["spec"]}
    with pytest.raises(ValueError, match="experiment_surface_already_reserved"):
        evolution.create_run(
            {**request, "request_id": str(uuid4())}, run["users"][0], customer_feedback=source
        )
    employee = deepcopy(source)
    employee["growthbook"]["lifecycle"].update(
        surface="employee_prompt", employee_id=WORKFLOW_NL_RESOURCE
    )
    assert evolution.create_run(
        {**request, "request_id": str(uuid4())}, run["users"][0], customer_feedback=employee
    )
    with get_session_factory()() as db:
        db.get(RetortEvolutionRun, run["id"]).status = "cancelled"
        db.commit()
    barrier = Barrier(2)

    def reserve(_index):
        barrier.wait(timeout=5)
        try:
            return evolution.create_run(
                {**request, "request_id": str(uuid4())}, run["users"][0], customer_feedback=source
            )
        except (ValueError, TimeoutError):
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(result is not None for result in pool.map(reserve, (0, 1))) == 1
