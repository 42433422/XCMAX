"""Regression results drive compensation, never success from mere measurement."""

from copy import deepcopy
from uuid import uuid4

import pytest
from retort_engine.evolution_contract import digest

from modstore_server import retort_feedback_recovery as recovery
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import RetortEvolutionRun, User, get_session_factory
from modstore_server.retort_feedback_measurements import _snapshot


def metric(name, low, lift, high):
    return {
        "metricId": name,
        "variations": [
            {"users": 60},
            {"users": 60, "analyses": [{"percentChange": lift, "ciLow": low, "ciHigh": high}]},
        ],
    }


@pytest.fixture
def experiment():
    spec = {"id": "exp", "project": "prod", "metric": "success", "minimum_users": 100}
    delivery = {"release_sha": "a" * 40, "deployment_completed_at": "2026-01-01T00:00:00Z"}
    payload = {
        "experiment": {
            "id": "exp",
            "project": "prod",
            "type": "standard",
            "status": "stopped",
            "trackingKey": "xcagi-retort-run",
            "tags": ["xcagi-release-" + "a" * 40],
        },
        "result": {
            "id": "snap",
            "experimentId": "exp",
            "dateStart": "2026-01-02T00:00:00Z",
            "dateUpdated": "2026-01-03T00:00:00Z",
            "dimension": {"type": "none"},
            "results": [{"totalUsers": 120, "checks": {"srm": 0.9}, "metrics": []}],
        },
    }
    return spec, delivery, payload


@pytest.mark.parametrize(
    "direction,interval,expected",
    [
        ("increase", (0.02, 0.12, 0.22), "promote"),
        ("increase", (-0.22, -0.12, -0.02), "rollback"),
        ("increase", (-0.02, 0.02, 0.04), "hold"),
        ("decrease", (-0.22, -0.12, -0.02), "promote"),
        ("decrease", (0.02, 0.12, 0.22), "rollback"),
    ],
)
def test_growthbook_direction_and_interval_control_decision(
    experiment, direction, interval, expected
):
    spec, delivery, payload = experiment
    spec["direction"] = direction
    payload["result"]["results"][0]["metrics"] = [metric("success", *interval)]
    result = _snapshot(payload, spec, "run", delivery)
    assert result["status"] == "measured" and result["decision"] == expected
    payload["experiment"]["status"] = "running"
    assert _snapshot(payload, spec, "run", delivery)["decision"] == "hold"


@pytest.mark.parametrize(
    "interval,expected",
    [
        ((-0.03, 0, 0.03), "hold"),
        ((0.03, 0.05, 0.07), "rollback"),
        ((-0.03, -0.02, 0.005), "promote"),
    ],
)
def test_growthbook_guardrail_overrides_successful_primary(experiment, interval, expected):
    spec, delivery, payload = experiment
    spec["guardrails"] = [{"metric": "cost", "direction": "decrease", "maximum_regression": 0.01}]
    payload["result"]["results"][0]["metrics"] = [
        metric("success", 0.02, 0.12, 0.22),
        metric("cost", *interval),
    ]
    assert _snapshot(payload, spec, "run", delivery)["decision"] == expected


@pytest.mark.parametrize("value", [True, "0.1", float("nan"), float("inf")])
def test_invalid_statistics_do_not_become_measured_success(experiment, value):
    spec, delivery, payload = experiment
    payload["result"]["results"][0]["metrics"] = [metric("success", 0, value, 1)]
    assert _snapshot(payload, spec, "run", delivery)["status"] == "sample_unverified"


def test_minimum_lift_and_ambiguous_analysis_hold_experiment(experiment):
    spec, delivery, payload = experiment
    spec["minimum_lift"] = 0.05
    row = metric("success", 0.02, 0.12, 0.22)
    payload["result"]["results"][0]["metrics"] = [row]
    assert _snapshot(payload, spec, "run", delivery)["decision"] == "hold"
    row["variations"][1]["analyses"].append(deepcopy(row["variations"][1]["analyses"][0]))
    assert _snapshot(payload, spec, "run", delivery)["status"] == "sample_unverified"


def identity(char):
    return {
        "git_sha": char * 40,
        "artifact_sha256": char * 64,
        "image_digest": "",
        "product_version": "1.0.0.7",
        "release_id": "xcagi-1.0.0.7-" + char * 40,
    }


@pytest.fixture
def failed_run(client, monkeypatch):
    request_id = str(uuid4())
    policy = {
        "mode": "restore_previous_release",
        "target": identity("b"),
        "captured_at": "2026-01-01T00:00:00Z",
    }
    plan = {"feedback_policy": {"recovery": policy}}
    state = {
        "protocol": {"request_id": request_id},
        "plan": plan,
        "optimization": {},
        "verification": {"status": "checks_passed"},
        "delivery": {
            "status": "deployment_verified",
            "release_sha": "a" * 40,
            "identity": identity("a"),
        },
        "impact": {"status": "customer_impact_rejected", "reason": "experiment_regression"},
    }
    state["approval"] = {"approved": True, "digest": digest(state["verification"])}
    effects = {
        "customer_feedback": {"recovery": policy},
        "plan": plan,
        "optimization": {},
        "authorization": {
            "approved": True,
            "digest": digest({key: state[key] for key in ("protocol", "plan", "optimization")}),
        },
    }
    with get_session_factory()() as db:
        user = User(username=uuid4().hex, password_hash="test-only", is_admin=True)
        db.add(user)
        db.flush()
        db.add(
            RetortEvolutionRun(
                id=request_id,
                user_id=user.id,
                protocol_json=json_dumps(state["protocol"]),
                effects_json=json_dumps(effects),
            )
        )
        db.commit()
    monkeypatch.setenv("MODSTORE_AUTO_ROLLBACK_COMMAND", "operator-managed-cas-recovery")
    return request_id, state


def test_recovery_reconciles_unknown_command_without_reexecuting(failed_run, monkeypatch):
    request_id, state = failed_run
    current = {"value": identity("a")}
    monkeypatch.setattr(recovery, "_release_identity", lambda: current["value"])
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        raise ConnectionError("lost receipt")

    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery", execute
    )
    first = recovery.recover_release(request_id, state)
    assert first["reason"] == "recovery_outcome_unknown"
    assert recovery.recover_release(request_id, state)["reason"] == "awaiting_recovery_readback"
    current["value"] = identity("b")
    assert recovery.recover_release(request_id, state)["status"] == "rollback_verified"
    assert len(calls) == 1
    assert calls[0]["payload"]["expected_identity"] == identity("a")
    assert calls[0]["payload"]["target_identity"] == identity("b")


def test_unavailable_or_changed_release_preserves_recovery_claim(failed_run, monkeypatch):
    request_id, state = failed_run
    recovery._save(request_id, {"submitted": True})
    monkeypatch.setattr(recovery, "_release_identity", lambda: identity("c"))
    assert recovery.recover_release(request_id, state)["reason"] == "active_release_changed"
    monkeypatch.setattr(recovery, "_release_identity", lambda: identity("a"))
    assert recovery.recover_release(request_id, state)["reason"] == "awaiting_recovery_readback"
    with get_session_factory()() as db:
        assert (
            json_loads(db.get(RetortEvolutionRun, request_id).effects_json, {})["recovery"][
                "submitted"
            ]
            is True
        )


def test_mutated_approval_never_executes_rollback(failed_run, monkeypatch):
    request_id, state = failed_run
    state["approval"]["digest"] = "0" * 64
    monkeypatch.setattr(
        recovery, "_release_identity", lambda: pytest.fail("must not read before authorization")
    )
    assert recovery.recover_release(request_id, state)["reason"] == "recovery_approval_mismatch"


def test_recovery_freezes_verified_prior_artifact(monkeypatch):
    monkeypatch.setattr(recovery, "_release_identity", lambda: identity("b"))
    assert recovery.freeze_recovery_policy({"mode": "restore_previous_release"})[
        "target"
    ] == identity("b")
    with pytest.raises(ValueError, match="invalid_feedback_recovery_policy"):
        recovery.freeze_recovery_policy(
            {"mode": "restore_previous_release", "target": identity("c")}
        )
