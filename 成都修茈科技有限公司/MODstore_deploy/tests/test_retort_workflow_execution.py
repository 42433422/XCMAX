"""Actual generated graphs and API/trigger terminals, with external GrowthBook contract data."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from growthbook import Experiment, GrowthBook
from sqlalchemy import create_engine, text

from modstore_server import retort_experiment_runtime as runtime
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server import workflow_engine, workflow_event_runner
from modstore_server.api.deps import _get_current_user
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowSandboxRun,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import WORKFLOW_EXECUTION_MEASUREMENT
from modstore_server.retort_workflow_metrics import execution_queries
from modstore_server.workflow_api import execution, sandbox
from modstore_server.workflow_execution_feedback import (
    GRAPH_GUARD_FAILED,
    START_EVENT,
    complete_execution_feedback,
)
from tests import test_retort_experiment_lifecycle as lifecycle_tests
from tests import test_retort_workflow_experiment as generation_tests
from tests.test_retort_experiment_lifecycle import Clock, reapprove, start
from tests.test_retort_workflow_experiment import observations

experiment_run = lifecycle_tests.experiment_run
workflow_experiment = generation_tests.workflow_experiment


class ExecutionAPI(lifecycle_tests.GrowthBookAPI):
    """The fixed 5.2 REST shapes; statistical values are synthetic contract fixtures."""

    def __init__(self):
        super().__init__()
        queries = execution_queries()
        self.datasource = {
            "id": "warehouse",
            "type": "postgres",
            "assignmentQueries": [
                {
                    "id": "actual-outbox-exposures",
                    "identifierTypes": ["user_id"],
                    "sql": queries["assignment"],
                    "includesNameColumns": False,
                    "dimensionColumns": [],
                }
            ],
        }
        self.metrics = {
            name: {
                "id": name,
                "datasourceId": "warehouse",
                "type": "binomial",
                "projects": ["prod"],
                "archived": False,
                "behavior": {"goal": direction, "windowSettings": {"type": "none"}},
                "sql": {
                    "identifierTypes": ["user_id"],
                    "userAggregationSQL": "SUM(value)",
                    "conversionSQL": queries[name],
                },
            }
            for name, direction in (("success", "increase"), ("failure", "decrease"))
        }

    def handle(self, request):
        if request.url.path.endswith("/data-sources/warehouse"):
            return httpx.Response(200, json={"dataSource": self.datasource})
        if "/metrics/" in request.url.path:
            return httpx.Response(
                200, json={"metric": self.metrics[request.url.path.rsplit("/", 1)[1]]}
            )
        response = super().handle(request)
        if self.experiment:
            self.experiment["settings"]["guardrails"] = [{"metricId": "failure"}]
        payload = response.json()
        if "experiment" in payload:
            payload["experiment"] = self.experiment
        if "result" in payload:
            metrics = payload["result"]["results"][0]["metrics"]
            failure = deepcopy(metrics[0])
            failure["metricId"] = "failure"
            failure["variations"][1]["analyses"][0].update(
                ciLow=-0.18, percentChange=-0.1, ciHigh=-0.02
            )
            metrics.append(failure)
        return httpx.Response(response.status_code, json=payload)


@pytest.fixture
def execution_experiment(workflow_experiment, monkeypatch):
    run = workflow_experiment
    life = run["spec"]["lifecycle"]
    life.update(
        measurement_scope=WORKFLOW_EXECUTION_MEASUREMENT,
        execution_outcomes={
            "source": "modstore_event_outbox_postgres_v1",
            "success_metric_id": "success",
            "failure_metric_id": "failure",
            "maximum_treatment_failures": 2,
        },
    )
    run["spec"]["guardrails"] = [{"metric": "failure", "direction": "decrease"}]
    # Keep the real SDK and ensure this fixture contains both randomized arms.
    arms = {}
    with get_session_factory()() as db:
        index = 0
        while len(arms) < 2:
            if index == len(run["users"]):
                user = User(username=uuid4().hex, password_hash="test-only")
                db.add(user)
                db.flush()
                workflow = Workflow(user_id=user.id, name="Additional approved owner")
                db.add(workflow)
                db.flush()
                run["users"].append(user.id)
                run["workflows"][user.id] = workflow.id
            user_id = run["users"][index]
            sdk = GrowthBook(attributes={"id": str(user_id)})
            try:
                key = f"xcagi-retort-{run['id']}"
                result = sdk.run(Experiment(key=key, seed=key, hashVersion=2, variations=[0, 1]))
                arms[str(result.variationId)] = user_id
            finally:
                sdk.destroy()
            index += 1
            assert index < 10000
        db.commit()
    run["arms"] = arms
    run["spec"] = lifecycle.freeze_experiment_policy(run["spec"])
    reapprove(run)
    run["api"] = api = ExecutionAPI()
    monkeypatch.setattr(lifecycle, "growthbook_client", api.client)
    monkeypatch.setattr(execution, "require_llm_credit", lambda *_: None)
    monkeypatch.setattr(workflow_event_runner, "require_llm_credit", lambda *_: None)
    monkeypatch.setattr(workflow_event_runner, "consume_llm_credit", lambda *_: None)
    monkeypatch.setattr("modstore_server.webhook_dispatcher.publish_event", lambda *_a, **_k: None)

    async def bill(*_args, **_kwargs):
        return None

    monkeypatch.setattr("modstore_server.llm_billing.bill_internal_llm_floor", bill)

    def database():
        with get_session_factory()() as db:
            yield db

    app = FastAPI()
    app.include_router(execution.router, prefix="/workflow")
    app.include_router(sandbox.router, prefix="/workflow")
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[_get_current_user] = lambda: SimpleNamespace(id=run["actor"])
    with TestClient(app) as client:

        def execute(user_id, inputs=None):
            run["actor"] = user_id
            return client.post(
                f"/workflow/{run['workflows'][user_id]}/execute", json={"input_data": inputs or {}}
            )

        def sandbox_run(user_id, inputs=None, **modes):
            run["actor"] = user_id
            return client.post(
                f"/workflow/{run['workflows'][user_id]}/sandbox-run",
                json={"input_data": inputs or {}, "mock_employees": False, **modes},
            )

        run["execute"] = execute
        run["sandbox"] = sandbox_run
        yield run


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["api", "trigger", "sandbox"])
@pytest.mark.parametrize("succeeds", [True, False])
async def test_only_real_terminal_receipts_enter_execution_metrics(
    execution_experiment, monkeypatch, entry, succeeds
):
    run = execution_experiment
    if not succeeds:
        run["graph"]["edges"][0]["condition"] = "ready == True"
    start(run)
    user_id = run["arms"]["1"]
    generated = await run["generate"](user_id)
    assert generated["ok"] and generated["sandbox_ok"]
    assert len(observations(run, "experiment.generation_observed")) == 1
    observed = observations(run, "experiment.generation_observed")[0]
    assert generated["experiment_observation"] == {
        "status": "queued",
        "event_id": f"experiment.generation_observed:{observed['observation_id']}",
    }
    assert observations(run) == observations(run, "experiment.exposed") == []
    inputs = {"ready": succeeds, "private_value": "customer-input-stays-private"}
    if entry == "sandbox":

        def duplicate_charge(*_args):
            pytest.fail("real sandbox must preserve its existing caller's billing boundary")

        monkeypatch.setattr(workflow_event_runner, "require_llm_credit", duplicate_charge)
        monkeypatch.setattr(workflow_event_runner, "consume_llm_credit", duplicate_charge)
    if entry == "api":
        response = run["execute"](user_id, inputs)
        assert response.status_code == (200 if succeeds else 500), response.text
    elif entry == "sandbox":
        response = run["sandbox"](user_id, inputs)
        assert response.status_code == (200 if succeeds else 400), response.text
        if succeeds:
            assert response.json()["output"]["ready"] is True
            assert [step["node_type"] for step in response.json()["steps"]] == ["start", "end"]
    elif succeeds:
        assert workflow_event_runner.run_workflow_for_trigger(
            workflow_id=run["workflows"][user_id], user_id=user_id, input_data=inputs
        )["ok"]
    else:
        with pytest.raises(ValueError, match="did not reach end"):
            workflow_event_runner.run_workflow_for_trigger(
                workflow_id=run["workflows"][user_id], user_id=user_id, input_data=inputs
            )
    observed = observations(run)
    assert len(observed) == len(observations(run, "experiment.exposed")) == 1
    assert observed[0]["success"] is succeeds
    assert observed[0]["measurement_scope"] == WORKFLOW_EXECUTION_MEASUREMENT
    assert observed[0]["variation_id"] == "1"
    with get_session_factory()() as db:
        receipt = db.get(WorkflowExecution, observed[0]["execution_id"])
        assert receipt.status == ("completed" if succeeds else "failed")
        assert json_loads(receipt.input_data, {}) == inputs
        assert receipt.completed_at is not None
        if entry == "sandbox":
            report = json_loads(receipt.output_data, {})
            assert report["ok"] is succeeds
            assert report["steps"]
        if not succeeds:
            assert "did not reach end" in receipt.error_message
        complete_execution_feedback(db, receipt)
        db.commit()
    assert len(observations(run)) == 1
    assert "customer-input" not in json_dumps(
        observations(run) + observations(run, "experiment.exposed")
    )


@pytest.mark.parametrize("fault", ["static_sql", "source", "goal", "window", "mapping"])
def test_execution_metric_definitions_cannot_be_replaced_by_generation_success(
    execution_experiment, fault
):
    run = execution_experiment
    if fault == "static_sql":
        run["api"].metrics["success"]["sql"]["conversionSQL"] = "SELECT * FROM generation_success"
    elif fault == "source":
        run["api"].metrics["failure"]["datasourceId"] = "other-warehouse"
    elif fault == "goal":
        run["api"].metrics["failure"]["behavior"]["goal"] = "increase"
    elif fault == "window":
        run["api"].metrics["success"]["behavior"]["windowSettings"]["type"] = "conversion"
    else:
        run["api"].datasource["assignmentQueries"][0]["columnMapping"] = {"userId": "unrelated"}
    assert run["advance"]()["status"] == "experiment_blocked"
    assert run["api"].experiment is None


def invalidate(run, fault):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        if fault == "authority":
            db.get(User, row.user_id).is_admin = False
        elif fault == "acceptance":
            state = json_loads(row.snapshot_json, {})
            state["approval"]["digest"] = "0" * 64
            row.snapshot_json = json_dumps(state)
        elif fault == "owner":
            db.get(Workflow, run["workflows"][run["arms"]["1"]]).user_id = run["outsider"]
        elif fault == "graph":
            edge = (
                db.query(WorkflowEdge)
                .filter_by(workflow_id=run["workflows"][run["arms"]["1"]])
                .one()
            )
            edge.condition = "ready == True"
        elif fault == "cohort":
            spec = deepcopy(run["spec"])
            spec["lifecycle"]["cohort_user_ids"].remove(run["arms"]["1"])
            run["spec"] = spec
        db.commit()
    if fault == "cohort":
        reapprove(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["authority", "acceptance", "version", "lease"])
@pytest.mark.parametrize("entry", ["execute", "sandbox"])
async def test_persisted_treatment_graph_cannot_run_after_its_approval_or_version_expires(
    execution_experiment, monkeypatch, fault, entry
):
    run = execution_experiment
    start(run)
    await run["generate"](run["arms"]["1"])
    if fault == "version":
        monkeypatch.setattr(runtime, "_identity", lambda: {"git_sha": "b" * 40})
    elif fault == "lease":
        Clock.value += timedelta(minutes=16)
    else:
        invalidate(run, fault)

    def executed_after_withdrawal(*_args, **_kwargs):
        pytest.fail("withdrawn treatment must be refused before any node executes")

    monkeypatch.setattr(workflow_engine.workflow_engine, "_execute_node", executed_after_withdrawal)
    response = run[entry](run["arms"]["1"])
    assert response.status_code == (400 if entry == "sandbox" else 500), response.text
    detail = response.json()["detail"]
    assert (detail["errors"][0] if entry == "sandbox" else detail) == (
        "workflow_experiment_graph_no_longer_approved"
    )
    assert observations(run) == []
    assert len(observations(run, "experiment.execution_archived")) == 1
    with get_session_factory()() as db:
        receipt = (
            db.query(WorkflowExecution)
            .filter_by(workflow_id=run["workflows"][run["arms"]["1"]])
            .one()
        )
        assert json_loads(receipt.output_data, {}) == {}
        started = db.query(OutboxEvent).filter_by(event_id=f"{START_EVENT}:{receipt.id}").one()
        assert json_loads(started.payload_json, {})["execution_allowed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mock_employees,validate_only", [(True, False), (True, True), (False, True)]
)
async def test_mock_and_static_sandbox_keep_their_semantics_without_execution_receipts(
    execution_experiment, monkeypatch, mock_employees, validate_only
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    invalidate(run, "authority")

    def not_actual_execution(*_args, **_kwargs):
        pytest.fail("mock/static validation must not enter actual execution or billing")

    monkeypatch.setattr(workflow_event_runner, "run_recorded_workflow", not_actual_execution)
    monkeypatch.setattr(workflow_event_runner, "require_llm_credit", not_actual_execution)
    monkeypatch.setattr(workflow_event_runner, "consume_llm_credit", not_actual_execution)
    response = run["sandbox"](user_id, mock_employees=mock_employees, validate_only=validate_only)
    assert response.status_code == 200 and response.json()["ok"] is True, response.text
    assert response.json()["validate_only"] is validate_only
    assert ("sandbox_run_id" in response.json()) is not validate_only
    assert bool(response.json()["steps"]) is not validate_only
    assert observations(run) == observations(run, "experiment.exposed") == []
    with get_session_factory()() as db:
        assert (
            db.query(WorkflowExecution).filter_by(workflow_id=run["workflows"][user_id]).count()
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["authority", "acceptance", "owner", "graph", "version", "late"])
async def test_late_or_changed_execution_is_archived_without_promoting(
    execution_experiment, monkeypatch, fault
):
    run = execution_experiment
    start(run)
    await run["generate"](run["arms"]["1"])
    real_engine = workflow_engine.execute_workflow

    def completing(*args, **kwargs):
        result = real_engine(*args, **kwargs)
        if fault == "version":
            monkeypatch.setattr(runtime, "_identity", lambda: {"git_sha": "b" * 40})
        elif fault == "late":
            Clock.value += timedelta(hours=2)
        else:
            invalidate(run, fault)
        return result

    monkeypatch.setattr(workflow_engine, "execute_workflow", completing)
    response = run["execute"](run["arms"]["1"])
    assert response.status_code == 200, response.text
    assert observations(run) == []
    archived = observations(run, "experiment.execution_archived")
    assert len(archived) == 1 and archived[0]["success"] is True
    assert archived[0]["execution_id"] == response.json()["id"]


@pytest.mark.asyncio
async def test_real_failures_stop_existing_treatment_graph_and_drive_remote_withdrawal(
    execution_experiment,
):
    run = execution_experiment
    run["graph"]["edges"][0]["condition"] = "ready == True"
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    for _ in range(2):
        response = run["execute"](user_id, {"ready": False})
        assert response.status_code == 500
        assert response.json()["detail"] == "工作流执行失败，请查看执行记录"
    with get_session_factory()() as db:
        failed = db.query(WorkflowExecution).filter_by(workflow_id=run["workflows"][user_id]).all()
        assert len(failed) == 2
        assert all(
            row.status == "failed" and "did not reach end" in row.error_message for row in failed
        )
    assert len(observations(run)) == 2
    response = run["execute"](user_id, {"ready": True})
    assert response.json()["detail"] == "workflow_experiment_graph_no_longer_approved"
    assert len(observations(run)) == 2
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "rollback"
    await run["generate"](user_id)
    assert run["prompts"][-1][1] == run["spec"]["lifecycle"]["control_prompt"]


@pytest.mark.asyncio
async def test_promoted_graph_still_requires_current_approval_but_does_not_reenter_measurement(
    execution_experiment,
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    Clock.value += timedelta(hours=2)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    assert run["execute"](user_id).status_code == 200
    assert observations(run) == []
    invalidate(run, "authority")
    assert (
        run["execute"](user_id).json()["detail"] == "workflow_experiment_graph_no_longer_approved"
    )


@pytest.mark.asyncio
async def test_unrelated_sandbox_history_does_not_hide_a_withdrawn_graph(execution_experiment):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    with get_session_factory()() as db:
        original = (
            db.query(WorkflowSandboxRun)
            .filter_by(workflow_id=run["workflows"][user_id])
            .order_by(WorkflowSandboxRun.id.desc())
            .first()
        )
        for _ in range(101):
            db.add(
                WorkflowSandboxRun(
                    workflow_id=original.workflow_id,
                    user_id=user_id,
                    graph_fingerprint=original.graph_fingerprint,
                    validate_only=True,
                    ok=True,
                    report_json=json_dumps(
                        {"phase": "other", "note": "natural_language_generation"}
                    ),
                )
            )
        db.commit()
    invalidate(run, "authority")
    response = run["execute"](user_id)
    assert response.json()["detail"] == "workflow_experiment_graph_no_longer_approved"
    assert len(observations(run, "experiment.execution_archived")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "sandbox"])
async def test_a_different_graph_loaded_between_start_and_execution_never_runs(
    execution_experiment, monkeypatch, entry
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    target = workflow_engine.workflow_engine if entry == "sandbox" else workflow_engine
    method = "run_sandbox" if entry == "sandbox" else "execute_workflow"
    real_engine = getattr(target, method)

    def racing(*args, **kwargs):
        invalidate(run, "graph")
        try:
            return real_engine(*args, **kwargs)
        finally:
            with get_session_factory()() as db:
                db.query(WorkflowEdge).filter_by(workflow_id=run["workflows"][user_id]).update(
                    {"condition": ""}
                )
                db.commit()

    monkeypatch.setattr(target, method, racing)
    response = run[entry](user_id)
    assert response.status_code == (400 if entry == "sandbox" else 500), response.text
    detail = response.json()["detail"]
    assert (detail["errors"][0] if entry == "sandbox" else detail) == GRAPH_GUARD_FAILED
    assert observations(run) == []
    with get_session_factory()() as db:
        receipt = db.query(WorkflowExecution).filter_by(workflow_id=run["workflows"][user_id]).one()
        started = db.query(OutboxEvent).filter_by(event_id=f"{START_EVENT}:{receipt.id}").one()
        assert json_loads(receipt.output_data, {}) == {}
        assert json_loads(started.payload_json, {})["execution_allowed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "sandbox"])
async def test_session_expiration_cannot_replace_the_graph_already_admitted(
    execution_experiment, monkeypatch, entry
):
    run = execution_experiment
    run["graph"]["nodes"].insert(
        1,
        {
            "temp_id": "value",
            "node_type": "variable_set",
            "config": {"name": "approved", "value": "original"},
        },
    )
    run["graph"]["edges"] = [
        {"source_temp_id": "start", "target_temp_id": "value"},
        {"source_temp_id": "value", "target_temp_id": "end"},
    ]
    start(run)
    user_id = run["arms"]["1"]
    generated = await run["generate"](user_id)
    assert generated["ok"] and generated["sandbox_ok"]
    engine = workflow_engine.workflow_engine
    original = engine._execute_node

    def editing(node, data, config, **kwargs):
        if node.node_type == "start":
            # This simulates a node's ordinary commit plus a concurrent editor.
            kwargs["session"].commit()
            with get_session_factory()() as db:
                changed = (
                    db.query(WorkflowNode)
                    .filter_by(workflow_id=run["workflows"][user_id], node_type="variable_set")
                    .one()
                )
                changed.config = json_dumps({"name": "approved", "value": "edited"})
                db.commit()
            kwargs["session"].expire_all()
        return original(node, data, config, **kwargs)

    monkeypatch.setattr(engine, "_execute_node", editing)
    response = run[entry](user_id)
    assert response.status_code == 200, response.text
    output_key = "output" if entry == "sandbox" else "output_data"
    assert response.json()[output_key]["approved"] == "original"
    if entry == "sandbox":
        assert response.json()["sandbox_status"]["status"] == "stale"
        assert response.json()["sandbox_passed_for_current_graph"] is False
    assert (
        observations(run) == []
    )  # The persisted graph has changed; the terminal remains archival.


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)
async def test_postgres_metric_queries_consume_actual_execution_outbox_only(execution_experiment):
    run = execution_experiment
    run["graph"]["edges"][0]["condition"] = "ready == True"
    start(run)
    user_id = run["arms"]["1"]
    await run["generate"](user_id)
    assert run["execute"](user_id, {"ready": False}).status_code == 500
    assert run["execute"](user_id, {"ready": True}).status_code == 200
    with get_session_factory()() as db:
        events = [
            {"event_name": row.event_name, "payload_json": row.payload_json}
            for row in db.query(OutboxEvent).filter_by(aggregate_id=run["id"])
        ]
    static_success = {
        **observations(run)[0],
        "measurement_scope": "workflow_generation_static_validation",
        "success": True,
    }
    events.append({"event_name": "experiment.observed", "payload_json": json_dumps(static_success)})
    engine = create_engine(os.environ["RETORT_TEST_POSTGRES_DSN"])
    try:
        with engine.begin() as connection:
            # A connection-local temporary table cannot touch production or
            # another test's outbox, and disappears when this connection closes.
            connection.execute(
                text(
                    "CREATE TEMP TABLE event_outbox (event_name TEXT, payload_json TEXT) ON COMMIT DROP"
                )
            )
            connection.execute(
                text("INSERT INTO event_outbox VALUES (:event_name, :payload_json)"), events
            )
            rows = {
                key: connection.execute(text(sql)).mappings().all()
                for key, sql in execution_queries().items()
            }
            assert all(len(value) == 1 for value in rows.values())
            assert {row["user_id"] for value in rows.values() for row in value} == {
                f"{user_id}:{run['id']}"
            }
            assert rows["assignment"][0]["variation_id"] == "1"
            assert rows["assignment"][0]["experiment_id"] == f"xcagi-retort-{run['id']}"
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["customer_tool", "service_port", "sub_workflow"])
async def test_existing_direct_consumers_record_success_and_cannot_bypass_withdrawal(
    execution_experiment, monkeypatch, consumer
):
    from modstore_server.customer_service_tools import _execute_workflow
    from modstore_server.services.workflow import InProcessWorkflowEngineClient

    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    await run["generate"](user_id)

    def duplicate_charge(*_args):
        pytest.fail("recorded execution must not add another quota or billing layer")

    monkeypatch.setattr(workflow_event_runner, "require_llm_credit", duplicate_charge)
    monkeypatch.setattr(workflow_event_runner, "consume_llm_credit", duplicate_charge)
    inputs = {"original_customer_input": "synthetic business task"}
    if consumer == "customer_tool":

        def execute():
            result = _execute_workflow(
                SimpleNamespace(target_id=str(workflow_id)),
                SimpleNamespace(id=user_id),
                {"input_data": inputs},
            )
            assert result["ok"] and result["workflow_id"] == workflow_id
            return result["output"]

    elif consumer == "service_port":

        def execute():
            return InProcessWorkflowEngineClient().execute_workflow(
                workflow_id=workflow_id, input_data=inputs, user_id=user_id
            )

    else:
        with get_session_factory()() as db:
            parent = Workflow(user_id=user_id, name="Actual parent consumer")
            db.add(parent)
            db.flush()
            nodes = [
                WorkflowNode(
                    workflow_id=parent.id, node_type=kind, name=kind, config=json_dumps(config)
                )
                for kind, config in (
                    ("start", {}),
                    ("sub_workflow", {"workflow_id": workflow_id}),
                    ("end", {}),
                )
            ]
            db.add_all(nodes)
            db.flush()
            db.add_all(
                [
                    WorkflowEdge(
                        workflow_id=parent.id,
                        source_node_id=nodes[0].id,
                        target_node_id=nodes[1].id,
                    ),
                    WorkflowEdge(
                        workflow_id=parent.id,
                        source_node_id=nodes[1].id,
                        target_node_id=nodes[2].id,
                    ),
                ]
            )
            parent_id = parent.id
            db.commit()

        def execute():
            parent_result = workflow_event_runner.run_recorded_workflow(
                workflow_id=parent_id, user_id=user_id, input_data=inputs
            )
            return parent_result["sub_workflow_result"]

    output = execute()
    assert output["original_customer_input"] == inputs["original_customer_input"]
    assert len(observations(run)) == 1 and observations(run)[0]["success"] is True
    invalidate(run, "authority")
    with pytest.raises(ValueError, match="workflow_experiment_graph_no_longer_approved"):
        execute()
    assert len(observations(run)) == 1
    assert len(observations(run, "experiment.execution_archived")) == 1
    with get_session_factory()() as db:
        receipts = (
            db.query(WorkflowExecution)
            .filter_by(workflow_id=workflow_id)
            .order_by(WorkflowExecution.id)
            .all()
        )
        assert [row.status for row in receipts] == ["completed", "failed"]
        assert all(row.completed_at is not None and row.user_id == user_id for row in receipts)
        assert receipts[1].error_message == "workflow_experiment_graph_no_longer_approved"
        assert json_loads(receipts[1].output_data, {}) == {}
