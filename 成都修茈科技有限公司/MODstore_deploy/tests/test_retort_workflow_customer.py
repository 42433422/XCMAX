"""Actual customer workflow files reach frozen experimental business observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from datetime import timedelta
from functools import partial
from uuid import uuid4

import pytest
from retort_engine.evolution_contract import digest
from sqlalchemy import create_engine, select, text

from modstore_server import retort_evolution as evolution
from modstore_server import retort_feedback_recovery as recovery
from modstore_server import workflow_customer_feedback as feedback
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.customer_value_evidence import append_customer_value_receipt
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    WorkflowExecution,
    WorkflowSandboxRun,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.retort_workflow_metrics import (
    execution_queries,
    execution_stop_loss,
    verify_execution_source,
)
from tests import test_workflow_customer_delivery as delivery_tests
from tests.test_retort_experiment_lifecycle import Clock
from tests.test_retort_workflow_experiment import observations

experiment_run = delivery_tests.experiment_run
workflow_experiment = delivery_tests.workflow_experiment
execution_experiment = delivery_tests.execution_experiment
customer_workflow = delivery_tests.customer_workflow


def business_receipts(env, *, measured=1.0, occurred_at=None, acceptance_id=None):
    artifact = env["artifact"]
    event_time = {"occurred_at": occurred_at.isoformat()} if occurred_at else {}
    env["actor"][0] = env["admin"]
    outcome = env["http"].post(
        "/api/admin/customer-value/outcome-materials",
        json={
            **env["goal"],
            "idempotency_key": "workflow-outcome-" + uuid4().hex,
            "outcome_id": artifact["artifact_id"],
            "artifact_sha256": artifact["artifact_sha256"],
            "measured_value": measured,
            "source_material_summary": "Measured the original CSV against the agreed customer target",
            "source_material_sha256": "b" * 64,
            **event_time,
        },
    )
    assert outcome.status_code == 200, outcome.text
    env["actor"][0] = env["actors"][env["customer_id"]]
    accepted = delivery_tests._accept(
        env,
        idempotency_key="workflow-accepted-" + uuid4().hex,
        **({"acceptance_id": acceptance_id} if acceptance_id else {}),
        **event_time,
    )
    assert accepted.status_code == 200, accepted.text
    return outcome.json(), accepted.json()


def mature(env):
    Clock.value = parse_datetime(env["binding"]["customer_outcome_due_at"]) + timedelta(seconds=1)
    env["run"]["advance"]()  # Original lifecycle consumer, not a detached measurement helper.
    return observations(env["run"])


def refund(env):
    return append_customer_value_receipt(
        {
            "receipt_kind": "refund",
            "verification_status": "verified",
            "customer_ref": f"paid-user:{env['customer_id']}",
            "customer_goal_id": env["goal"]["customer_goal_id"],
            "order_no": env["goal"]["order_no"],
            "environment": "production",
            "source_event_id": "verified-refund-" + uuid4().hex,
            "occurred_at": Clock.value,
            "evidence": {"provider_refund_id": "verified-original-order-refund"},
        },
        payment_order=env["order"],
        now=Clock.value,
    )


@pytest.mark.parametrize("measured", [1.0, 0.0])
def test_real_customer_api_outcomes_mature_into_original_account_assignment(
    customer_workflow, measured
):
    env = customer_workflow
    response = env["execute"]()
    assert response.status_code == 200, response.text
    assert observations(env["run"]) == []  # A successful engine is not customer success.
    business_receipts(env, measured=measured)
    assert feedback.reconcile_customer_executions(env["run"]["id"])["pending"] == 1
    observed = mature(env)
    assert len(observed) == 1
    item = observed[0]
    assert item["measurement_scope"] == WORKFLOW_CUSTOMER_MEASUREMENT
    assert item["execution_id"] == env["execution_id"] and item["success"] is (measured == 1.0)
    assert item["subject_id"] == str(env["customer_id"]) and item["variation_id"] == "1"
    assert item["customer_outcome_evidence_sha256"]
    for _ in range(3):
        env["run"]["advance"]()
    assert observations(env["run"]) == observed
    with env["run"]["api"].client() as api:
        verify_execution_source(api, env["run"]["spec"])
    assert "GROUP BY user_id" in execution_queries(WORKFLOW_CUSTOMER_MEASUREMENT)["success"]
    env["run"]["api"].metrics["success"]["sql"]["userAggregationSQL"] = "SUM(value)"
    with (
        env["run"]["api"].client() as api,
        pytest.raises(ValueError, match="metric_source_changed"),
    ):
        verify_execution_source(api, env["run"]["spec"])


def test_unavailable_payment_stays_pending_then_the_original_receipts_settle(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    business_receipts(env)
    env["source"]["source_available"] = False
    assert mature(env) == []
    assert feedback.reconcile_customer_executions(env["run"]["id"])["pending"] == 1
    env["source"]["source_available"] = True
    env["run"]["advance"]()
    assert observations(env["run"])[0]["success"] is True


def test_late_customer_confirmation_cannot_rewrite_the_frozen_observation(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    frozen = mature(env)
    assert len(frozen) == 1 and frozen[0]["success"] is False
    business_receipts(env)
    feedback.reconcile_customer_executions(env["run"]["id"])
    assert observations(env["run"]) == frozen


def test_backdated_receipts_recorded_after_the_window_are_not_accepted_as_timely_evidence(
    customer_workflow, monkeypatch
):
    from modstore_server import customer_value_evidence

    env = customer_workflow
    assert env["execute"]().status_code == 200
    due = parse_datetime(env["binding"]["customer_outcome_due_at"])
    within_window = due - timedelta(minutes=5)
    Clock.value = due + timedelta(seconds=1)
    monkeypatch.setattr(customer_value_evidence, "datetime", Clock)
    business_receipts(env, occurred_at=within_window)
    assert feedback.reconcile_customer_executions(env["run"]["id"])["observed"] == 1
    assert observations(env["run"])[0]["success"] is False


def test_actual_native_failure_is_a_failed_execution_not_a_completed_customer_delivery(
    customer_workflow,
):
    env = customer_workflow
    (env["workspace"] / "outputs/output.csv").mkdir(parents=True)
    response = env["execute"]()
    assert response.status_code == 500, response.text
    with get_session_factory()() as db:
        row = db.scalars(
            select(WorkflowExecution)
            .where(WorkflowExecution.user_id == env["customer_id"])
            .order_by(WorkflowExecution.id.desc())
        ).first()
        assert row.status == "failed" and row.completed_at
        env["execution_id"] = row.id
        event = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_id == f"workflow.execution.feedback_started:{row.id}"
            )
        )
        env["binding"] = json_loads(event.payload_json, {})
        assert (
            db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.event_name == "workflow.customer.delivery_produced",
                    OutboxEvent.aggregate_id == str(row.id),
                )
            )
            is None
        )
    measured = mature(env)
    assert len(measured) == 1 and measured[0]["success"] is False
    assert measured[0]["execution_id"] == env["execution_id"]


@pytest.mark.parametrize("fault", ["generation", "claimed_execution"])
def test_customer_delivery_request_without_original_start_is_rejected_before_side_effects(
    customer_workflow, fault
):
    env = customer_workflow
    values = {}
    if fault == "generation":
        with get_session_factory()() as db:
            db.query(WorkflowSandboxRun).filter_by(
                workflow_id=env["run"]["workflows"][env["customer_id"]]
            ).delete()
            db.commit()
    else:
        values["execution_id"] = 9999
    response = env["execute"](**values)
    assert response.status_code == 500, response.text
    assert not (env["workspace"] / "outputs/output.csv").exists()
    with get_session_factory()() as db:
        row = db.scalars(
            select(WorkflowExecution)
            .where(WorkflowExecution.user_id == env["customer_id"])
            .order_by(WorkflowExecution.id.desc())
        ).first()
        assert row.status == "failed"
        assert (
            db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.event_name == "workflow.customer.delivery_started",
                    OutboxEvent.aggregate_id == str(row.id),
                )
            )
            is None
        )


def test_rollout_new_graph_keeps_provenance_without_new_experimental_samples(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    business_receipts(env)
    before = mature(env)
    Clock.value += timedelta(hours=1)
    assert env["run"]["advance"]()["status"] == "awaiting_experiment_stop"
    assert env["run"]["advance"]()["decision"] == "promote"
    # Replace the old graph through the real generator only after deleting its
    # old nodes via the ordinary owned graph tables, as the editor does.
    from modstore_server.models import WorkflowEdge, WorkflowNode

    with get_session_factory()() as db:
        workflow_id = env["run"]["workflows"][env["customer_id"]]
        db.query(WorkflowEdge).filter_by(workflow_id=workflow_id).delete()
        db.query(WorkflowNode).filter_by(workflow_id=workflow_id).delete()
        db.commit()
    generated = asyncio.run(env["run"]["generate"](env["customer_id"]))
    assert generated["ok"] and generated["sandbox_ok"]
    source = env["workspace"] / "inputs/orders.json"
    data = json.loads(source.read_text())
    data["rows"][0]["quantity"] = 4
    source.write_text(json.dumps(data))
    assert env["execute"]().status_code == 200
    assert env["binding"]["assignment"]["assignment_stage"] == "approved_rollout"
    assert env["binding"]["metric_admitted"] is False
    feedback.reconcile_customer_executions(env["run"]["id"])
    assert observations(env["run"]) == before
    refund(env)
    denied = env["execute"]()
    assert denied.status_code == 500
    assert denied.json() == {"detail": "工作流执行失败，请查看执行记录"}
    with get_session_factory()() as db:
        refused = db.scalars(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.user_id == env["customer_id"],
            )
            .order_by(WorkflowExecution.id.desc())
        ).first()
        assert refused.status == "failed" and refused.completed_at
        assert refused.error_message == "workflow_customer_experiment_no_longer_approved"
        assert refused.error_message not in denied.text
    assert env["run"]["advance"]()["status"] == "awaiting_rollout_readback"
    assert env["run"]["advance"]()["decision"] == "rollback"
    assert observations(env["run"]) == before



def test_actual_promoted_customer_delivery_enters_separate_postpromotion_ledger(
    customer_workflow,
):
    """The genuine customer/file path supplies effects, but never A/B samples."""
    from modstore_server.models import WorkflowEdge, WorkflowNode

    env = customer_workflow
    assert env["execute"]().status_code == 200
    business_receipts(env)
    original = mature(env)
    Clock.value += timedelta(hours=1)
    assert env["run"]["advance"]()["status"] == "awaiting_experiment_stop"
    assert env["run"]["advance"]()["decision"] == "promote"
    with get_session_factory()() as db:
        workflow_id = env["run"]["workflows"][env["customer_id"]]
        db.query(WorkflowEdge).filter_by(workflow_id=workflow_id).delete()
        db.query(WorkflowNode).filter_by(workflow_id=workflow_id).delete()
        db.commit()
    generated = asyncio.run(env["run"]["generate"](env["customer_id"]))
    assert generated["ok"] and generated["sandbox_ok"]
    source = env["workspace"] / "inputs/orders.json"
    actual = json.loads(source.read_text())
    actual["rows"][0]["quantity"] = 4
    source.write_text(json.dumps(actual))
    assert env["execute"]().status_code == 200
    assert env["binding"]["rollout_admitted"] is True
    assert env["binding"]["metric_admitted"] is False
    business_receipts(env, acceptance_id="approved-followup-" + uuid4().hex)
    Clock.value = parse_datetime(env["binding"]["customer_outcome_due_at"]) + timedelta(
        seconds=1
    )
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, env["run"]["id"])
        row.status = "completed"
        db.commit()
    with get_session_factory()() as db:
        result = feedback.reconcile_postpromotion_customer_outcomes(
            env["run"]["id"], session=db
        )
        assert result == {"observed": 1, "pending": 0}
        db.commit()
    with get_session_factory()() as db:
        rows = list(
            db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == env["run"]["id"],
                    OutboxEvent.event_name == "experiment.postpromotion_observed",
                )
            )
        )
        assert len(rows) == 1
        item = json_loads(rows[0].payload_json, {})
        assert item["execution_id"] == env["execution_id"]
        assert item["assignment_stage"] == "approved_rollout"
        assert item["customer_outcome_evidence_sha256"]
        assert item["success"] is True
        from modstore_server.retort_training_candidates import postpromotion_effect_snapshot

        effects = json_loads(db.get(RetortEvolutionRun, env["run"]["id"]).effects_json, {})
        snapshot = postpromotion_effect_snapshot(
            db, db.get(RetortEvolutionRun, env["run"]["id"]),
            env["run"]["spec"], effects, observed_at=Clock.value,
        )
        assert snapshot["status"] == "observational_only"
        assert snapshot["successes"] == 1
        assert snapshot["independently_verified_lift"] is False
    assert feedback.reconcile_customer_executions(env["run"]["id"])["observed"] == 0
    assert observations(env["run"]) == original
    with get_session_factory()() as db:
        assert feedback.reconcile_postpromotion_customer_outcomes(
            env["run"]["id"], session=db
        ) == {"observed": 0, "pending": 0}


def test_repeated_customer_executions_remain_one_account_for_failure_guard(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    source = env["workspace"] / "inputs/orders.json"
    data = json.loads(source.read_text())
    data["rows"][0]["quantity"] = 4
    source.write_text(json.dumps(data))
    assert env["execute"]().status_code == 200
    observed = mature(env)
    assert len(observed) == 2 and all(item["success"] is False for item in observed)
    assert len({item["subject_id"] for item in observed}) == 1
    with get_session_factory()() as db:
        assert not execution_stop_loss(
            db, db.get(RetortEvolutionRun, env["run"]["id"]), env["run"]["spec"]
        )


@pytest.mark.skipif(
    not os.getenv("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)
def test_postgres_business_queries_keep_one_account_and_exclude_other_measurement_scopes(
    customer_workflow,
):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    business_receipts(env)
    source = env["workspace"] / "inputs/orders.json"
    data = json.loads(source.read_text())
    data["rows"][0]["quantity"] = 4
    source.write_text(json.dumps(data))
    assert env["execute"]().status_code == 200
    actual = mature(env)
    assert {item["success"] for item in actual} == {True, False}
    with get_session_factory()() as db:
        events = [
            {"event_name": event.event_name, "payload_json": event.payload_json}
            for event in db.query(OutboxEvent).filter_by(aggregate_id=env["run"]["id"])
        ]
    for scope in ("workflow_generation_static_validation", "workflow_execution_terminal"):
        events.append(
            {
                "event_name": "experiment.observed",
                "payload_json": json_dumps(
                    {**actual[0], "subject_id": "other", "measurement_scope": scope}
                ),
            }
        )
    # A repeated execution observation for the same account does not increase
    # a binomial sample. Missing trusted customer evidence is excluded entirely.
    events.append({"event_name": "experiment.observed", "payload_json": json_dumps(actual[0])})
    missing = {**actual[0], "subject_id": "unbound"}
    missing.pop("customer_outcome_evidence_sha256")
    events.append({"event_name": "experiment.observed", "payload_json": json_dumps(missing)})
    engine = create_engine(os.environ["RETORT_TEST_POSTGRES_DSN"])
    try:
        with engine.begin() as connection:
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
                for key, sql in execution_queries(WORKFLOW_CUSTOMER_MEASUREMENT).items()
            }
            assert all(len(value) == 1 for value in rows.values())
            assert {row["user_id"] for value in rows.values() for row in value} == {
                f"{env['customer_id']}:{env['run']['id']}"
            }
    finally:
        engine.dispose()


def test_completed_refund_reenters_actual_graph_withdraws_and_converges_after_exact_readback(
    customer_workflow, monkeypatch, tmp_path
):
    from retort_engine.evolution_workflow import build_evolution_graph

    from modstore_server.customer_value_reconciler import reconcile_paid_customer_value
    from tests.test_customer_value_refunds import install_refund_gateway, native_refund_row
    from tests.test_retort_feedback_decisions import identity

    env = customer_workflow
    run = env["run"]
    assert env["execute"]().status_code == 200
    business_receipts(env)
    frozen = mature(env)
    Clock.value += timedelta(hours=1)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    # Fixture a previously completed checkpoint with the original approved
    # rollback contract. The test runs the real scheduler, graph and recovery
    # adapter; only the external host command/health are synthetic boundaries.
    state = {
        **deepcopy(run["state"]),
        "delivery": {**run["delivery"], "identity": identity("a")},
        "optimization": {},
        "has_customer_feedback": True,
        "status": "completed",
        "impact": {"status": "customer_impact_verified"},
    }
    policy = {
        "mode": "restore_previous_release",
        "target": identity("b"),
        "captured_at": Clock.value.isoformat(),
    }
    with get_session_factory()() as db:
        # Other tests retain rows in this integration database. They must not
        # consume this test's original scheduler batch or external fixtures.
        db.query(RetortEvolutionRun).filter(RetortEvolutionRun.id != run["id"]).update(
            {"status": "cancelled"}
        )
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        effects["customer_feedback"]["recovery"] = policy
        effects["plan"]["feedback_policy"]["recovery"] = policy
        state["plan"] = effects["plan"]
        effects["authorization"]["digest"] = digest(
            {key: state[key] for key in ("protocol", "plan", "optimization")}
        )
        row.effects_json = json_dumps(effects)
        row.status = "completed"
        row.snapshot_json = json_dumps(state)
        db.commit()
    monkeypatch.setenv("MODSTORE_RETORT_CHECKPOINT_DSN", "sqlite:///" + str(tmp_path / "flow.db"))
    with evolution.checkpoint() as saver:
        graph = build_evolution_graph(evolution.ComponentPorts(run["id"]), saver)
        graph.update_state({"configurable": {"thread_id": run["id"]}}, state, as_node="remember")
    for method in ("plan", "optimize", "dispatch", "collect", "verify", "delivery"):
        monkeypatch.setattr(
            evolution.ComponentPorts, method, lambda *_a: pytest.fail("upstream work replayed")
        )

    expected = {
        "request_id": f"retort:{run['id']}:rollback",
        "expected_identity": identity("a"),
        "target_identity": identity("b"),
        "reason": "verified_customer_refund",
    }
    releases = tmp_path / "releases"
    target = releases / ("b" * 40)
    target.mkdir(parents=True)
    (target / ".xcmax-release.json").write_text(json.dumps(identity("b")))
    (tmp_path / "current").symlink_to(target, target_is_directory=True)
    runtime_dir = tmp_path / "runtime"
    receipts = runtime_dir / "release-recovery"
    receipts.mkdir(parents=True)
    lock = tmp_path / "release.lock"
    lock.touch()
    monkeypatch.setenv("XCMAX_RELEASE_BASE", str(tmp_path))
    monkeypatch.setenv("XCMAX_ALLOW_CUSTOM_RELEASE_BASE", "1")
    monkeypatch.setenv("XCMAX_RELEASE_LOCK", str(lock))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("MODSTORE_AUTO_ROLLBACK_COMMAND", "original-operator-cas-recovery")
    immutable = recovery._immutable_recovery()
    monkeypatch.setattr(immutable, "_payment_present", lambda: False)
    monkeypatch.setattr(
        immutable,
        "readback",
        partial(
            immutable.readback,
            read_health=lambda _url: {"ok": True, "deploy_tier": "production", **identity("b")},
        ),
    )
    current = {"value": identity("a")}
    monkeypatch.setattr(recovery, "_release_identity", lambda: current["value"])
    attempts = []

    def unknown_command(**kwargs):
        attempts.append(kwargs)
        raise ConnectionError("synthetic lost command response")

    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery", unknown_command
    )
    refund_row = native_refund_row(
        user_id=env["customer_id"], order_no=env["order"]["out_trade_no"], now=Clock.value
    )
    refund_row.update(
        amount_cents=env["order"]["amount_cents"],
        order_total_amount_cents=env["order"]["amount_cents"],
        paid_at=env["order"]["paid_at"],
        provider_trade_no=env["order"]["provider_trade_no"],
    )
    gateway = install_refund_gateway(monkeypatch, [refund_row], at=Clock.value)
    first = reconcile_paid_customer_value(session_factory=get_session_factory(), now=Clock.value)
    again = reconcile_paid_customer_value(session_factory=get_session_factory(), now=Clock.value)
    assert first["refunds"]["created"] == 1 and again["refunds"]["existing"] == 1
    assert len(gateway.calls) == 2  # Actual authenticated source loader, not a seeded receipt.
    assert evolution.tick() == {"processed": 1, "errors": []}
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        assert row.status == "delivered"
        refs = json_loads(row.effects_json, {})["customer_outcome_recheck"]["references"]
        assert refs[0]["execution_id"] == env["execution_id"]
    assert feedback.request_customer_refund_rechecks() == 0
    assert evolution.tick() == {"processed": 1, "errors": []}
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        assert row.status == "waiting_recovery"
        effects = json_loads(row.effects_json, {})
        assert effects["experiment"]["traffic"] == "control"
        assert effects["recovery"]["submitted"] is True
    assert len(attempts) == 1
    current["value"] = identity("b")
    receipt = {
        **expected,
        "request_sha256": hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "status": "rollback_verified",
        "identity": identity("b"),
        "submitted": True,
    }
    (receipts / (hashlib.sha256(expected["request_id"].encode()).hexdigest() + ".json")).write_text(
        json.dumps(receipt)
    )
    assert evolution.tick() == {"processed": 1, "errors": []}
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        assert row.status == "customer_impact_rejected"
        assert json_loads(row.effects_json, {})["experiment"]["decision"] == "rollback"
        settled = row.updated_at
    calls = list(run["api"].calls)
    for _ in range(3):
        assert evolution.tick() == {"processed": 0, "errors": []}
        assert evolution.advance_run(run["id"])["status"] == "customer_impact_rejected"
    assert len(attempts) == 1 and run["api"].calls == calls
    with get_session_factory()() as db:
        assert db.get(RetortEvolutionRun, run["id"]).updated_at == settled
    assert observations(run) == frozen
