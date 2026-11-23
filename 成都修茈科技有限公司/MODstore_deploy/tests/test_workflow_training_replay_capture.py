"""Forward fixture snapshots must precede the real customer's native delivery."""

from __future__ import annotations

import json

from modstore_server import workflow_nl_training as training
from modstore_server import workflow_training_replay as replay
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
