"""Offline, human-reviewed strategy research; never imported by the live runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sklearn import __version__ as sklearn_version
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss

Action = Literal["direct", "supplement_evidence", "clarify", "human_help", "unknown"]
Arm = Literal["baseline", "candidate"]
Digest = str


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Case(Contract):
    task: str = Field(min_length=1, max_length=100)
    source: Digest
    group: Digest
    partition: Literal["development", "holdout"]
    condition: Literal["sufficient", "missing", "ambiguous", "outside_capability"]
    expected_action: Action
    evidence: tuple[str, ...]


class Protocol(Contract):
    source_revision: str = Field(min_length=1, max_length=64)
    dataset_version: str = Field(min_length=1, max_length=100)
    evaluator_revision: Digest
    model_revision: str = Field(min_length=1, max_length=100)
    model_settings_sha256: Digest
    baseline_revision: Digest
    candidate_revision: Digest
    seeds: tuple[int, ...] = Field(min_length=1, max_length=10)
    cases: tuple[Case, ...] = Field(min_length=1, max_length=2000)


class Observation(Contract):
    protocol_sha256: Digest
    task: str
    arm: Arm
    seed: int
    strategy_revision: Digest
    model_revision: str
    model_settings_sha256: Digest
    output_sha256: Digest
    action: Action
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    evidence: tuple[str, ...]
    unknown: bool


class Receipt(Contract):
    observation_sha256: Digest
    evaluator_revision: Digest
    receipt_sha256: Digest
    correct: bool | None
    reason: Literal["verified", "wrong_inference", "capability_boundary", "missing_evidence", "unknown"]


def fingerprint(value: BaseModel) -> str:
    encoded = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _validate(protocol: Protocol) -> dict[str, Case]:
    revisions = (protocol.evaluator_revision, protocol.baseline_revision, protocol.candidate_revision)
    if not all(map(_digest, (*revisions, protocol.model_settings_sha256))) or len(set(revisions)) != 3:
        raise ValueError("invalid_or_nonindependent_revision")
    if len(set(protocol.seeds)) != len(protocol.seeds):
        raise ValueError("duplicate_seed")
    if len(protocol.source_revision) not in (40, 64) or any(
        c not in "0123456789abcdef" for c in protocol.source_revision
    ):
        raise ValueError("invalid_source_revision")
    cases = {}
    partitions: dict[str, str] = {}
    for case in protocol.cases:
        if case.task in cases or not all(map(_digest, (case.source, case.group, *case.evidence))):
            raise ValueError("duplicate_task_or_invalid_source")
        for key in (case.source, case.group, *case.evidence):
            if partitions.setdefault(key, case.partition) != case.partition:
                raise ValueError("partition_leakage")
        cases[case.task] = case
    return {key: case for key, case in cases.items() if case.partition == "holdout"}


def _metrics(rows: list[tuple[Case, Observation, Receipt]]) -> dict:
    known = [(obs, receipt) for _, obs, receipt in rows if receipt.correct is not None]
    measured = [(obs.confidence, int(receipt.correct)) for obs, receipt in known if obs.confidence is not None]
    probabilities = [p for p, _ in measured]
    labels = [y for _, y in measured]
    high_confidence = [
        (obs, receipt) for obs, receipt in known
        if obs.confidence is not None and obs.confidence >= 0.8
    ]
    high_confidence_errors = sum(receipt.correct is False for _, receipt in high_confidence)
    bins = []
    if measured:
        observed, predicted = calibration_curve(labels, probabilities, n_bins=5, strategy="uniform")
        bins = [{"mean_confidence": float(p), "correct_rate": float(y)} for y, p in zip(observed, predicted)]
    failures = Counter(case.task for case, _, receipt in rows if receipt.correct is False)
    insufficient = [(case, obs) for case, obs, _ in rows if case.condition != "sufficient"]
    return {
        "trials": len(rows),
        "verified_trials": len(known),
        "unknown_outcomes": len(rows) - len(known),
        "accuracy_verified_only": sum(r.correct is True for _, r in known) / len(known) if known else None,
        "calibrated_trials": len(measured),
        "missing_confidence": sum(obs.confidence is None for _, obs, _ in rows),
        "verified_missing_confidence": len(known) - len(measured),
        "mean_confidence": sum(probabilities) / len(probabilities) if measured else None,
        "calibration_correct_rate": sum(labels) / len(labels) if measured else None,
        # Positive gap means overconfidence on the *same labelled* subset only.
        "mean_confidence_minus_correct_rate": (
            (sum(probabilities) - sum(labels)) / len(measured) if measured else None
        ),
        "brier_score": float(brier_score_loss(labels, probabilities)) if measured else None,
        "reliability_bins": bins,
        "high_confidence_errors": high_confidence_errors,
        "high_confidence_verified_trials": len(high_confidence),
        "high_confidence_error_rate_verified_only": (
            high_confidence_errors / len(high_confidence) if high_confidence else None
        ),
        "route_matches": sum(o.action == c.expected_action for c, o, _ in rows),
        "unknown_acknowledged": sum(o.unknown for _, o in insufficient),
        "unsupported_direct": sum(o.action == "direct" and (not o.evidence or c.condition != "sufficient" or o.unknown) for c, o, _ in rows),
        "unknown_state_conflicts": sum(o.action == "unknown" and not o.unknown for _, o, _ in rows),
        "insufficient_evidence_trials": len(insufficient),
        "failure_reasons": dict(Counter(r.reason for _, _, r in rows if r.correct is False)),
        "repeated_failure_tasks": sorted(k for k, n in failures.items() if n >= 2),
    }


def evaluate(protocol: Protocol, *, frozen_sha256: str, observations: tuple[Observation, ...], receipts: tuple[Receipt, ...]) -> dict:
    """Compare frozen held-out trials. Receipt authenticity is the reviewer's duty.

    No model calls, strategy selection, policy writes, or inferred permissions.
    This verifies binding/completeness, not the truth of externally supplied labels.
    """
    if fingerprint(protocol) != frozen_sha256:
        raise ValueError("protocol_drift")
    cases = _validate(protocol)
    expected = {(task, arm, seed) for task in cases for arm in ("baseline", "candidate") for seed in protocol.seeds}
    if not expected:
        raise ValueError("no_holdout")
    outcomes = {}
    seen_receipts = set()
    for receipt in receipts:
        if (not _digest(receipt.observation_sha256) or not _digest(receipt.receipt_sha256)
                or receipt.evaluator_revision != protocol.evaluator_revision
                or receipt.observation_sha256 in outcomes or receipt.receipt_sha256 in seen_receipts
                or (receipt.correct is None) != (receipt.reason == "unknown")
                or (receipt.correct is True) != (receipt.reason == "verified")):
            raise ValueError("invalid_receipt")
        outcomes[receipt.observation_sha256] = receipt
        seen_receipts.add(receipt.receipt_sha256)
    rows = {}
    for obs in observations:
        key = (obs.task, obs.arm, obs.seed)
        if obs.protocol_sha256 != frozen_sha256:
            raise ValueError("trial_protocol_mismatch")
        if key not in expected or key in rows:
            raise ValueError("unexpected_or_duplicate_trial")
        case = cases[obs.task]
        strategy = protocol.baseline_revision if obs.arm == "baseline" else protocol.candidate_revision
        if (
            obs.strategy_revision != strategy
            or obs.model_revision != protocol.model_revision
            or obs.model_settings_sha256 != protocol.model_settings_sha256
            or not _digest(obs.output_sha256)
        ):
            raise ValueError("trial_revision_or_output_mismatch")
        if not set(obs.evidence) <= set(case.evidence):
            raise ValueError("invalid_evidence_reference")
        receipt = outcomes.pop(fingerprint(obs), None)
        if receipt is None:
            raise ValueError("missing_bound_receipt")
        rows[key] = (case, obs, receipt)
    if rows.keys() != expected or outcomes:
        raise ValueError("incomplete_or_extra_trials")
    report = {}
    for arm in ("baseline", "candidate"):
        arm_rows = [row for key, row in rows.items() if key[1] == arm]
        report[arm] = {"overall": _metrics(arm_rows), "conditions": {
            condition: _metrics([row for row in arm_rows if row[0].condition == condition])
            for condition in sorted({case.condition for case in cases.values()})
        }}
    pairs = Counter()
    paired_conditions: dict[str, Counter] = {}
    calibration_pairs: list[tuple[float, float, int, int]] = []
    for task, case in cases.items():
        for seed in protocol.seeds:
            _, base_obs, base_receipt = rows[(task, "baseline", seed)]
            _, candidate_obs, candidate_receipt = rows[(task, "candidate", seed)]
            a, b = base_receipt.correct, candidate_receipt.correct
            label = "unknown" if a is None or b is None else "same" if a == b else "regression" if a else "improvement"
            pairs[label] += 1
            paired_conditions.setdefault(case.condition, Counter())[label] += 1
            if (
                a is not None and b is not None
                and base_obs.confidence is not None and candidate_obs.confidence is not None
            ):
                calibration_pairs.append((base_obs.confidence, candidate_obs.confidence, int(a), int(b)))
    groups = len({case.group for case in cases.values()})
    sources = len({case.source for case in cases.values()})
    condition_groups = {
        condition: len({case.group for case in cases.values() if case.condition == condition})
        for condition in ("sufficient", "missing", "ambiguous", "outside_capability")
    }
    sample_floor = len(cases) >= 100 and min(groups, sources) >= 100 and len(protocol.seeds) >= 3
    coverage_complete = all(n >= 10 for n in condition_groups.values())
    all_pairs = len(cases) * len(protocol.seeds)
    paired_brier_delta = None
    if calibration_pairs:
        p_base, p_candidate, y_base, y_candidate = map(list, zip(*calibration_pairs))
        paired_brier_delta = float(
            brier_score_loss(y_candidate, p_candidate) - brier_score_loss(y_base, p_base)
        )
    ready_for_review = sample_floor and coverage_complete and len(calibration_pairs) == all_pairs
    return {
        "scope": "offline_research_not_capability_score_or_authority",
        "status": "pending_human_review" if ready_for_review else "insufficient_evidence",
        "protocol_sha256": frozen_sha256,
        "sklearn_version": sklearn_version,
        "holdout_tasks": len(cases),
        "independent_source_groups": groups,
        "distinct_source_digests": sources,
        "sample_floor_met": sample_floor,
        "condition_group_counts": condition_groups,
        "condition_coverage_met": coverage_complete,
        "matched_calibration_pairs": len(calibration_pairs),
        "total_pairs": all_pairs,
        "paired_brier_delta_candidate_minus_baseline": paired_brier_delta,
        "arms": report,
        "paired_outcomes": dict(pairs),
        "paired_by_condition": {key: dict(value) for key, value in sorted(paired_conditions.items())},
        "audit_trials": [
            {
                "task": task, "arm": arm, "seed": seed,
                "observation_sha256": fingerprint(rows[(task, arm, seed)][1]),
                "receipt_sha256": rows[(task, arm, seed)][2].receipt_sha256,
            }
            for task, arm, seed in sorted(rows)
        ],
        "receipt_sha256s": sorted(seen_receipts),
        "review_required": True,
        "review_findings": {
            "regressions_to_review": pairs["regression"],
            "unresolved_pairs": pairs["unknown"],
            "route_and_calibration_review": "Compare each condition; inspect unsupported direct, repeated failures, unknown recognition and calibration before any separate human decision.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("frozen_sha256")
    parser.add_argument("observations", type=Path)
    parser.add_argument("receipts", type=Path)
    args = parser.parse_args()
    report = evaluate(
        Protocol.model_validate_json(args.protocol.read_bytes()),
        frozen_sha256=args.frozen_sha256,
        observations=TypeAdapter(tuple[Observation, ...]).validate_json(args.observations.read_bytes()),
        receipts=TypeAdapter(tuple[Receipt, ...]).validate_json(args.receipts.read_bytes()),
    )
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
