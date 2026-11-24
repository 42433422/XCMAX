"""A fixture report is usable as history, never as an ability certificate."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from modstore_server.xiaoc_self_evidence import (
    annotate_unverified_catalog,
    fixture_trend,
    read_fixture_summary,
)


def encode(value):
    return json.dumps(value, sort_keys=True).encode()


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sample():
    standard = {
        "standard_version": "test-v1",
        "scoring_version": "test-score-v1",
        "digital_life_evaluation": {
            "protocol_version": "test-protocol-v1",
            "seeds": [17, 29, 43],
            "layers": ["unit", "integration", "real_model", "real_business", "production"],
            "scenarios": [
                {
                    "id": "memory",
                    "anchor": "autonomy-B3",
                    "positive": "tests/test_memory.py::test_positive",
                    "negative": "tests/test_memory.py::test_negative",
                },
                {
                    "id": "business",
                    "anchor": "erp-B3",
                    "positive": "tests/test_business.py::test_positive",
                    "negative": "tests/test_business.py::test_negative",
                },
            ],
        },
    }
    standard_raw = encode(standard)
    rows = []
    for scenario in standard["digital_life_evaluation"]["scenarios"]:
        trials = [
            {
                "kind": kind,
                "seed": seed,
                "node": scenario[kind],
                "status": "PASS",
                "returncode": 0,
                "artifact_sha256": sha(f"{scenario['id']}:{kind}:{seed}"),
            }
            for kind in ("positive", "negative")
            for seed in (17, 29, 43)
        ]
        rows.append(
            {
                "id": scenario["id"],
                "anchor": scenario["anchor"],
                "trials": trials,
                "layers": {
                    "unit": "NOT RUN",
                    "integration": "PASS",
                    "real_model": "NOT RUN",
                    "real_business": "NOT RUN",
                    "production": "NOT RUN",
                },
            }
        )
    report = {
        "standard_sha256": hashlib.sha256(standard_raw).hexdigest(),
        "standard_version": "test-v1",
        "scoring_version": "test-score-v1",
        "protocol_version": "test-protocol-v1",
        "seeds": [17, 29, 43],
        "score": None,
        "domain_status": "UNRATED",
        "evidence_scope": "isolated_fixture_only_not_attested",
        "model_and_budget": "fixture_only_no_live_model_claim",
        "source_sha": "a" * 40,
        "auditor_source_sha": "b" * 40,
        "dataset_sha256": sha("dataset"),
        "environment_sha256": sha("environment"),
        "scenarios": rows,
    }
    return report, standard_raw


def test_report_fingerprints_are_historical_and_anchor_status_remains_unverified():
    report, standard = sample()
    summary = read_fixture_summary(encode(report), standard)
    assert summary["scope"] == "historical_fixture_claim_only_not_current_capability"
    assert summary["scenarios"]["memory"]["integration"] == "PASS"
    projection = {
        "status": "catalog_only",
        "standard_sha256": summary["standard_sha256"],
        "anchors": [
            {"anchor_id": "autonomy-B3", "status": "unverified"},
            {"anchor_id": "erp-B3", "status": "unverified"},
        ],
    }
    entry = {
        "id": "self-fixture:" + summary["report_sha256"],
        "kind": "self_fixture_check",
        "status": "historical_fixture",
        "details": summary,
    }
    annotated = annotate_unverified_catalog(projection, [entry], current_sha="a" * 40)
    assert all(row["status"] == "unverified" for row in annotated["anchors"])
    assert annotated["anchors"][0]["fixture_history"][0]["reported_integration"] == "PASS"
    assert annotated["anchors"][0]["fixture_history"][0]["release_match"] is True
    assert annotated["anchors"][0]["fixture_history"][0]["status"] == (
        "unverified_fixture_claim_not_capability"
    )
    assert not annotate_unverified_catalog({"status": "unknown"}, [entry], current_sha=None).get(
        "anchors"
    )


@pytest.mark.parametrize(
    "change",
    [
        "source_drift",
        "missing_scenario",
        "duplicate_scenario",
        "forged_anchor",
        "forged_live_model",
        "forged_score",
        "forged_release",
        "nonindependent_auditor",
        "missing_trial",
        "duplicate_trial",
        "wrong_node",
        "false_aggregate",
        "forged_pass",
        "unrun_with_trials",
    ],
)
def test_fixture_report_fails_closed_on_provenance_and_coverage(change):
    report, standard = sample()
    rows = report["scenarios"]
    if change == "source_drift":
        report["standard_sha256"] = sha("other")
    elif change == "missing_scenario":
        rows.pop()
    elif change == "duplicate_scenario":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "forged_anchor":
        rows[0]["anchor"] = "made-up"
    elif change == "forged_live_model":
        rows[0]["layers"]["real_model"] = "PASS"
    elif change == "forged_score":
        report["score"] = 100
    elif change == "forged_release":
        report["source_sha"] = "not-a-git-sha"
    elif change == "nonindependent_auditor":
        report["auditor_source_sha"] = report["source_sha"]
    elif change == "missing_trial":
        rows[0]["trials"].pop()
    elif change == "duplicate_trial":
        rows[0]["trials"].append(copy.deepcopy(rows[0]["trials"][0]))
    elif change == "wrong_node":
        rows[0]["trials"][0]["node"] = "tests/test_fake.py::test_fake"
    elif change == "false_aggregate":
        rows[0]["layers"]["integration"] = "BLOCKED"
    elif change == "forged_pass":
        rows[0]["trials"][0]["artifact_sha256"] = None
    elif change == "unrun_with_trials":
        rows[0]["layers"]["integration"] = "NOT RUN"
    with pytest.raises(ValueError):
        read_fixture_summary(encode(report), standard)


def test_history_must_match_standard_digest_and_bound_event_identity():
    report, standard = sample()
    summary = read_fixture_summary(encode(report), standard)
    catalog = {
        "status": "catalog_only",
        "standard_sha256": summary["standard_sha256"],
        "anchors": [{"anchor_id": "autonomy-B3", "status": "unverified"}],
    }
    event = {
        "id": "self-fixture:" + summary["report_sha256"],
        "kind": "self_fixture_check",
        "status": "historical_fixture",
        "details": summary,
    }
    for tampered in (
        {**event, "id": "self-fixture:" + sha("fake")},
        {**event, "details": {**summary, "standard_sha256": sha("other")}},
        {**event, "status": "current_mastered"},
    ):
        result = annotate_unverified_catalog(copy.deepcopy(catalog), [tampered], current_sha=None)
        assert "fixture_history" not in result["anchors"][0]


def test_release_fixture_trend_never_claims_actual_capability_decline():
    report, standard = sample()
    summary = read_fixture_summary(encode(report), standard)

    def event(key, source, statuses):
        details = copy.deepcopy(summary)
        details["source_sha"] = source
        details["report_sha256"] = sha(key)
        for scenario, state in statuses.items():
            details["scenarios"][scenario]["integration"] = state
        return {
            "id": "self-fixture:" + details["report_sha256"],
            "kind": "self_fixture_check",
            "status": "historical_fixture",
            "details": details,
        }

    old = event("old", "c" * 40, {"memory": "PASS", "business": "PASS"})
    current = event("new", "a" * 40, {"memory": "FAIL", "business": "BLOCKED"})
    trend = fixture_trend([current, old], current_sha="a" * 40)
    assert trend["status"] == "comparable_fixture_only_not_capability_degradation"
    assert trend["fixture_regressions_to_review"] == ["memory"]
    assert trend["fixture_evidence_lost"] == ["business"]

    drifted = copy.deepcopy(old)
    drifted["details"]["dataset_sha256"] = sha("different")
    assert (
        fixture_trend([current, drifted], current_sha="a" * 40)["status"]
        == "insufficient_comparable_fixture_evidence"
    )
    assert (
        fixture_trend([old], current_sha="a" * 40)["status"]
        == "insufficient_comparable_fixture_evidence"
    )
