"""Holdouts never reach proposal text or gain trust from submitted flags."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from modstore_server import capability_trainer as trainer
from modstore_server import workflow_training_dataset as datasets


@pytest.fixture
def cases(monkeypatch):
    from modstore_server import workflow_training_replay

    # Manifest integrity and native execution have separate real-file tests.
    # These cases exercise partition/candidate authority without running employees.
    monkeypatch.setattr(workflow_training_replay, "validate_replay_manifest", lambda value: value)
    return [
        {
            "task": task,
            "generation_context": {
                "customer_business_replay": {
                    "source_group_sha256": prefix + "a" * 56,
                    "source_sha256": [prefix + "b" * 56],
                    "expected_files": [{"private_oracle": "ORACLE_MUST_NOT_REACH_MODEL"}],
                },
                "execution_feedback": {"error": "verified_business_difference"},
            },
        }
        for prefix, task in (
            ("00000001", "DEVELOPMENT_TASK"),
            ("00000005", "HOLDOUT_MUST_NOT_REACH_MODEL"),
        )
    ]


def test_proposal_excludes_holdout_and_oracle_even_when_cluster_contains_both(cases):
    cluster = {
        "surface": "workflow_nl_prompt",
        "resource_id": "workflow_nl_generator",
        "failure_reason": "business_failure",
        "count": 2,
        "samples": cases,
    }
    prompt = trainer.build_patch_prompt("baseline", [cluster])
    assert "DEVELOPMENT_TASK" in prompt
    assert "HOLDOUT_MUST_NOT_REACH_MODEL" not in prompt
    assert "ORACLE_MUST_NOT_REACH_MODEL" not in prompt
    assert cluster["samples"] == cases


def test_same_original_cannot_change_partition_when_renamed_or_new_cases_arrive(cases):
    before = datasets.partition_cases(cases)
    renamed = {**deepcopy(cases[0]), "task": "renamed-task", "source_run": "new-execution"}
    after = datasets.partition_cases([cases[1], renamed, cases[0]])
    assert after[1]["evaluation_partition"] == before[0]["evaluation_partition"]
    assert after[2]["evaluation_partition"] == before[0]["evaluation_partition"]
    assert after[0]["evaluation_partition"] == before[1]["evaluation_partition"]
    with pytest.raises(ValueError, match="holdout_required"):
        datasets.partition_cases([cases[0], renamed])


def test_selection_skips_missing_holdout_before_any_proposal(cases):
    blocked = {"samples": cases[:1]}
    ready = {"samples": cases}
    selected, reasons = datasets.select_clusters([blocked, ready])
    assert [sample["task"] for sample in selected[0]["samples"]] == [case["task"] for case in cases]
    assert reasons == {"training_business_holdout_required": 1}


def test_selection_fixes_cost_before_proposal_and_returns_only_evaluated_sources(cases):
    duplicate = {**deepcopy(cases[0]), "run_id": "later-run", "task": "other execution"}
    selected, _ = datasets.select_clusters([{"samples": [duplicate, *cases], "count": 3}])
    assert selected[0]["count"] == len(selected[0]["samples"]) == 2
    assert {sample["task"] for sample in selected[0]["samples"]} == {case["task"] for case in cases}
    cases[0]["generation_context"]["private_extra"] = "x" * 160_000
    selected, reasons = datasets.select_clusters([{"samples": cases}])
    assert selected == []
    assert reasons == {"training_business_payload_budget_exceeded": 1}


def test_overlapping_original_files_cannot_cross_partitions_when_batches_change(cases):
    second = cases[1]["generation_context"]["customer_business_replay"]
    second["source_sha256"].extend(
        cases[0]["generation_context"]["customer_business_replay"]["source_sha256"]
    )
    with pytest.raises(ValueError, match="training_business_source_overlap"):
        datasets.partition_cases(cases)


@pytest.mark.parametrize("selected", [0, 1])
def test_later_round_combination_preserves_each_original_partition(cases, selected):
    before = datasets.partition_cases(cases)
    expanded = deepcopy(cases[selected])
    replay = expanded["generation_context"]["customer_business_replay"]
    replay["source_sha256"].append(("00000002" if selected == 0 else "0000000a") + "c" * 56)
    # The new contract identity would have flipped the old group-based bucket.
    replay["source_group_sha256"] = ("00000005" if selected == 0 else "00000001") + "d" * 56
    after = datasets.partition_cases([cases[1 - selected], expanded])
    assert after[1]["evaluation_partition"] == before[selected]["evaluation_partition"]
    assert after[1]["source_group_sha256"] == replay["source_group_sha256"]


def test_later_round_rejects_mixed_originals_when_old_holdout_case_is_absent(cases):
    assert datasets.partition_cases(cases)[1]["evaluation_partition"] == "holdout"
    mixed = deepcopy(cases[1])
    replay = mixed["generation_context"]["customer_business_replay"]
    replay["source_sha256"].extend(
        cases[0]["generation_context"]["customer_business_replay"]["source_sha256"]
    )
    replay["source_group_sha256"] = "00000001" + "d" * 56
    new_holdout = deepcopy(cases[1])
    new_holdout["generation_context"]["customer_business_replay"].update(
        source_group_sha256="0000000a" + "e" * 56,
        source_sha256=["0000000a" + "f" * 56],
    )
    # Neither original standalone case is in this round. A per-round overlap map
    # would admit the mixed case to development and the unrelated case to holdout.
    with pytest.raises(ValueError, match="training_business_source_overlap"):
        datasets.partition_cases([mixed, new_holdout])


def _sealed_inputs(cases):
    variables = [
        {**case, "case_id": f"case-{index}"}
        for index, case in enumerate(datasets.partition_cases(cases))
    ]
    bundle = {
        "case_partitions": [case["evaluation_partition"] for case in variables],
        "case_source_groups": [case["source_group_sha256"] for case in variables],
    }
    tests = [{"vars": case} for case in variables]
    verified = {
        (arm, index): {
            "pass": bool(arm),
            "runtime_verified": True,
            "measurement_scope": datasets.BUSINESS_SCOPE,
            "business_evidence": {"manifest_sha256": f"manifest-{index}"},
        }
        for arm in (0, 1)
        for index in range(len(cases))
    }
    return bundle, tests, verified


def test_independent_holdout_failure_overrules_submitted_improvement(cases):
    bundle, tests, verified = _sealed_inputs(cases)
    verdict = {"improved": True, "verdict": "candidate_for_approval", "holdout_verified": True}
    good = datasets.seal_business_evidence(bundle, tests, verified, verdict)
    assert good["verdict"] == "candidate_for_approval"
    assert good["holdout_verified"] is True
    verified[1, 1]["pass"] = False
    bad = datasets.seal_business_evidence(bundle, tests, verified, verdict)
    assert bad["verdict"] == "keep_baseline"
    assert bad["holdout_verified"] is False
    assert bad["business_evidence"] == good["business_evidence"]


def test_claimed_partitions_cannot_override_original_content_group(cases):
    bundle, tests, verified = _sealed_inputs(cases)
    bundle["case_partitions"].reverse()
    for test, partition in zip(tests, bundle["case_partitions"]):
        test["vars"]["evaluation_partition"] = partition
    with pytest.raises(ValueError, match="partitions_unbound"):
        datasets.seal_business_evidence(bundle, tests, verified, {"improved": True})


def test_upstream_redaction_only_restores_frozen_context_and_never_task_or_shape(cases):
    original = {**datasets.partition_cases(cases)[0], "case_id": "case-0"}
    exported = deepcopy(original)
    exported["source_group_sha256"] = "[REDACTED]"
    exported["generation_context"]["customer_business_replay"]["source_group_sha256"] = "[REDACTED]"
    assert datasets.bound_result_variables(exported, original) is original
    exported["task"] = "[REDACTED]"
    with pytest.raises(ValueError, match="result_unverified"):
        datasets.bound_result_variables(exported, original)
    exported["task"] = original["task"]
    exported["generation_context"] = "[REDACTED]"
    with pytest.raises(ValueError, match="result_unverified"):
        datasets.bound_result_variables(exported, original)
    exported = deepcopy(original)
    exported["generation_context"]["execution_feedback"]["error"] = "[REDACTED]"
    with pytest.raises(ValueError, match="result_unverified"):
        datasets.bound_result_variables(exported, original)
    original["generation_context"]["numeric_input"] = 1
    exported = deepcopy(original)
    exported["generation_context"]["numeric_input"] = True
    with pytest.raises(ValueError, match="result_unverified"):
        datasets.bound_result_variables(exported, original)


def test_business_bundle_freezes_partitions_and_evaluator_inputs(tmp_path, monkeypatch, cases):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="baseline",
        candidate_prompt="candidate",
        cases=cases,
        surface="workflow_nl_prompt",
    )
    bundle = json.loads(Path(built["bundle"]).read_bytes())
    tests = json.loads(Path(built["tests"]).read_bytes())
    assert bundle["measurement_scope"] == datasets.BUSINESS_SCOPE
    assert bundle["holdout_verified"] is False
    assert bundle["case_partitions"] == ["development", "holdout"]
    assert {"workflow_training_replay.py", "workflow_training_dataset.py"}.issubset(
        bundle["validation_sha256"]
    )
    assert datasets.verify_partitions(bundle, [test["vars"] for test in tests]) == [
        "development",
        "holdout",
    ]


@pytest.mark.parametrize(
    "mutation", ["duplicate", "provider", "missing", "last_case", "second_vars"]
)
def test_invalid_result_matrix_never_starts_native_execution(
    tmp_path, monkeypatch, cases, mutation
):
    from modstore_server import workflow_nl_training

    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="baseline",
        candidate_prompt="candidate",
        cases=cases,
        surface="workflow_nl_prompt",
    )
    bundle = json.loads(Path(built["bundle"]).read_bytes())
    tests = json.loads(Path(built["tests"]).read_bytes())
    rows = [
        {
            "promptIdx": arm,
            "testIdx": index,
            "success": bool(arm),
            "failureReason": 0 if arm else 1,
            "gradingResult": {"pass": bool(arm)},
            "provider": {"id": bundle["provider_id"]},
            "vars": deepcopy(test["vars"]),
            "response": {"output": "fixture graph"},
        }
        for arm in (0, 1)
        for index, test in enumerate(tests)
    ]
    if mutation == "duplicate":
        rows.append(deepcopy(rows[-1]))
    elif mutation == "provider":
        rows[-1]["provider"]["id"] = "unapproved-model"
    elif mutation == "missing":
        rows.pop()
    elif mutation == "second_vars":
        rows[-1]["testCase"] = {"vars": {**deepcopy(rows[-1]["vars"]), "task": "different task"}}
    else:
        rows[-1]["vars"]["generation_context"]["extra"] = "unbound context"
    result = {
        "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
        "results": {
            "prompts": [{"raw": Path(built[key]).read_text()} for key in ("baseline", "candidate")],
            "results": rows,
        },
    }
    output = tmp_path / "result.json"
    output.write_text(json.dumps(result))

    def unexpected_execution(*_args, **_kwargs):
        pytest.fail("invalid result matrix started native replay")

    monkeypatch.setattr(workflow_nl_training, "get_assert", unexpected_execution)
    with pytest.raises(
        ValueError, match="training_(business_results_incomplete|workflow_result_unverified)"
    ):
        trainer.seal_evaluation(Path(built["bundle"]), output)
