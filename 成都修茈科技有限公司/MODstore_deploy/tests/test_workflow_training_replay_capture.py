"""Forward fixture snapshots must precede the real customer's native delivery."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from modstore_server import workflow_nl_training as training
from modstore_server import workflow_training_replay as replay
from modstore_server.models import OutboxEvent, WorkflowExecution, get_session_factory
from tests import test_workflow_customer_delivery as customer_tests

experiment_run = customer_tests.experiment_run
workflow_experiment = customer_tests.workflow_experiment
execution_experiment = customer_tests.execution_experiment
customer_workflow = customer_tests.customer_workflow


def _oracle(env, monkeypatch, *, changed=False):
    source = env["workspace"] / "inputs/orders.json"
    group = replay._digest([replay._sha(source.read_bytes())])
    golden = env["workspace"] / "references/verified.csv"
    golden.parent.mkdir()
    golden.write_text(f"order,quantity\nA-{env['customer_id']},3\n")
    assert not (env["workspace"] / "outputs/output.csv").exists()
    policy = {
        "growthbook": {"lifecycle": env["run"]["spec"]["lifecycle"]},
        "offline_business_replay": {
            "references": {
                group: [
                    {
                        "output_path": "outputs/output.csv",
                        "reference_path": "references/verified.csv",
                        "sha256": "0" * 64 if changed else replay._sha(golden.read_bytes()),
                    }
                ]
            }
        },
    }
    monkeypatch.setattr(training, "_policies", lambda: [policy])
    return source


def test_production_freezes_original_source_and_oracle_before_delivery(
    customer_workflow, monkeypatch
):
    env = customer_workflow
    original = _oracle(env, monkeypatch)
    original_bytes = original.read_bytes()
    response = env["execute"]()
    assert response.status_code == 200, response.text
    binding = env["binding"]
    assert binding["customer_delivery"]["business_replay"]["replay_ready"] is True
    # A later import cannot replace the historical source used by this failure.
    original.write_text('{"columns":["wrong"],"rows":[[999]]}')
    inputs = {
        "file_path": "inputs/orders.json",
        "customer_delivery": {
            "order_no": env["goal"]["order_no"],
            "customer_goal_id": env["goal"]["customer_goal_id"],
        },
    }
    manifest = replay.export_customer_replay(binding, inputs, "e" * 64)
    assert replay._bytes(manifest["assets"]["input_files"][0]) == original_bytes
    source = {
        "graph": {
            "name": "Frozen original customer replay",
            "nodes": [],
            "edges": [],
            "triggers": [],
        },
        "skills": [],
        "brief": "Generate the confirmed order CSV",
        "customer_business_replay": manifest,
    }
    result = training.get_assert(
        json.dumps(env["run"]["graph"]), {"vars": {"generation_context": source}}
    )
    assert result["pass"] is True, result
    assert result["runtime_verified"] is True


def test_changed_reference_does_not_block_customer_delivery_but_cannot_train(
    customer_workflow, monkeypatch
):
    env = customer_workflow
    _oracle(env, monkeypatch, changed=True)
    response = env["execute"]()
    assert response.status_code == 200, response.text
    captured = env["binding"]["customer_delivery"]["business_replay"]
    assert captured["replay_ready"] is False
    assert captured["reason"] == "training_replay_capture_unavailable"


@pytest.mark.parametrize("change", ["reference_deleted", "reference_changed", "business_input"])
def test_running_delivery_reuses_training_snapshot_but_rechecks_business_input(
    customer_workflow, monkeypatch, change
):
    env = customer_workflow
    source = _oracle(env, monkeypatch)
    reference = env["workspace"] / "references/verified.csv"
    original_reference = reference.read_bytes()
    capture = replay.capture_business_replay
    captured = []

    def capture_then_change(*args, **kwargs):
        frozen = capture(*args, **kwargs)
        captured.append(deepcopy(frozen))
        if len(captured) == 1:
            assert frozen["replay_ready"] is True
            if change == "reference_deleted":
                reference.unlink()
            elif change == "reference_changed":
                reference.write_text("order,quantity\nchanged-reference,999\n")
            else:
                payload = json.loads(source.read_bytes())
                payload["rows"][0]["quantity"] = 99
                source.write_text(json.dumps(payload))
        return frozen

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_change)
    response = env["execute"]()
    if change == "business_input":
        assert response.status_code == 500, response.text
        assert not (env["workspace"] / "outputs/output.csv").exists()
        with get_session_factory()() as db:
            execution = db.scalar(
                select(WorkflowExecution)
                .where(WorkflowExecution.workflow_id == env["run"]["workflows"][env["customer_id"]])
                .order_by(WorkflowExecution.id.desc())
            )
            assert execution.status == "failed"
            assert not db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == str(execution.id),
                    OutboxEvent.event_name == customer_tests.delivery.PRODUCED_EVENT,
                )
            )
    else:
        assert response.status_code == 200, response.text
        assert env["binding"]["customer_delivery"]["business_replay"] == captured[0]
        manifest = replay.export_customer_replay(
            env["binding"], captured[0]["assets"]["input_data"], "e" * 64
        )
        assert replay._bytes(manifest["assets"]["expected_files"][0]) == original_reference
        listing = env["http"].get(
            "/api/customer-value/deliveries", params=customer_tests._query(env)
        )
        assert listing.status_code == 200 and len(listing.json()["items"]) == 1, listing.text
        received = env["http"].get(listing.json()["items"][0]["download_url"])
        assert received.status_code == 200, received.text
        assert (
            received.content.decode("utf-8-sig").replace("\r\n", "\n")
            == original_reference.decode()
        )
        assert len(captured) == 1


@pytest.mark.parametrize("change", ["delete", "replace", "disable_policy"])
def test_running_delivery_reuses_its_original_optional_training_snapshot(
    customer_workflow, monkeypatch, change
):
    env = customer_workflow
    _oracle(env, monkeypatch)
    golden = env["workspace"] / "references/verified.csv"
    original_bytes = golden.read_bytes()
    capture = replay.capture_business_replay
    snapshots = []

    def capture_then_change_reference(*args):
        snapshot = capture(*args)
        snapshots.append(deepcopy(snapshot))
        if len(snapshots) == 1:
            assert snapshot["replay_ready"] is True
            if change == "delete":
                golden.unlink()
            elif change == "replace":
                golden.write_text("order,quantity\nchanged-after-admission,999\n")
            else:
                monkeypatch.setattr(training, "_policies", lambda: [])
        return snapshot

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_change_reference)

    response = env["execute"]()

    assert response.status_code == 200, response.text
    assert len(snapshots) == 1
    stored = env["binding"]["customer_delivery"]["business_replay"]
    assert stored == snapshots[0]
    assert replay._bytes(stored["assets"]["expected_files"][0]) == original_bytes
    assert env["artifact"]["artifact_sha256"] == replay._sha(
        (env["workspace"] / "outputs/output.csv").read_bytes()
    )
    listing = env["http"].get("/api/customer-value/deliveries", params=customer_tests._query(env))
    assert listing.status_code == 200, listing.text
    downloaded = env["http"].get(listing.json()["items"][0]["download_url"])
    assert downloaded.status_code == 200, downloaded.text
    assert replay._equal_files("outputs/output.csv", downloaded.content, original_bytes)


@pytest.mark.parametrize("capture_state", ["ready", "missing_reference", "changed_reference"])
def test_frozen_training_snapshot_still_rejects_changed_business_input(
    customer_workflow, monkeypatch, capture_state
):
    env = customer_workflow
    source = _oracle(env, monkeypatch, changed=capture_state == "changed_reference")
    if capture_state == "missing_reference":
        (env["workspace"] / "references/verified.csv").unlink()
    capture = replay.capture_business_replay

    def capture_then_change_input(*args):
        snapshot = capture(*args)
        assert snapshot["replay_ready"] is (capture_state == "ready")
        source.write_text('{"columns":["order","quantity"],"rows":[["changed",999]]}')
        return snapshot

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_change_input)

    response = env["execute"]()
    assert response.status_code == 500, response.text
    assert not (env["workspace"] / "outputs/output.csv").exists()


def test_missing_training_snapshot_cannot_be_recaptured_during_delivery(
    customer_workflow, monkeypatch
):
    env = customer_workflow
    _oracle(env, monkeypatch)
    golden = env["workspace"] / "references/verified.csv"
    original_bytes = golden.read_bytes()
    golden.unlink()
    capture = replay.capture_business_replay
    snapshots = []

    def capture_then_restore_reference(*args):
        snapshot = capture(*args)
        snapshots.append(deepcopy(snapshot))
        golden.write_bytes(original_bytes)
        return snapshot

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_restore_reference)

    response = env["execute"]()

    assert response.status_code == 200, response.text
    assert len(snapshots) == 1
    stored = env["binding"]["customer_delivery"]["business_replay"]
    assert stored == snapshots[0] and stored["replay_ready"] is False


def test_delivery_recheck_does_not_add_a_late_training_snapshot(customer_workflow, monkeypatch):
    env = customer_workflow
    monkeypatch.setattr(training, "_policies", lambda: [])
    capture = replay.capture_business_replay
    calls = []

    def capture_then_configure(*args):
        frozen = capture(*args)
        calls.append(frozen)
        if len(calls) == 1:
            _oracle(env, monkeypatch)
        return frozen

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_configure)
    response = env["execute"]()
    assert response.status_code == 200, response.text
    assert calls == [None]
    assert "business_replay" not in env["binding"]["customer_delivery"]


@pytest.mark.parametrize("change", ["remove", "replace"])
def test_delivery_reuses_training_snapshot_after_optional_reference_changes(
    customer_workflow, monkeypatch, change
):
    env = customer_workflow
    _oracle(env, monkeypatch)
    reference = env["workspace"] / "references/verified.csv"
    capture = replay.capture_business_replay
    captured = []

    def capture_then_change_reference(db, contract, inputs):
        snapshot = capture(db, contract, inputs)
        captured.append(deepcopy(snapshot))
        if len(captured) == 1:
            assert snapshot["replay_ready"] is True
            if change == "remove":
                reference.unlink()
            else:
                reference.write_text("order,quantity\nchanged,999\n")
        return snapshot

    monkeypatch.setattr(replay, "capture_business_replay", capture_then_change_reference)
    response = env["execute"]()
    assert response.status_code == 200, response.text
    assert len(captured) == 1
    assert env["binding"]["customer_delivery"]["business_replay"] == captured[0]
