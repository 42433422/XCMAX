"""The independent verifier must reject wrong, missing and mock-promoted evidence."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.dev import audit_benchmark_ssot as standard
from scripts.dev import xiaoc_independent_eval as evaluator

NODE = "tests/test_example.py::test_result"


def xml(body=""):
    return (
        '<testsuites><testsuite><testcase classname="tests.test_example" name="test_result">'
        + body
        + "</testcase></testsuite></testsuites>"
    ).encode()


@pytest.mark.parametrize(
    ("raw", "code", "expected"),
    [
        (xml(), 0, "PASS"),
        (xml("<failure/>"), 1, "FAIL"),
        (xml("<failure/>"), 0, "BLOCKED"),
        (xml("<skipped/>"), 0, "BLOCKED"),
        (xml("<error/>"), 1, "BLOCKED"),
        (xml(), 1, "BLOCKED"),
        (xml(), 5, "BLOCKED"),
        (b"", 0, "BLOCKED"),
        (b"<broken", 0, "BLOCKED"),
        (xml().replace(b"test_result", b"other"), 0, "BLOCKED"),
        (b"<testsuite>" + xml() + xml() + b"</testsuite>", 0, "BLOCKED"),
    ],
)
def test_junit_is_fail_closed(raw, code, expected):
    assert evaluator.judge(raw, NODE, code) == expected


def test_negative_case_must_pass_and_all_trials_must_exist():
    assert evaluator.aggregate(["PASS"] * 6, 6) == "PASS"
    assert evaluator.aggregate(["PASS"] * 5, 6) == "BLOCKED"
    assert evaluator.aggregate(["PASS"] * 5 + ["FAIL"], 6) == "FAIL"
    assert evaluator.aggregate(["PASS"] * 5 + ["BLOCKED"], 6) == "BLOCKED"


def test_ssot_remains_18_domains_and_108_anchors():
    data = json.loads(standard.CATALOG.read_text())
    assert not standard.validate(data)
    assert len(data["domains"]) == 18
    assert sum(len(d["anchor_60"]) + len(d["anchor_90"]) for d in data["domains"]) == 108
    protocol = data["digital_life_evaluation"]
    assert len(protocol["scenarios"]) == 8
    assert protocol["status"] == "NOT RUN"
    data["digital_life_evaluation"]["scenarios"][0]["anchor"] = "invented"
    assert standard.validate(data)


def test_trends_do_not_compare_different_data_and_separate_missing_evidence():
    old = {
        "standard_sha256": "standard",
        "dataset_sha256": "dataset",
        "environment_sha256": "environment",
        "seeds": [17, 29, 43],
        "auditor_source_sha": "a" * 40,
        "protocol_version": "digital-life-fixture/v1",
        "scoring_version": "ssot-v1",
        "scenarios": [{"id": key, "layers": {"integration": "PASS"}} for key in ("a", "b")],
    }
    current = copy.deepcopy(old)
    current["source_sha"] = "b" * 40
    current["scenarios"][0]["layers"]["integration"] = "FAIL"
    current["scenarios"][1]["layers"]["integration"] = "BLOCKED"
    assert evaluator.compare(old, current) == {
        "status": "COMPARABLE_FIXTURE_ONLY",
        "regressions": ["a"],
        "evidence_lost": ["b"],
    }
    for key in (
        "standard_sha256",
        "dataset_sha256",
        "environment_sha256",
        "auditor_source_sha",
        "protocol_version",
        "scoring_version",
    ):
        changed = copy.deepcopy(current)
        changed[key] = "different"
        assert evaluator.compare(old, changed)["status"] == "INCOMPARABLE"
    changed = copy.deepcopy(current)
    changed["seeds"] = [1, 2, 3]
    assert evaluator.compare(old, changed)["status"] == "INCOMPARABLE"

    # Legacy reports lacking the independent auditor identity are not comparable.
    legacy = copy.deepcopy(old)
    del legacy["auditor_source_sha"]
    assert evaluator.compare(legacy, current)["status"] == "INCOMPARABLE"

    # Malformed or duplicated scenario IDs cannot silently replace a PASS case.
    changed = copy.deepcopy(current)
    changed["scenarios"].append(copy.deepcopy(changed["scenarios"][0]))
    assert evaluator.compare(old, changed)["status"] == "INCOMPARABLE"
    changed = copy.deepcopy(current)
    changed["scenarios"][0]["layers"]["integration"] = "self_reported_pass"
    assert evaluator.compare(old, changed)["status"] == "INCOMPARABLE"


def test_higher_evidence_layers_are_never_promoted(monkeypatch, tmp_path):
    raw = standard.CATALOG.read_bytes()
    monkeypatch.setattr(evaluator, "identity", lambda *_: None)
    monkeypatch.setattr(evaluator, "freeze_dataset", lambda *_: "frozen")
    monkeypatch.setattr(evaluator, "git", lambda *_: "auditor-sha")
    monkeypatch.setattr(evaluator, "environment", lambda: {"python": "test"})
    monkeypatch.setattr(evaluator, "run_node", lambda *_: {"status": "PASS"})
    report = evaluator.evaluate(
        tmp_path / "candidate",
        "candidate",
        tmp_path / "report",
        evaluator.digest(raw),
        True,
        auditor_sha="approved-auditor",
    )
    assert report["score"] is None
    assert report["domain_status"] == "UNRATED"
    assert all(
        row["layers"]
        == {
            "unit": "NOT RUN",
            "integration": "PASS",
            "real_model": "NOT RUN",
            "real_business": "NOT RUN",
            "production": "NOT RUN",
        }
        for row in report["scenarios"]
    )
    with pytest.raises(ValueError, match="approved standard"):
        evaluator.evaluate(tmp_path / "candidate", "candidate", tmp_path / "other", "wrong", False)


def test_auditor_checkout_is_mandatory_for_execution(monkeypatch, tmp_path):
    raw = standard.CATALOG.read_bytes()
    monkeypatch.setattr(evaluator, "identity", lambda *_: None)
    with pytest.raises(ValueError, match="separate approved auditor"):
        evaluator.evaluate(
            tmp_path / "candidate",
            "candidate",
            tmp_path / "output",
            evaluator.digest(raw),
            True,
        )


def test_generated_ssot_view_is_current():
    data = json.loads(standard.CATALOG.read_text(encoding="utf-8"))
    assert standard.DOCUMENT.read_text(encoding="utf-8") == standard.render(data)
