"""Original SQL receipts and frozen independent files reach the real candidate seal."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from modstore_server import capability_trainer as trainer
from modstore_server import workflow_nl_graph as generator
from modstore_server.customer_service_tools import json_loads
from modstore_server.models import (
    CustomerValueReceipt,
    OutboxEvent,
    RetortEvolutionRun,
    WorkflowExecution,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_CUSTOMER_MEASUREMENT,
    WORKFLOW_NL_PROMPT_PATH,
)
from tests import test_workflow_customer_failure_training as customer_training

experiment_run = customer_training.experiment_run
workflow_experiment = customer_training.workflow_experiment
execution_experiment = customer_training.execution_experiment
customer_workflow = customer_training.customer_workflow
capture_original_generation = customer_training.capture_original_generation
customer_business_source = customer_training.customer_business_source


def _production_rows():
    with get_session_factory()() as db:
        return tuple(
            db.query(model).count()
            for model in (WorkflowExecution, CustomerValueReceipt, OutboxEvent)
        )


def test_real_sql_business_sources_reach_frozen_customer_candidate(
    customer_business_source, client, tmp_path, monkeypatch
):
    env = customer_business_source
    baseline = env["run"]["spec"]["lifecycle"]["treatment_prompt"]
    # The original release plan publishes treatment into the shared source before
    # experiment traffic. External GitHub is a contract fixture; SQL/runtime are real.
    monkeypatch.setattr(generator, "SYSTEM_PROMPT", baseline)

    class EvaluationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return customer_training.customer_tests.Clock.now(tz)

    monkeypatch.setattr(trainer, "datetime", EvaluationClock)
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "example/product")
    monkeypatch.setenv("XCAGI_LLM_MODEL", "isolated-contract-test-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://isolated-model.test/v1")
    paths = trainer.build_config(
        out_dir=tmp_path / "business-evaluation",
        baseline_prompt=baseline,
        candidate_prompt=baseline + "\nUse the customer's agreed <FIELD>CSV delimiter</FIELD>.",
        cases=[
            {
                "task": sample["task_excerpt"],
                "generation_context": sample["generation_context"],
            }
            for sample in env["business_samples"]
        ],
        surface="workflow_nl_prompt",
    )
    bundle = json.loads(Path(paths["bundle"]).read_bytes())
    tests = json.loads(Path(paths["tests"]).read_bytes())
    # Only model responses are fixed test inputs. The gate independently runs
    # both original native graphs and checks the pre-existing operator oracles.
    rows = [
        {
            "promptIdx": arm,
            "testIdx": index,
            "success": bool(arm),
            "failureReason": 0 if arm else 1,
            "gradingResult": {"pass": bool(arm)},
            "error": None if arm else "Independent business format assertion failed",
            "provider": {"id": bundle["provider_id"]},
            "vars": case["vars"],
            "response": {"output": env["business_outputs"][name]},
        }
        for index, case in enumerate(tests)
        for arm, name in enumerate(("control", "candidate"))
    ]
    result = {
        "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
        "results": {
            "prompts": [{"raw": Path(paths[key]).read_text()} for key in ("baseline", "candidate")],
            "results": rows,
        },
    }
    body = {
        "request_key": "business-source-public-entry",
        "source_sha": "a" * 40,
        "workflow_run_id": 17,
        "surface": "workflow_nl_prompt",
        "resource_id": "workflow_nl_generator",
        "failure_run_ids": [row["run_id"] for row in env["business_samples"]],
        "bundle_json": Path(paths["bundle"]).read_text(),
        "files": {key: Path(paths[key]).read_text() for key in bundle["files"]},
        "result_json": json.dumps(result),
    }
    policy = deepcopy(env["run"]["spec"])
    templates = tmp_path / "protocols.json"
    templates.write_text(
        json.dumps(
            {
                "business": {
                    "name": "Verify original customer file outcome",
                    "criterion_ids": ["shared-engine-B2"],
                    "container_image": "example/test@sha256:" + "c" * 64,
                    "checks": [
                        {
                            "id": "business-regression",
                            "criterion_ids": ["shared-engine-B2"],
                            "files": {"check.py": "b" * 64},
                            "argv": ["python", "check.py"],
                            "timeout_seconds": 10,
                        }
                    ],
                    "training_candidate": {
                        "surface": "workflow_nl_prompt",
                        "resource_id": "workflow_nl_generator",
                        "owner_id": env["admin"].id,
                        "goal": "Match the original agreed customer file format",
                        "prompt_path": WORKFLOW_NL_PROMPT_PATH,
                        "growthbook": policy,
                    },
                }
            }
        )
    )
    monkeypatch.setenv("MODSTORE_RETORT_PROTOCOLS", str(templates))
    token = "synthetic-business-training-credential"
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256", hashlib.sha256(token.encode()).hexdigest()
    )

    def github(method, path, body=None):
        assert method == "GET"
        if path.endswith("/commits/main"):
            return {"sha": "a" * 40}
        assert "/contents/" in path and path.endswith("?ref=" + "a" * 40)
        return {
            "encoding": "base64",
            "content": base64.b64encode(("SYSTEM_PROMPT = " + repr(baseline)).encode()).decode(),
        }

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    scheduled = []
    monkeypatch.setattr("modstore_server.retort_evolution_api._advance", scheduled.append)
    # Existing Retort owns the lifecycle. Close the failed experiment and represent
    # its verified terminal handoff before reserving the same surface again.
    env["run"]["advance"](reject=True)
    closed = env["run"]["advance"](reject=True)
    assert closed["decision"] == "rollback" and closed["rollout_verified"]
    with get_session_factory()() as db:
        db.get(RetortEvolutionRun, env["run"]["id"]).status = "customer_impact_rejected"
        db.commit()
    mined = trainer.mine(tmp_path / "empty-ledger.jsonl", min_count=1)
    assert {sample["run_id"] for cluster in mined for sample in cluster["samples"]} == set(
        body["failure_run_ids"]
    )
    original = _production_rows()
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    response = client.post(
        "/api/service/mac-control/training/candidates",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert response.status_code == 202, response.text
    request_id = response.json()["request_id"]
    assert response.json()["approval_required"] is True
    assert scheduled == [request_id]
    with get_session_factory()() as db:
        source = json_loads(db.get(RetortEvolutionRun, request_id).effects_json, {})[
            "training_candidate"
        ]
        frozen = source["growthbook"]

    # Same submission is read back without another native replay or new request.
    def unexpected_replay(*_args, **_kwargs):
        raise AssertionError("Idempotent submission repeated native replay")

    monkeypatch.setattr("modstore_server.retort_training_candidates._candidate", unexpected_replay)
    repeated = client.post(
        "/api/service/mac-control/training/candidates",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert repeated.status_code == 202 and repeated.json()["request_id"] == request_id

    evidence = frozen["lifecycle"]["offline_evidence"]
    assert evidence["verdict"] == "candidate_for_approval"
    assert evidence["baseline"] == {"pass": 0, "total": 2}
    assert evidence["candidate"] == {"pass": 2, "total": 2}
    assert evidence["runtime_verified"] is evidence["holdout_verified"] is True
    assert evidence["measurement_scope"] == "workflow_business_artifact_verification"
    assert evidence["feedback_scope"] == WORKFLOW_CUSTOMER_MEASUREMENT
    assert set(bundle["case_partitions"]) == {"development", "holdout"}
    assert frozen["lifecycle"]["measurement_scope"] == WORKFLOW_CUSTOMER_MEASUREMENT
    assert _production_rows() == original  # Replay emits no production execution or receipt.
