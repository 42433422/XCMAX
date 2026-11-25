"""Customer experiments require sealed business replay, not a static prompt score."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.retort_training_candidates import (
    _customer_candidate_sources,
    _preverify_business_sources,
)
from modstore_server.workflow_nl_training import _digest
from tests import test_workflow_nl_training as workflow_tests

setup = workflow_tests.setup
workflow_training = workflow_tests.workflow_training


def _customer_policy():
    path = Path(os.environ["MODSTORE_RETORT_PROTOCOLS"])
    templates = json.loads(path.read_bytes())
    policy = templates["restore"]["training_candidate"]["growthbook"]
    policy.update(
        metric="customer-accepted-success",
        guardrails=[{"metric": "customer-accepted-failure", "direction": "decrease"}],
    )
    policy["lifecycle"].update(
        measurement_scope=WORKFLOW_CUSTOMER_MEASUREMENT,
        maturation_hours=1,
        customer_outcomes={
            "source": "modstore_customer_workflow_postgres_v1",
            "success_metric_id": "customer-accepted-success",
            "failure_metric_id": "customer-accepted-failure",
            "maximum_treatment_failures": 2,
            "employee_id": "native-customer-file",
            "observation_hours": 1,
        },
    )
    path.write_text(json.dumps(templates), encoding="utf-8")
    return policy


@pytest.mark.asyncio
async def test_static_generation_candidate_cannot_enter_customer_business_experiment(
    workflow_training,
):
    run = workflow_training
    _customer_policy()
    assert (await run["generate"]())["ok"] is False
    body = workflow_tests._body(run)
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 409, response.text
    assert "training_customer_evidence_required" in response.text
    assert not [call for call in run["calls"] if call[0] == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("customer", [False, True])
async def test_unbound_native_packages_never_reach_seal_or_execution(
    workflow_training, monkeypatch, customer
):
    from modstore_server import (
        retort_training_candidates,
        workflow_nl_training,
        workflow_training_replay,
    )

    run = workflow_training
    assert (await run["generate"]())["ok"] is False
    body = workflow_tests._body(run)
    tests = json.loads(body["files"]["tests"])
    tests[0]["vars"]["generation_context"]["customer_business_replay"] = {
        "replay_ready": True,
        "assets": {"packages": [{"base64": "cHJpbnQoJ2ZvcmNlZCcp", "sha256": "b" * 64}]},
    }
    body["files"]["tests"] = json.dumps(tests)
    if customer:
        _customer_policy()
        bundle = json.loads(body["bundle_json"])
        bundle["measurement_scope"] = "workflow_business_artifact_verification"
        body["bundle_json"] = json.dumps(bundle)
    attempted = []

    def blocked(*_args, **_kwargs):
        attempted.append(True)
        pytest.fail("Unbound native code reached the replay boundary")

    monkeypatch.setattr(retort_training_candidates, "_candidate", blocked)
    monkeypatch.setattr(workflow_nl_training, "get_assert", blocked)
    monkeypatch.setattr(workflow_training_replay, "evaluate_business_replay", blocked)
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 409, response.text
    assert (
        "training_customer_source_unbound" if customer else "training_customer_experiment_required"
    ) in response.text
    assert attempted == []
    assert not [call for call in run["calls"] if call[0] == "POST"]


@pytest.fixture
def customer_source_bindings(monkeypatch):
    """Isolate admission from the replay runner; its real execution has separate tests."""
    from modstore_server import workflow_execution_feedback, workflow_training_replay

    policy = {"employee_id": "native-customer-file", "observation_hours": 1}
    records = []
    evidence = {}
    for index in range(2):
        path = "outputs/report.csv"
        outcome = {
            "classification": "business_failure",
            "reason": "customer_goal_not_met",
            "success": False,
            "contract_sha256": _digest({"contract": index}),
            "evidence_sha256": _digest({"receipts": index}),
            "customer_policy": deepcopy(policy),
            "required_artifacts": [{"output_path": path}],
        }
        replay = {
            "execution_id": index + 1,
            "workflow_id": index + 3,
            "user_id": index + 7,
            "input_sha256": _digest({"input": index}),
            "graph_fingerprint": _digest({"graph": index}),
            "contract_sha256": outcome["contract_sha256"],
            "source_evidence_sha256": outcome["evidence_sha256"],
            "source_group_sha256": f"{index:08x}" + "0" * 56,
            "source_sha256": [f"{index:08x}" + "1" * 56],
            "manifest_sha256": _digest({"manifest": index}),
            "expected_output_paths": [path],
            "expected_reference_sha256": {path: _digest({"reference": index})},
        }
        context = {
            "execution_feedback": {
                "execution_id": index + 1,
                "input": {"input": index},
                "graph_fingerprint": replay["graph_fingerprint"],
                "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                "failure_kind": "business_outcome_failed",
                "customer_outcome": outcome,
            },
            "customer_business_replay": replay,
        }
        records.append(
            {
                "run_id": f"workflow-customer:{index + 1}",
                "task_excerpt": f"Original customer task {index}",
                "generation_context": context,
                "user_id": index + 7,
                "workflow_id": index + 3,
            }
        )
        evidence[f"case-{index}"] = {
            **{key: replay[key] for key in ("manifest_sha256", "source_group_sha256")},
            "contract_sha256": outcome["contract_sha256"],
            "source_evidence_sha256": outcome["evidence_sha256"],
            "expected_reference_sha256": deepcopy(replay["expected_reference_sha256"]),
            # Semantic verification need not yield byte-identical XLSX ZIP files.
            "output_sha256": {path: _digest({"actual-output": index})},
        }
    queried = []

    def originals(**kwargs):
        queried.append(kwargs)
        return records

    monkeypatch.setattr(workflow_execution_feedback, "execution_failure_records", originals)
    monkeypatch.setattr(
        workflow_training_replay,
        "validate_replay_manifest",
        lambda value: {
            key: value[key]
            for key in (
                "manifest_sha256",
                "source_group_sha256",
                "expected_reference_sha256",
                "expected_output_paths",
                "source_sha256",
            )
        },
    )
    offline = {
        "measurement_scope": "workflow_business_artifact_verification",
        "feedback_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
        "runtime_verified": True,
        "holdout_verified": True,
        "prompt_sha256": {"control": "a" * 64},
        "business_evidence": evidence,
    }
    return {
        "body": {
            "surface": "workflow_nl_prompt",
            "resource_id": "workflow_nl_generator",
            "failure_run_ids": [record["run_id"] for record in records],
            "files": {
                "tests": json.dumps(
                    [
                        {
                            "vars": {
                                "case_id": f"case-{index}",
                                "task": record["task_excerpt"],
                                "generation_context": record["generation_context"],
                                "evaluation_partition": "holdout" if index == 0 else "development",
                                "source_group_sha256": record["generation_context"][
                                    "customer_business_replay"
                                ]["source_group_sha256"],
                            }
                        }
                        for index, record in enumerate(records)
                    ]
                )
            },
        },
        "bundle": {
            "surface": "workflow_nl_prompt",
            "measurement_scope": "workflow_business_artifact_verification",
            "prompt_sha256": {"control": "a" * 64},
            "case_ids": list(evidence),
            "case_sha256": [sha256(row["task_excerpt"].encode()).hexdigest() for row in records],
            "case_context_sha256": [_digest(row["generation_context"]) for row in records],
            "case_partitions": ["holdout", "development"],
            "case_source_groups": [
                row["generation_context"]["customer_business_replay"]["source_group_sha256"]
                for row in records
            ],
        },
        "spec": {
            "lifecycle": {
                "surface": "workflow_nl_prompt",
                "resource_id": "workflow_nl_generator",
                "measurement_scope": WORKFLOW_CUSTOMER_MEASUREMENT,
                "cohort_user_ids": [7, 8],
                "customer_outcomes": policy,
                "offline_evidence": offline,
            }
        },
        "records": records,
        "queried": queried,
    }


def _admit(case):
    sources = _preverify_business_sources(case["body"], case["bundle"], case["spec"])
    _customer_candidate_sources(case["bundle"], case["spec"], sources)


def test_sealed_business_scope_rechecks_sql_sources_and_original_group_assignments(
    customer_source_bindings,
):
    case = customer_source_bindings
    before = deepcopy(case["spec"])
    _admit(case)
    assert case["queried"] == [{"days": 14, "cohort": [7, 8], "baseline": "a" * 64}]
    assert case["spec"] == before  # Admission creates no promotion or new authority.


def test_postseal_uses_the_original_snapshot_without_requery(customer_source_bindings):
    case = customer_source_bindings
    sources = _preverify_business_sources(case["body"], case["bundle"], case["spec"])
    case["records"].clear()
    _customer_candidate_sources(case["bundle"], case["spec"], sources)
    assert len(case["queried"]) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "runtime",
        "holdout",
        "target_scope",
        "surface",
        "proof_scope",
        "missing_case_proof",
        "cohort",
        "employee_policy",
        "sql_source_missing",
        "original_context_changed",
        "contract",
        "receipt",
        "reference",
        "output",
        "partition",
        "source_group",
        "extra_source_id",
        "unevaluated_source_id",
        "forged_package",
    ],
)
def test_customer_admission_rejects_unverified_or_drifted_business_bindings(
    customer_source_bindings, fault
):
    case = customer_source_bindings
    life = case["spec"]["lifecycle"]
    offline = life["offline_evidence"]
    measured = offline["business_evidence"]["case-0"]
    if fault in {"runtime", "holdout"}:
        offline[f"{fault}_verified"] = False
    elif fault == "target_scope":
        life["measurement_scope"] = "workflow_execution_terminal"
    elif fault == "surface":
        case["body"]["surface"] = "employee_prompt"
    elif fault == "proof_scope":
        offline["measurement_scope"] = "workflow_generation_static_validation"
    elif fault == "missing_case_proof":
        offline["business_evidence"].pop("case-1")
    elif fault == "cohort":
        life["cohort_user_ids"] = [7, 9]
    elif fault == "employee_policy":
        life["customer_outcomes"]["employee_id"] = "another-employee"
    elif fault == "sql_source_missing":
        case["records"].clear()  # Claimed failure ids and sealed files do not substitute for SQL.
    elif fault == "original_context_changed":
        case["records"][0]["generation_context"]["another_input"] = True
    elif fault == "contract":
        measured["contract_sha256"] = "b" * 64
    elif fault == "receipt":
        measured["source_evidence_sha256"] = "b" * 64
    elif fault == "reference":
        measured["expected_reference_sha256"]["outputs/report.csv"] = "b" * 64
    elif fault == "output":
        measured["output_sha256"] = {"outputs/another.csv": "b" * 64}
    elif fault == "partition":
        case["bundle"]["case_partitions"].reverse()
    elif fault == "extra_source_id":
        case["body"]["failure_run_ids"].append("workflow-customer:999")
    elif fault == "unevaluated_source_id":
        extra = deepcopy(case["records"][0])
        extra["run_id"] = "workflow-customer:999"
        extra["generation_context"]["execution_feedback"]["execution_id"] = 999
        case["records"].append(extra)
        case["body"]["failure_run_ids"].append(extra["run_id"])
    elif fault == "forged_package":
        tests = json.loads(case["body"]["files"]["tests"])
        tests[0]["vars"]["generation_context"]["customer_business_replay"]["packages"] = ["forged"]
        case["body"]["files"]["tests"] = json.dumps(tests)
    else:
        case["bundle"]["case_source_groups"][0] = "b" * 64
    with pytest.raises(ValueError, match="training_customer_"):
        _admit(case)
