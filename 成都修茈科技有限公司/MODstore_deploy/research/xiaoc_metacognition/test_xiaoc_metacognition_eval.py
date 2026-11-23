import hashlib

import pytest

from xiaoc_metacognition_eval import Case, Observation, Protocol, Receipt, evaluate, fingerprint


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    case = Case(task="held", source=digest("source"), group=digest("group"), partition="holdout",
                condition="missing", expected_action="supplement_evidence", evidence=(digest("ref"),))
    protocol = Protocol(source_revision="commit", dataset_version="synthetic-v1",
                        evaluator_revision=digest("verifier"), model_revision="model-v1",
                        model_settings_sha256=digest("settings"),
                        baseline_revision=digest("base"), candidate_revision=digest("candidate"),
                        seeds=(1, 2, 3), cases=(case,))
    observations = tuple(Observation(protocol_sha256=fingerprint(protocol), task="held", arm=arm, seed=seed,
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


@pytest.mark.parametrize("field", ["source", "group", "evidence"])
def test_development_holdout_overlap_rejected(field):
    protocol, observations, receipts = fixture()
    case = protocol.cases[0]
    dev = case.model_copy(update={"task": "dev", "partition": "development", "source": digest("dev"),
                                  "group": digest("dev-group"), "evidence": (digest("dev-ref"),),
                                  field: getattr(case, field)})
    with pytest.raises(ValueError, match="partition_leakage"):
        run(protocol.model_copy(update={"cases": (case, dev)}), observations, receipts)


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
