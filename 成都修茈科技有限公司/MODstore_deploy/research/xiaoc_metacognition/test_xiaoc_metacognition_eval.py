import hashlib

import pytest

from xiaoc_metacognition_eval import Case, Observation, Protocol, Receipt, evaluate, fingerprint


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    case = Case(task="held", source=digest("source"), group=digest("group"), partition="holdout",
                condition="missing", expected_action="supplement_evidence", evidence=(digest("ref"),))
    protocol = Protocol(source_revision="a" * 40, dataset_version="synthetic-v1",
                        evaluator_revision=digest("verifier"), model_revision="model-v1",
                        model_settings_sha256=digest("settings"),
                        baseline_revision=digest("base"), candidate_revision=digest("candidate"),
                        seeds=(1, 2, 3), cases=(case,))
    observations = tuple(Observation(protocol_sha256=fingerprint(protocol), task="held", arm=arm, seed=seed,
                                     strategy_revision=protocol.baseline_revision if arm == "baseline" else protocol.candidate_revision,
                                     model_revision=protocol.model_revision, model_settings_sha256=protocol.model_settings_sha256,
                                     output_sha256=digest(f"{arm}:{seed}"),
                                     action="direct" if arm == "baseline" else "supplement_evidence",
                                     confidence=0.9 if arm == "baseline" else 0.7,
                                     evidence=case.evidence, unknown=arm == "candidate")
                         for arm in ("baseline", "candidate") for seed in protocol.seeds)
    receipts = tuple(Receipt(observation_sha256=fingerprint(obs), evaluator_revision=protocol.evaluator_revision,
                             receipt_sha256=digest(fingerprint(obs)), correct=obs.arm == "candidate",
                             reason="verified" if obs.arm == "candidate" else "wrong_inference")
                     for obs in observations)
    return protocol, observations, receipts


def run(protocol, observations, receipts, frozen=None):
    return evaluate(protocol, frozen_sha256=frozen or fingerprint(protocol), observations=observations, receipts=receipts)


def test_paired_metrics_and_review_only():
    protocol, observations, receipts = fixture()
    report = run(protocol, observations, receipts)
    assert report["paired_outcomes"] == {"improvement": 3}
    assert report["status"] == "insufficient_evidence"
    assert report["review_required"] is True
    base = report["arms"]["baseline"]["overall"]
    candidate = report["arms"]["candidate"]["overall"]
    assert base["brier_score"] == pytest.approx(0.81)
    assert candidate["brier_score"] == pytest.approx(0.09)
    assert base["high_confidence_errors"] == 3
    assert base["high_confidence_verified_trials"] == 3
    assert base["high_confidence_error_rate_verified_only"] == pytest.approx(1.0)
    assert base["mean_confidence_minus_correct_rate"] == pytest.approx(0.9)
    assert candidate["mean_confidence_minus_correct_rate"] == pytest.approx(-0.3)
    assert candidate["high_confidence_error_rate_verified_only"] is None
    assert base["unsupported_direct"] == 3
    assert base["repeated_failure_tasks"] == ["held"]
    assert candidate["unknown_acknowledged"] == 3
    assert candidate["route_matches"] == 3


def test_unknown_result_is_not_a_failure_or_success():
    protocol, observations, receipts = fixture()
    receipts = (receipts[0].model_copy(update={"correct": None, "reason": "unknown"}), *receipts[1:])
    report = run(protocol, observations, receipts)
    assert report["paired_outcomes"] == {"unknown": 1, "improvement": 2}
    assert report["arms"]["baseline"]["overall"]["verified_trials"] == 2
    assert report["arms"]["baseline"]["overall"]["high_confidence_verified_trials"] == 2
    assert report["arms"]["baseline"]["overall"]["high_confidence_errors"] == 2


@pytest.mark.parametrize("field", ["source", "group", "evidence"])
@pytest.mark.parametrize("left,right", [
    ("development", "holdout"), ("validation", "holdout"),
    ("development", "validation"),
])
def test_partition_overlap_rejected(field, left, right):
    protocol, observations, receipts = fixture()
    case = protocol.cases[0].model_copy(update={"partition": left})
    other = case.model_copy(update={
        "task": "other", "partition": right, "source": digest("other"),
        "group": digest("other-group"), "evidence": (digest("other-ref"),),
        field: getattr(case, field),
    })
    with pytest.raises(ValueError, match="partition_leakage"):
        run(protocol.model_copy(update={"cases": (case, other)}), observations, receipts)


@pytest.mark.parametrize("partition", ["development", "validation"])
def test_nonholdout_observation_rejected(partition):
    protocol, observations, receipts = fixture()
    case = protocol.cases[0]
    other = case.model_copy(update={
        "task": "other", "partition": partition, "source": digest("other"),
        "group": digest("other-group"), "evidence": (digest("other-ref"),),
    })
    protocol = protocol.model_copy(update={"cases": (case, other)})
    frozen = fingerprint(protocol)
    obs = observations[0].model_copy(update={"protocol_sha256": frozen, "task": "other"})
    receipt = receipts[0].model_copy(update={"observation_sha256": fingerprint(obs)})
    with pytest.raises(ValueError, match="unexpected_or_duplicate_trial"):
        run(protocol, (obs,), (receipt,))


@pytest.mark.parametrize("change,match", [
    ("missing_trial", "incomplete_or_extra_trials"), ("duplicate_trial", "unexpected_or_duplicate_trial"),
    ("missing_receipt", "missing_bound_receipt"), ("drift", "protocol_drift"),
    ("wrong_evidence", "invalid_evidence_reference"), ("wrong_verifier", "invalid_receipt"),
    ("duplicate_receipt", "invalid_receipt"), ("wrong_protocol", "trial_protocol_mismatch"), ("self_contradiction", "invalid_receipt"),
])
def test_rejects_invalid_evidence(change, match):
    protocol, observations, receipts = fixture()
    frozen = fingerprint(protocol)
    if change == "missing_trial":
        observations, receipts = observations[1:], receipts[1:]
    elif change == "duplicate_trial":
        observations += observations[:1]
    elif change == "missing_receipt":
        receipts = receipts[1:]
    elif change == "drift":
        protocol = protocol.model_copy(update={"dataset_version": "modified"})
    elif change == "wrong_evidence":
        observations = (observations[0].model_copy(update={"evidence": (digest("invented"),)}), *observations[1:])
    elif change == "wrong_protocol":
        observations = (observations[0].model_copy(update={"protocol_sha256": digest("other")}), *observations[1:])
    elif change == "wrong_verifier":
        receipts = (receipts[0].model_copy(update={"evaluator_revision": digest("other")}), *receipts[1:])
    elif change == "duplicate_receipt":
        receipts += receipts[:1]
    else:
        receipts = (receipts[0].model_copy(update={"correct": True}), *receipts[1:])
    with pytest.raises(ValueError, match=match):
        run(protocol, observations, receipts, frozen)


@pytest.mark.parametrize("field,value", [
    ("strategy_revision", digest("wrong-strategy")),
    ("model_revision", "wrong-model"),
    ("model_settings_sha256", digest("wrong-settings")),
    ("output_sha256", "not-a-sha"),
])
def test_frozen_trial_identity(field, value):
    protocol, observations, receipts = fixture()
    observations = (observations[0].model_copy(update={field: value}), *observations[1:])
    with pytest.raises(ValueError, match="trial_revision_or_output_mismatch"):
        run(protocol, observations, receipts)


def test_missing_confidence_is_excluded_from_paired_comparison():
    protocol, observations, receipts = fixture()
    obs = observations[0].model_copy(update={"confidence": None})
    observations = (obs, *observations[1:])
    receipts = (receipts[0].model_copy(update={"observation_sha256": fingerprint(obs)}), *receipts[1:])
    report = run(protocol, observations, receipts)
    assert report["matched_calibration_pairs"] == 2
    assert report["total_pairs"] == 3
    assert report["arms"]["baseline"]["overall"]["verified_missing_confidence"] == 1
    assert report["paired_brier_delta_candidate_minus_baseline"] == pytest.approx(-0.72)
    assert report["paired_by_condition"] == {"missing": {"improvement": 3}}
    assert len(report["audit_trials"]) == 6
    assert report["status"] == "insufficient_evidence"


@pytest.mark.parametrize("mode,expected_floor,expected_coverage,expected_status", [
    ("balanced", True, True, "pending_human_review"),
    ("one_condition", True, False, "insufficient_evidence"),
    ("one_source", False, True, "insufficient_evidence"),
    ("missing_confidence", True, True, "insufficient_evidence"),
    ("no_development", True, True, "insufficient_evidence"),
    ("no_validation", True, True, "insufficient_evidence"),
])
def test_sample_and_condition_coverage(mode, expected_floor, expected_coverage, expected_status):
    protocol, _, _ = fixture()
    conditions = ("sufficient", "missing", "ambiguous", "outside_capability")
    actions = ("direct", "supplement_evidence", "clarify", "human_help")
    cases = tuple(Case(task=f"task-{i}", source=digest("one" if mode == "one_source" else f"source-{i}"),
                       group=digest(f"group-{i}"), partition="holdout",
                       condition=conditions[0 if mode == "one_condition" else i % 4],
                       expected_action=actions[0 if mode == "one_condition" else i % 4],
                       evidence=(digest(f"evidence-{i}"),)) for i in range(100))
    nonholdout = tuple(
        Case(task=partition, source=digest(f"{partition}-source"),
             group=digest(f"{partition}-group"), partition=partition,
             condition="sufficient", expected_action="direct",
             evidence=(digest(f"{partition}-evidence"),))
        for partition in ("development", "validation") if mode != f"no_{partition}"
    )
    protocol = protocol.model_copy(update={"cases": cases + nonholdout})
    frozen = fingerprint(protocol)
    observations = tuple(Observation(protocol_sha256=frozen, task=case.task, arm=arm, seed=seed,
                                     strategy_revision=protocol.baseline_revision if arm == "baseline" else protocol.candidate_revision,
                                     model_revision=protocol.model_revision, model_settings_sha256=protocol.model_settings_sha256,
                                     output_sha256=digest(f"{case.task}:{arm}:{seed}"), action=case.expected_action,
                                     confidence=None if mode == "missing_confidence" else 0.8,
                                     evidence=case.evidence, unknown=case.condition != "sufficient")
                         for case in cases for arm in ("baseline", "candidate") for seed in protocol.seeds)
    receipts = tuple(Receipt(observation_sha256=fingerprint(obs), evaluator_revision=protocol.evaluator_revision,
                             receipt_sha256=digest(fingerprint(obs)), correct=True, reason="verified")
                     for obs in observations)
    report = run(protocol, observations, receipts)
    assert report["sample_floor_met"] is expected_floor
    assert report["condition_coverage_met"] is expected_coverage
    assert report["dataset_partitions_present"] is (mode not in ("no_development", "no_validation"))
    assert report["dataset_partition_counts"] == {
        "development": int(mode != "no_development"),
        "validation": int(mode != "no_validation"),
        "holdout": 100,
    }
    assert report["status"] == expected_status
    assert report["review_required"] is True
    assert report["paired_outcomes"] == {"same": 300}
    assert report["total_pairs"] == 300


def test_invalid_source_revision_rejected():
    protocol, observations, receipts = fixture()
    protocol = protocol.model_copy(update={"source_revision": "not-a-commit"})
    with pytest.raises(ValueError, match="invalid_source_revision"):
        run(protocol, observations, receipts)


def test_low_confidence_routes_and_label_conflict_keep_original_receipt_distinct():
    protocol, observations, receipts = fixture()
    first = observations[0].model_copy(update={"confidence": 0.2, "action": "human_help"})
    second = observations[1].model_copy(update={"confidence": 0.49})
    observations = (first, second, *observations[2:])
    receipts = (
        receipts[0].model_copy(update={"observation_sha256": fingerprint(first),
                                      "correct": True, "reason": "verified"}),
        receipts[1].model_copy(update={"observation_sha256": fingerprint(second)}),
        *receipts[2:],
    )
    report = run(protocol, observations, receipts)
    base = report["arms"]["baseline"]["overall"]
    assert base["route_label_conflicts"] == 1
    assert base["route_label_conflict_refs"] == [fingerprint(first)]
    assert report["review_findings"]["route_label_conflicts"] == 1
    review = base["low_confidence_review"]
    assert review["trials"] == 2
    assert review["direct_routes"] == 1
    assert review["human_help_routes"] == 1
    assert review["human_help_route_refs"] == [fingerprint(first)]
    assert review["handoff_delivery"] == "not_measured_by_offline_protocol"
