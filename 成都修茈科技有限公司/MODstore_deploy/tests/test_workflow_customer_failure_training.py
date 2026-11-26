"""Original customer outcomes, rather than engine terminals, feed private regressions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select

from modstore_server import workflow_execution_feedback as execution_feedback
from modstore_server import workflow_nl_training as training
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.models import (
    OutboxEvent,
    RetortEvolutionRun,
    User,
    WorkflowEdge,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from tests import test_retort_workflow_customer as customer_tests

experiment_run = customer_tests.experiment_run
workflow_experiment = customer_tests.workflow_experiment
execution_experiment = customer_tests.execution_experiment
customer_workflow = customer_tests.customer_workflow


@pytest.fixture(autouse=True)
def capture_original_generation(execution_experiment, monkeypatch):
    # Use the real request capture while the existing fixture creates the graph.
    monkeypatch.setattr(
        training,
        "_policies",
        lambda: [{"growthbook": {"lifecycle": execution_experiment["spec"]["lifecycle"]}}],
    )


def _samples(env, *, cohort=None):
    baseline = env["run"]["spec"]["lifecycle"]["treatment_prompt"]
    return execution_feedback.execution_failure_records(
        days=14,
        cohort=[env["customer_id"]] if cohort is None else cohort,
        baseline=hashlib.sha256(baseline.encode()).hexdigest(),
    )


def _outcome_without_acceptance(env):
    env["actor"][0] = env["admin"]
    response = env["http"].post(
        "/api/admin/customer-value/outcome-materials",
        json={
            **env["goal"],
            "idempotency_key": "outcome-without-customer-acceptance",
            "outcome_id": env["artifact"]["artifact_id"],
            "artifact_sha256": env["artifact"]["artifact_sha256"],
            "measured_value": 1.0,
            "source_material_summary": "Independently measured the original CSV",
            "source_material_sha256": "b" * 64,
        },
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def customer_business_source(capture_original_generation, customer_workflow, monkeypatch):
    """Real SQL failures and pre-execution operator oracles for both stable partitions."""
    from modstore_server.workflow_training_replay import _blob, source_group_sha256

    env = customer_workflow
    references = {}
    policy = {
        "growthbook": {"lifecycle": env["run"]["spec"]["lifecycle"]},
        "offline_business_replay": {"references": references},
    }
    monkeypatch.setattr(training, "_policies", lambda: [policy])
    for holdout in (False, True):
        for nonce in range(100):
            order = f"private-synthetic-order-{holdout}-{nonce}"
            raw = json.dumps(
                {"columns": ["order", "quantity"], "rows": [{"order": order, "quantity": 3}]}
            ).encode()
            group = source_group_sha256(
                {
                    "assets": {
                        "workspace": str(env["workspace"]),
                        "input_data": {"file_path": "inputs/orders.json"},
                        "input_files": [_blob("inputs/orders.json", raw)],
                    },
                    "contract": {"node_input": {"file_path": "inputs/orders.json"}},
                }
            )
            if (int(hashlib.sha256(raw).hexdigest()[:8], 16) % 5 == 0) is holdout:
                break
        else:
            raise AssertionError("could not construct independent fixture source groups")
        (env["workspace"] / "inputs/orders.json").write_bytes(raw)
        # Approved before the failed run; the expected business format is semicolon CSV.
        # No produced customer output is read to construct this independent reference.
        golden = f"order;quantity\r\n{order};3\r\n".encode()
        reference_path = f"inputs/operator-reference-{int(holdout)}.csv"
        (env["workspace"] / reference_path).write_bytes(golden)
        references[group] = [
            {
                "output_path": "outputs/output.csv",
                "reference_path": reference_path,
                "sha256": hashlib.sha256(golden).hexdigest(),
            }
        ]
        response = env["execute"]()
        assert response.status_code == 200, response.text
        customer_tests.business_receipts(env, measured=0.0)
    customer_tests.mature(env)
    samples = _samples(env)
    assert len(samples) == 2
    assert all(
        sample["generation_context"]["customer_business_replay"]["replay_ready"]
        for sample in samples
    )
    candidate = deepcopy(env["run"]["graph"])
    candidate["nodes"][1]["config"]["input_mapping"]["delimiter"] = ";"
    env.update(
        business_samples=samples,
        training_policy=policy,
        business_outputs={
            "control": json.dumps(env["run"]["graph"]),
            "candidate": json.dumps(candidate),
        },
    )
    return env


def test_completed_customer_failure_preserves_original_source_and_private_replay_identity(
    customer_workflow,
):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    customer_tests.business_receipts(env, measured=0.0)
    assert _samples(env) == []  # The fixed observation window has not matured.
    observed = customer_tests.mature(env)[0]
    assert observed["success"] is False
    assert observed["customer_outcome_classification"] == "business_failure"
    samples = _samples(env)
    assert len(samples) == 1
    sample = samples[0]
    assert sample["error"] == "workflow_customer_outcome_failed"
    assert sample["run_id"] == f"workflow-customer:{env['execution_id']}"
    context = sample["generation_context"]
    source = context["execution_feedback"]["customer_outcome"]
    assert context["execution_feedback"]["measurement_scope"] == WORKFLOW_CUSTOMER_MEASUREMENT
    assert source["contract_sha256"] == env["binding"]["customer_delivery"]["contract_sha256"]
    assert source["evidence_sha256"] == observed["customer_outcome_evidence_sha256"]
    assert source["customer_policy"]["employee_id"] == env["employee_id"]
    assert source["goal"] == env["binding"]["customer_delivery"]["goal"]
    assert source["receipt_refs"]
    assert source["required_artifacts"][0]["artifact_id"] == env["artifact"]["artifact_id"]
    assert context["customer_business_replay"]["user_id"] == env["customer_id"]
    assert context["customer_business_replay"]["input_sha256"] == env["binding"]["input_sha256"]
    assert context["customer_business_replay"]["replay_ready"] is False
    assert _samples(env) == samples  # Mining does not create another execution or receipt.


@pytest.mark.parametrize(
    ("receipts", "classification"),
    [
        ("none", "evidence_missing"),
        ("outcome_only", "pending_acceptance"),
        ("success", "success"),
    ],
)
def test_missing_acceptance_and_missing_evidence_are_not_prompt_failures(
    customer_workflow, receipts, classification
):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    if receipts == "success":
        customer_tests.business_receipts(env)
    elif receipts == "outcome_only":
        _outcome_without_acceptance(env)
    observed = customer_tests.mature(env)[0]
    assert observed["customer_outcome_classification"] == classification
    assert _samples(env) == []


@pytest.mark.parametrize("receipts", ["miss", "outcome_only", "none"])
def test_promoted_customer_failures_feed_next_training_without_reopening_experiment(
    customer_workflow, receipts, monkeypatch, tmp_path
):
    from modstore_server import capability_trainer as trainer
    from modstore_server import workflow_nl_graph as generator

    env = customer_workflow
    # The original training plan publishes the treatment as the source constant
    # before its approved experiment. Exercise that same single production baseline.
    monkeypatch.setattr(
        generator, "SYSTEM_PROMPT", env["run"]["spec"]["lifecycle"]["treatment_prompt"]
    )

    def mined_samples():
        return [
            sample
            for cluster in trainer.mine(tmp_path / "empty-training-ledger.jsonl", min_count=1)
            if cluster["surface"] == "workflow_nl_prompt"
            for sample in cluster["samples"]
        ]

    assert env["execute"]().status_code == 200
    customer_tests.business_receipts(env)
    observed = customer_tests.mature(env)
    customer_tests.Clock.value += timedelta(hours=1)
    assert env["run"]["advance"]()["status"] == "awaiting_experiment_stop"
    assert env["run"]["advance"]()["decision"] == "promote"
    exposures = customer_tests.observations(env["run"], "experiment.exposed")
    with get_session_factory()() as db:
        workflow_id = env["run"]["workflows"][env["customer_id"]]
        db.query(WorkflowEdge).filter_by(workflow_id=workflow_id).delete()
        db.query(WorkflowNode).filter_by(workflow_id=workflow_id).delete()
        db.commit()
    generated = asyncio.run(env["run"]["generate"](env["customer_id"]))
    assert generated["ok"] and generated["sandbox_ok"]
    assert env["execute"]().status_code == 200
    assert env["binding"]["assignment"]["assignment_stage"] == "approved_rollout"
    assert env["binding"]["metric_admitted"] is False
    assert env["binding"]["rollout_admitted"] is True
    if receipts == "miss":
        customer_tests.business_receipts(env, measured=0.0)
    elif receipts == "outcome_only":
        _outcome_without_acceptance(env)
    assert _samples(env) == []
    assert training.failure_records() == []
    assert mined_samples() == []
    customer_tests.Clock.value = parse_datetime(
        env["binding"]["customer_outcome_due_at"]
    ) + timedelta(seconds=1)
    customer_tests.feedback.reconcile_customer_executions(env["run"]["id"])
    samples = _samples(env)
    assert training.failure_records() == samples
    mined = mined_samples()
    assert [sample["run_id"] for sample in mined] == [sample["run_id"] for sample in samples]
    assert [sample["generation_context"] for sample in mined] == [
        sample["generation_context"] for sample in samples
    ]
    assert customer_tests.observations(env["run"]) == observed
    assert customer_tests.observations(env["run"], "experiment.exposed") == exposures
    if receipts != "miss":
        assert samples == []
        return
    assert len(samples) == 1
    assert samples[0]["run_id"] == f"workflow-customer:{env['execution_id']}"
    outcome = samples[0]["generation_context"]["execution_feedback"]["customer_outcome"]
    assert outcome["reason"] == "customer_goal_not_met"
    assert outcome["contract_sha256"] == env["binding"]["customer_delivery"]["contract_sha256"]
    assert _samples(env) == samples
    env["run"]["advance"](reject=True)
    env["run"]["advance"](reject=True)
    assert _samples(env) == samples  # A later withdrawal cannot erase the original product failure.
    assert training.failure_records() == samples
    assert mined_samples() == mined
    customer_tests.refund(env)
    assert _samples(env) == []  # Refunds remain an independent stop/recovery source.
    assert training.failure_records() == []
    assert mined_samples() == []


@pytest.mark.parametrize(
    "stopped", ["stop_loss", "rollback", "customer_impact_rejected", "waiting_recovery"]
)
def test_closed_failed_experiment_remains_a_source_without_authorizing_new_traffic(
    customer_workflow, monkeypatch, stopped
):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    customer_tests.business_receipts(env, measured=0.0)
    customer_tests.mature(env)
    original = _samples(env)
    assert len(original) == 1
    if stopped == "stop_loss":
        monkeypatch.setattr(
            "modstore_server.retort_workflow_metrics.execution_stop_loss", lambda *_: True
        )
    else:
        env["run"]["advance"](reject=True)
        env["run"]["advance"](reject=True)
        with get_session_factory()() as db:
            run = db.get(RetortEvolutionRun, env["run"]["id"])
            progress = json_loads(run.effects_json, {})["experiment"]
            assert progress["decision"] == "rollback" and progress["closed_at"]
            if stopped in {"customer_impact_rejected", "waiting_recovery"}:
                run.status = stopped
                db.commit()
        monkeypatch.setattr(
            "modstore_server.retort_experiment_runtime._identity", lambda: {"git_sha": "b" * 40}
        )
    assert _samples(env) == original
    with get_session_factory()() as db:
        assert not execution_feedback._admitted(db, env["binding"])
        assert not execution_feedback._admitted(db, env["binding"], completing=True)
        # The original frozen source may not drift, even after the current release changes.
        row = db.get(RetortEvolutionRun, env["run"]["id"])
        effects = json_loads(row.effects_json, {})
        effects["experiment"]["identity"]["git_sha"] = "c" * 40
        row.effects_json = json_dumps(effects)
        db.commit()
    assert _samples(env) == []


def test_closed_experiment_does_not_restore_revoked_operator_authority(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    customer_tests.business_receipts(env, measured=0.0)
    customer_tests.mature(env)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, env["run"]["id"])
        row.status = "customer_impact_rejected"
        db.commit()
    assert len(_samples(env)) == 1
    with get_session_factory()() as db:
        db.get(User, env["admin"].id).is_admin = False
        db.commit()
    assert _samples(env) == []


@pytest.mark.parametrize(
    "fault",
    ["cohort", "artifact", "observed", "owner", "contract", "deadline", "source", "disabled"],
)
def test_customer_failure_rechecks_owned_frozen_evidence_before_mining(customer_workflow, fault):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    customer_tests.business_receipts(env, measured=0.0)
    customer_tests.mature(env)
    assert len(_samples(env)) == 1
    if fault == "cohort":
        assert _samples(env, cohort=[]) == []
        return
    if fault == "source":
        env["source"]["source_available"] = False
        assert _samples(env) == []
        return
    if fault == "artifact":
        from modstore_server.workflow_customer_delivery import _artifact_snapshot_path

        path = _artifact_snapshot_path(env["binding"]["customer_delivery"], env["artifact"])
        path.write_bytes(b"Changed the original private delivery snapshot")
        assert _samples(env) == []
        return
    with get_session_factory()() as db:
        if fault == "disabled":
            db.get(User, env["customer_id"]).account_state = "disabled"
            db.commit()
            assert _samples(env) == []
            return
        event_id = (
            f"experiment.observed:workflow-customer:{env['execution_id']}"
            if fault == "observed"
            else f"workflow.execution.feedback_started:{env['execution_id']}"
        )
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
        body = json_loads(row.payload_json, {})
        if fault == "observed":
            body["customer_outcome_evidence_sha256"] = "f" * 64
        elif fault == "owner":
            body["user_id"] = env["admin"].id
        elif fault == "deadline":
            body["customer_outcome_due_at"] = "2000-01-01T00:00:00+00:00"
        else:
            body["customer_delivery"]["contract_sha256"] = "f" * 64
        row.payload_json = json_dumps(body)
        db.commit()
    assert _samples(env) == []
