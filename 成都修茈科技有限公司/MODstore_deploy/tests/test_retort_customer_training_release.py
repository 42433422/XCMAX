"""A reviewed customer trainer prompt must be in the release and running module."""

from __future__ import annotations

import base64
from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modstore_server import retort_experiment_runtime as runtime
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server import retort_training_candidates as training
from modstore_server import workflow_nl_graph
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import RetortEvolutionRun, get_session_factory
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_CUSTOMER_MEASUREMENT,
    WORKFLOW_NL_PROMPT_PATH,
    WORKFLOW_NL_RESOURCE,
)
from modstore_server.retort_workflow_metrics import execution_queries
from tests import test_retort_workflow_execution as execution_tests
from tests.test_retort_experiment_lifecycle import Clock, reapprove, start

experiment_run = execution_tests.experiment_run
workflow_experiment = execution_tests.workflow_experiment
execution_experiment = execution_tests.execution_experiment


@pytest.fixture
def released_customer_training(execution_experiment, monkeypatch):
    run = execution_experiment
    life = run["spec"]["lifecycle"]
    life.pop("execution_outcomes")
    life.update(
        measurement_scope=WORKFLOW_CUSTOMER_MEASUREMENT,
        maturation_hours=1,
        customer_outcomes={
            "source": "modstore_customer_workflow_postgres_v1",
            "employee_id": "native-customer-file",
            "observation_hours": 1,
            "success_metric_id": "success",
            "failure_metric_id": "failure",
            "maximum_treatment_failures": 2,
        },
    )
    run["spec"] = lifecycle.freeze_experiment_policy(run["spec"])
    reapprove(run)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        effects["training_candidate"] = {
            **effects.pop("customer_feedback"),
            "surface": "workflow_nl_prompt",
            "resource_id": WORKFLOW_NL_RESOURCE,
            "prompt_path": WORKFLOW_NL_PROMPT_PATH,
        }
        row.effects_json = json_dumps(effects)
        db.commit()
    queries = execution_queries(WORKFLOW_CUSTOMER_MEASUREMENT)
    run["api"].datasource["assignmentQueries"][0]["sql"] = queries["assignment"]
    for name, metric in run["api"].metrics.items():
        metric["sql"].update(conversionSQL=queries[name], userAggregationSQL="MAX(value)")
    released = {"prompt": life["treatment_prompt"], "available": True, "reads": []}
    monkeypatch.setattr(workflow_nl_graph, "SYSTEM_PROMPT", released["prompt"])
    monkeypatch.setattr(
        "modstore_server.customer_ticket_github.configuration",
        lambda: {"repository": "fixture/product"},
    )

    def github(method, path, body=None):
        assert method == "GET" and body is None
        assert path == (
            f"/repos/fixture/product/contents/{quote(WORKFLOW_NL_PROMPT_PATH, safe='/')}"
            f"?ref={run['delivery']['release_sha']}"
        )
        released["reads"].append(path)
        if not released["available"]:
            raise HTTPException(502, "Isolated release readback unavailable")
        return {
            "encoding": "base64",
            "content": base64.b64encode(
                f"SYSTEM_PROMPT = {released['prompt']!r}\n".encode()
            ).decode(),
        }

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    run["released"] = released
    return run


def test_exact_released_and_running_treatment_reaches_original_promotion(
    released_customer_training,
):
    run = released_customer_training
    start(run)
    assert run["advance"]()["status"] == "running"  # Renew the original traffic lease.
    Clock.value += timedelta(hours=3)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    result = run["advance"]()
    assert result["decision"] == "promote" and result["rollout_verified"] is True
    assert len(run["released"]["reads"]) == 6
    with get_session_factory()() as db:
        effects = json_loads(db.get(RetortEvolutionRun, run["id"]).effects_json, {})
        assert effects["training_candidate"]["growthbook"] == run["spec"]
        assert effects["experiment"]["release_sha"] == run["delivery"]["release_sha"]
        assert effects["experiment"]["traffic"] == "candidate"


def test_late_postpromotion_failure_reopens_original_training_compensation(released_customer_training):
    from modstore_server.eventing.db_outbox import enqueue

    run = released_customer_training
    start(run)
    run["advance"]()
    Clock.value += timedelta(hours=3)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        row.status = "completed"
        db.commit()
    assert training.request_postpromotion_regression_rechecks() == 0
    for user_id in run["users"][:2]:
        with get_session_factory()() as db:
            enqueue(
                db,
                "experiment.observed",
                run["id"],
                {
                    "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                    "variation_id": "1",
                    "execution_id": str(uuid4()),
                    "subject_id": str(user_id),
                    "success": False,
                },
                event_id="experiment.observed:" + str(uuid4()),
            )
            db.commit()
    # Uses original outbox stop-loss, never a submitted model verdict.
    assert training.request_postpromotion_regression_rechecks() == 1
    assert training.request_postpromotion_regression_rechecks() == 0
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        assert row.status == "impact_recheck"
        effects = json_loads(row.effects_json, {})
        assert effects["training_regression_recheck"]["reason"] == "workflow_execution_stop_loss"
        assert effects["experiment"]["traffic"] == "candidate"
    state = {**run["state"], "delivery": run["delivery"]}
    first = training.read_training_impact(run["id"], state)
    assert first["status"] == "waiting_customer_impact"
    assert first["experiment"]["status"] in ("awaiting_rollout_readback", "measured")
    second = training.read_training_impact(run["id"], state)
    assert second["status"] == "customer_impact_rejected"
    assert second["reason"] == "experiment_regression"
    assert second["experiment"]["decision"] == "rollback"
    with get_session_factory()() as db:
        effects = json_loads(db.get(RetortEvolutionRun, run["id"]).effects_json, {})
        assert effects["experiment"]["traffic"] == "control"
        assert effects["experiment"]["decision"] == "rollback"
    owner = run["users"][0]
    assert runtime.select_variant(
        surface="workflow_nl_prompt",
        resource_id=WORKFLOW_NL_RESOURCE,
        subject_id=owner,
        workflow_id=run["workflows"][owner],
        default_value=run["spec"]["lifecycle"]["treatment_prompt"],
    ) == (run["spec"]["lifecycle"]["control_prompt"], None)


@pytest.mark.parametrize("tamper", ["no_outbox_regression", "release_changed", "snapshot_changed"])
def test_postpromotion_recheck_cannot_accept_forged_or_unbound_evidence(
    released_customer_training, tamper
):
    run = released_customer_training
    start(run)
    run["advance"]()
    Clock.value += timedelta(hours=3)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        progress = effects["experiment"]
        effects["training_regression_recheck"] = {
            "source": "original_experiment_outbox",
            "reason": "workflow_execution_stop_loss",
            "request_id": run["id"],
            "release_sha": (
                "f" * 40 if tamper == "release_changed" else progress["release_sha"]
            ),
            "final_snapshot_sha256": (
                "f" * 64
                if tamper == "snapshot_changed"
                else progress["final_snapshot_sha256"]
            ),
        }
        row.status = "impact_recheck"
        row.effects_json = json_dumps(effects)
        db.commit()
    previous_calls = list(run["api"].calls)
    state = {**run["state"], "delivery": run["delivery"]}
    result = training.read_training_impact(run["id"], state)
    assert result["status"] == "waiting_customer_impact"
    assert result["reason"] == "training_regression_recheck_unverified"
    assert run["api"].calls == previous_calls
    owner = run["users"][0]
    assert runtime.select_variant(
        surface="workflow_nl_prompt",
        resource_id=WORKFLOW_NL_RESOURCE,
        subject_id=owner,
        workflow_id=run["workflows"][owner],
        default_value=run["spec"]["lifecycle"]["treatment_prompt"],
    ) == (run["spec"]["lifecycle"]["control_prompt"], None)


def test_completed_training_keeps_only_original_postpromotion_effect_evidence(
    released_customer_training
):
    from modstore_server.eventing.db_outbox import enqueue

    run = released_customer_training
    start(run)
    run["advance"]()
    Clock.value += timedelta(hours=3)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        row.status = "completed"
        effects = json_loads(row.effects_json, {})
        progress = effects["experiment"]
        no_evidence = training.postpromotion_effect_snapshot(
            db, row, run["spec"], effects, observed_at=Clock.value + timedelta(days=1)
        )
        assert no_evidence["status"] == "unknown"
        assert no_evidence["observations"] == 0
        observation_id = str(uuid4())
        user_id = run["users"][0]
        enqueue(
            db,
            "experiment.observed",
            run["id"],
            {
                "assignment_stage": "approved_rollout",
                "request_id": run["id"],
                "experiment_id": progress["experiment_id"],
                "policy_digest": progress["policy_digest"],
                "release_sha": progress["release_sha"],
                "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                "variation_id": "1",
                "observation_id": observation_id,
                "subject_id": str(user_id),
                "user_id": user_id,
                "execution_id": str(uuid4()),
                "success": True,
                "customer_outcome_evidence_sha256": "b" * 64,
                "assigned_at": (Clock.value + timedelta(seconds=1)).isoformat(),
                "completed_at": (Clock.value + timedelta(seconds=2)).isoformat(),
            },
            event_id="experiment.observed:" + observation_id,
        )
        db.commit()
    assert training.request_postpromotion_regression_rechecks() == 0
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        saved = json_loads(row.effects_json, {})["training_online_observations"]
        assert saved["scope"] == "cumulative_absolute_observation_not_causal_lift"
        assert len(saved["snapshots"]) == 1
        daily = saved["snapshots"][0]
        assert daily["status"] == "observational_only"
        assert daily["observations"] == daily["successes"] == daily["unique_subjects"] == 1
        assert daily["failures"] == 0
        assert daily["independently_verified_lift"] is False
        assert len(daily["source_events_sha256"]) == 64
    assert training.request_postpromotion_regression_rechecks() == 0
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        assert len(json_loads(row.effects_json, {})["training_online_observations"]["snapshots"]) == 1


def test_invalid_postpromotion_terminal_cannot_supply_verified_improvement(
    released_customer_training
):
    from modstore_server.eventing.db_outbox import enqueue

    run = released_customer_training
    start(run)
    run["advance"]()
    Clock.value += timedelta(hours=3)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["decision"] == "promote"
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        row.status = "completed"
        effects = json_loads(row.effects_json, {})
        progress = effects["experiment"]
        observation_id = str(uuid4())
        user_id = run["users"][0]
        enqueue(
            db,
            "experiment.observed",
            run["id"],
            {
                "assignment_stage": "approved_rollout",
                "request_id": run["id"],
                "experiment_id": progress["experiment_id"],
                "policy_digest": progress["policy_digest"],
                "release_sha": progress["release_sha"],
                "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                "variation_id": "1",
                "observation_id": observation_id,
                "subject_id": str(user_id),
                "user_id": user_id,
                "execution_id": str(uuid4()),
                "success": 1,  # bool required, a producer's 1 is not a verified success.
                "customer_outcome_evidence_sha256": "b" * 64,
                "assigned_at": (Clock.value + timedelta(seconds=1)).isoformat(),
                "completed_at": (Clock.value + timedelta(seconds=2)).isoformat(),
            },
            event_id="experiment.observed:" + observation_id,
        )
        db.flush()
        snapshot = training.postpromotion_effect_snapshot(
            db, row, run["spec"], effects, observed_at=Clock.value + timedelta(days=1)
        )
        assert snapshot["status"] == "source_unverified"
        assert snapshot["observations"] == snapshot["successes"] == 0
        assert snapshot["independently_verified_lift"] is False
        db.rollback()


@pytest.mark.parametrize("phase", ["create", "start", "lease", "promote", "rollout_readback"])
@pytest.mark.parametrize("fault", ["source", "runtime"])
def test_customer_training_release_drift_blocks_forward_progress(
    released_customer_training, monkeypatch, phase, fault
):
    run = released_customer_training
    if phase == "start":
        assert run["advance"]()["status"] == "awaiting_experiment_readback"
    elif phase != "create":
        start(run)
    if phase in {"promote", "rollout_readback"}:
        Clock.value += timedelta(hours=3)
    if phase == "rollout_readback":
        assert run["advance"]()["status"] == "awaiting_experiment_stop"
    if fault == "source":
        run["released"]["prompt"] = run["spec"]["lifecycle"]["control_prompt"]
    else:
        monkeypatch.setattr(
            workflow_nl_graph, "SYSTEM_PROMPT", run["spec"]["lifecycle"]["control_prompt"]
        )
    before = len(run["api"].calls)
    result = run["advance"]()
    assert result["status"] == "experiment_blocked", result
    assert result["reason"] == (
        "training_customer_release_prompt_changed"
        if fault == "source"
        else "training_customer_runtime_prompt_changed"
    )
    assert not [
        call
        for call in run["api"].calls[before:]
        if call[0] == "POST" and not call[1].endswith("/snapshot")
    ]
    with get_session_factory()() as db:
        effects = json_loads(db.get(RetortEvolutionRun, run["id"]).effects_json, {})
        assert effects["experiment"]["traffic"] == "control"


@pytest.mark.parametrize("mode", ["explicit", "statistical", "hold", "maturation"])
def test_release_readback_failure_cannot_block_original_withdrawal_or_hold(
    released_customer_training, monkeypatch, mode
):
    run = released_customer_training
    start(run)
    Clock.value += timedelta(hours=1.5 if mode == "maturation" else 3)
    if mode == "explicit":
        assert run["advance"]()["status"] == "awaiting_experiment_stop"
        assert run["advance"]()["decision"] == "promote"
    else:
        run["api"].interval = [-0.1, 0, 0.1] if mode == "hold" else [-0.18, -0.1, -0.02]
    reads = len(run["released"]["reads"])
    run["released"]["available"] = False
    monkeypatch.setattr(workflow_nl_graph, "SYSTEM_PROMPT", "Old deployed module")
    if mode == "maturation":
        result = run["advance"]()
        assert result["status"] == "running" and result["decision"] == "hold"
        assert len(run["released"]["reads"]) == reads
        return
    run["advance"](reject=mode == "explicit")
    result = run["advance"](reject=mode == "explicit")
    assert result["decision"] == ("hold" if mode == "hold" else "rollback"), result
    assert result["rollout_verified"] is True
    assert len(run["released"]["reads"]) == reads
