"""Source-bound dataset partitions for the existing private promptfoo trainer.

SQL owns the samples; promptfoo owns execution. This adapter only keeps identical
customer inputs in one stable partition and excludes holdouts from proposal text.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy

from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_BUSINESS_MEASUREMENT as BUSINESS_SCOPE,
)


def is_business_case(case):
    context = case.get("generation_context") or {}
    return bool(
        "customer_business_replay" in context
        or (context.get("execution_feedback") or {}).get("measurement_scope")
        == "workflow_customer_accepted_outcome"
    )


def partition_cases(cases):
    """Each original stays in its fixed partition across changing file combinations."""
    if not any(is_business_case(case) for case in cases):
        return list(cases)
    from modstore_server.workflow_training_replay import validate_replay_manifest

    result = []
    for case in cases:
        if not is_business_case(case):
            raise ValueError("training_business_scope_mixed")
        replay = (case.get("generation_context") or {}).get("customer_business_replay")
        if not isinstance(replay, dict):
            raise ValueError("training_business_replay_required")
        identity = validate_replay_manifest(replay)
        group = replay["source_group_sha256"]
        # A group digest changes when another original joins the contract. Bucket
        # each original instead, so even a later round without the old case cannot
        # expose its holdout data to the proposer through a different combination.
        partitions = {
            "holdout" if int(source[:8], 16) % 5 == 0 else "development"
            for source in identity["source_sha256"]
        }
        if len(partitions) != 1:
            raise ValueError("training_business_source_overlap")
        partition = partitions.pop()
        result.append({**case, "source_group_sha256": group, "evaluation_partition": partition})
    if {case["evaluation_partition"] for case in result} != {"development", "holdout"}:
        raise ValueError("training_business_holdout_required")
    return result


def proposal_clusters(clusters):
    """Only development failures reach the proposer; private oracles stay in eval."""
    result = []
    for cluster in clusters:
        samples = partition_cases(cluster.get("samples", []))
        if not any(is_business_case(sample) for sample in samples):
            result.append(cluster)
            continue
        validate_business_budget(samples)
        visible = [sample for sample in samples if sample["evaluation_partition"] == "development"]
        result.append({**cluster, "samples": visible, "count": len(visible)})
    return result


def select_clusters(clusters):
    """Keep the original bounded one-candidate run; skip unready business samples."""
    blocked = {}
    for cluster in clusters:
        try:
            samples = partition_cases(cluster.get("samples", []))
            if any(is_business_case(sample) for sample in samples):
                ordered = sorted(
                    samples,
                    key=lambda sample: (
                        sample["source_group_sha256"],
                        str(sample.get("run_id", "")),
                    ),
                )
                # Bound original native work before a paid proposal; never select by scores.
                samples = [
                    next(
                        sample for sample in ordered if sample["evaluation_partition"] == partition
                    )
                    for partition in ("development", "holdout")
                ]
                validate_business_budget(samples)
                cluster = {**cluster, "samples": samples, "count": len(samples)}
        except (ValueError, KeyError, TypeError) as exc:
            reason = str(exc)
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,100}", reason):
                reason = "training_business_replay_invalid"
            blocked[reason] = blocked.get(reason, 0) + 1
            continue
        return [cluster], blocked
    return [], blocked


def validate_business_budget(cases):
    # Official promptfoo results repeat the frozen vars; leave space inside the
    # existing 1.5 MB result / 2 MB request contracts and 300-second HTTP deadline.
    if len(cases) > 2 or len(json.dumps(cases, ensure_ascii=False).encode()) > 160_000:
        raise ValueError("training_business_payload_budget_exceeded")


def verify_partitions(bundle, variables):
    cases = partition_cases(variables)
    validate_business_budget(cases)
    partitions = [case["evaluation_partition"] for case in cases]
    groups = [case["source_group_sha256"] for case in cases]
    if (
        bundle.get("case_partitions") != partitions
        or bundle.get("case_source_groups") != groups
        or any(
            original.get("evaluation_partition") != case["evaluation_partition"]
            or original.get("source_group_sha256") != case["source_group_sha256"]
            for original, case in zip(variables, cases)
        )
    ):
        raise ValueError("training_business_partitions_unbound")
    return partitions


def bound_result_variables(exported, frozen):
    """Keep promptfoo's export redaction; execute only the original frozen inputs.

    The pinned CLI hides long SHA/base64 strings in its result copy. Redaction
    carries no evidence: the API has already verified frozen vars against SQL,
    and seal independently reruns the native graph with those exact vars.
    """

    def matches(actual, expected):
        if isinstance(actual, dict) and isinstance(expected, dict):
            return actual.keys() == expected.keys() and all(
                matches(actual[key], value) for key, value in expected.items()
            )
        if isinstance(actual, list) and isinstance(expected, list):
            return len(actual) == len(expected) and all(
                matches(left, right) for left, right in zip(actual, expected)
            )
        if isinstance(actual, bool) or isinstance(expected, bool):
            return type(actual) is type(expected) and actual == expected
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            return actual == expected  # JSON numbers may serialize 1.0 as 1 in JavaScript.
        return type(actual) is type(expected) and (
            actual == expected
            or (
                actual == "[REDACTED]"
                and isinstance(expected, str)
                and re.fullmatch(r"[A-Za-z0-9+/=_-]{64,}", expected) is not None
            )
        )

    if (
        not isinstance(exported, dict)
        or exported.keys() != frozen.keys()
        or any(
            exported.get(key) != value
            for key, value in frozen.items()
            if key not in {"generation_context", "source_group_sha256"}
        )
        or not matches(exported, frozen)
    ):
        raise ValueError("training_workflow_result_unverified")
    return frozen


def seal_business_evidence(bundle, tests, verified, verdict):
    """Only independent reruns can attest runtime and holdout success."""
    partitions = verify_partitions(bundle, [test["vars"] for test in tests])
    expected = {(arm, index) for arm in (0, 1) for index in range(len(tests))}
    if set(verified) != expected:
        raise ValueError("training_business_results_incomplete")
    if any(
        report.get("measurement_scope") != BUSINESS_SCOPE
        or report.get("runtime_verified") is not True
        or type(report.get("pass")) is not bool
        for report in verified.values()
    ):
        return {
            **verdict,
            "improved": False,
            "verdict": "keep_baseline",
            "runtime_verified": False,
            "holdout_verified": False,
            "reason": "training_business_execution_unverified",
        }
    # A caller-provided success flag is not proof of a native customer replay.
    # Bind BOTH arms to the frozen original source manifest and readback hashes,
    # without accepting a model's self-declared runtime or artifact identity.
    from modstore_server.workflow_training_replay import validate_replay_manifest

    for index, test in enumerate(tests):
        replay = (test["vars"].get("generation_context") or {}).get("customer_business_replay")
        identity = validate_replay_manifest(replay)
        for arm in (0, 1):
            evidence = verified[arm, index].get("business_evidence")
            if not isinstance(evidence, dict):
                raise ValueError("training_business_evidence_missing")
            output = evidence.get("output_sha256")
            references = identity.get("expected_reference_sha256")
            source_bound = (
                all(
                    evidence.get(key) == identity.get(key)
                    for key in ("manifest_sha256", "source_group_sha256")
                )
                and evidence.get("expected_reference_sha256") == references
                and all(
                    evidence.get(key) == replay.get(key)
                    for key in ("contract_sha256", "source_evidence_sha256")
                )
                and all(
                    isinstance(evidence.get(key), str)
                    and re.fullmatch(r"[0-9a-f]{64}", evidence[key])
                    for key in (
                        "manifest_sha256",
                        "source_group_sha256",
                        "contract_sha256",
                        "source_evidence_sha256",
                    )
                )
                and isinstance(references, dict)
                and bool(references)
                and all(
                    isinstance(path, str)
                    and bool(path)
                    and isinstance(sha, str)
                    and re.fullmatch(r"[0-9a-f]{64}", sha)
                    for path, sha in references.items()
                )
                and isinstance(output, dict)
                and set(output).issubset(references)
                and all(
                    isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)
                    for sha in output.values()
                )
                and (verified[arm, index]["pass"] is False or set(output) == set(references))
            )
            if not source_bound:
                return {
                    **verdict,
                    "improved": False,
                    "verdict": "keep_baseline",
                    "runtime_verified": False,
                    "holdout_verified": False,
                    "reason": "training_business_evidence_origin_unverified",
                }
    development = [
        index for index, partition in enumerate(partitions) if partition == "development"
    ]
    holdout = [index for index, partition in enumerate(partitions) if partition == "holdout"]
    holdout_passed = bool(holdout) and all(verified[1, index]["pass"] is True for index in holdout)
    no_regression = all(
        not verified[0, index]["pass"] or verified[1, index]["pass"] for index in range(len(tests))
    )
    # Passing a holdout that the baseline already passed is not holdout improvement.
    # Both partitions need at least one independently replayed paired win.
    development_wins = sum(
        verified[1, index]["pass"] and not verified[0, index]["pass"] for index in development
    )
    holdout_wins = sum(
        verified[1, index]["pass"] and not verified[0, index]["pass"] for index in holdout
    )
    evidence = {
        tests[index]["vars"]["case_id"]: deepcopy(verified[1, index].get("business_evidence"))
        for index in range(len(tests))
    }
    if any(not isinstance(item, dict) for item in evidence.values()):
        raise ValueError("training_business_evidence_missing")
    eligible = bool(
        verdict.get("improved") is True
        and holdout_passed
        and no_regression
        and development_wins > 0
        and holdout_wins > 0
    )
    return {
        **verdict,
        "improved": eligible,
        "feedback_scope": "workflow_customer_accepted_outcome",
        "runtime_verified": True,
        "development_paired_wins": development_wins,
        "holdout_paired_wins": holdout_wins,
        "holdout_verified": holdout_passed and no_regression and holdout_wins > 0,
        "business_evidence": evidence,
        "evaluation_scope": "business_regression_and_holdout",
        "verdict": "candidate_for_approval" if eligible else "keep_baseline",
        "reason": (
            "business_regression_and_holdout_passed" if eligible else "no_business_improvement"
        ),
    }
