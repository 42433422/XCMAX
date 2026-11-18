"""Failures, actual predictions and model-call evidence govern intent acceptance."""

from __future__ import annotations

import json
import os

import pytest

from scripts.dev import intent_benchmark as runner
from scripts.dev import intent_benchmark_llm as model


def completion(intent="customers", slots=None):
    return {
        "model": "test-provider-model",
        "choices": [{"message": {"content": json.dumps({"intent": intent, "slots": slots or {}})}}],
    }


@pytest.mark.parametrize(
    ("case", "result", "expected"),
    [
        ({"check": "help"}, {}, False),
        ({"check": "help"}, {"is_help": True}, True),
        ({"check": "help"}, {"is_help": True, "tool_key": "customers"}, False),
        ({"expect_negated": True}, {}, False),
        ({"expect_negated": True}, {"is_negated": True}, True),
        ({"expect_negated": True}, {"is_negated": True, "tool_key": "wechat_send"}, False),
        ({"expected_out_of_scope": True}, {"tool_key": "customers"}, False),
        ({"expected_out_of_scope": True}, {}, True),
        ({"expected_out_of_scope": True}, {"is_greeting": True}, False),
        ({}, {}, False),
    ],
)
def test_rule_matcher_scores_every_outcome(case, result, expected):
    assert runner.match_rule_result(case, result) is expected


def test_confusion_predictions_are_independent_of_expected_labels(monkeypatch):
    from app.domain.shared_services import intent_service

    monkeypatch.setattr(intent_service, "recognize_intents", lambda text: {"tool_key": "materials"})
    rows = runner._run_holdout_round(
        [
            {"text": "同一个输入", "check": "greeting"},
            {"text": "同一个输入", "expect_negated": True},
        ]
    )
    assert [row["predicted_domain"] for row in rows] == ["inventory", "inventory"]
    assert not any(row["correct"] for row in rows)


def test_model_samples_call_the_gateway_independently(monkeypatch):
    calls = []

    def gateway(**kwargs):
        calls.append(kwargs)
        return completion(slots={"unit_name": "客户甲"})

    monkeypatch.setattr(model, "request_planner_completion", gateway)
    with model.observe_model_calls() as evidence:
        assert model.predict("客户甲") == model.predict("客户甲")
    assert len(calls) == evidence["attempted"] == evidence["completed"] == 2
    assert evidence["errors"] == []
    assert evidence["models"] == ["test-provider-model"]
    assert calls[0]["messages"][-1] == {"role": "user", "content": "客户甲"}
    assert "expected" not in str(calls)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        completion("invented_route"),
        completion(slots={}) | {"choices": [{"message": {"tool_calls": [{}]}}]},
    ],
)
def test_unavailable_or_malformed_model_result_is_never_completed(monkeypatch, payload):
    monkeypatch.setattr(model, "request_planner_completion", lambda **kwargs: payload)
    with model.observe_model_calls() as evidence, pytest.raises((ValueError, RuntimeError)):
        model.predict("查询客户")
    assert evidence["attempted"] == 1
    assert evidence["completed"] == 0
    assert len(evidence["errors"]) == 1


def test_model_matcher_checks_slots_and_special_outcomes():
    assert model.match_prediction({"check": "help"}, {"intent": "help"})
    assert not model.match_prediction({"expect_negated": True}, {"intent": "wechat_send"})
    assert model.match_prediction({"expected_out_of_scope": True}, {"intent": "out_of_scope"})
    case = {"expected_tool": "customers", "expected_slots": {"keyword": "甲"}}
    assert not model.match_prediction(case, {"intent": "customers", "slots": {"keyword": "乙"}})
    assert model.match_prediction(case, {"intent": "customers", "slots": {"keyword": "甲"}})


@pytest.fixture
def one_case(monkeypatch, tmp_path):
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps([{"text": "客户名册", "domain": "customers", "expected_tool": "customers"}])
    )
    monkeypatch.setattr(runner, "HOLDOUT_PATH", dataset)
    monkeypatch.setattr(runner, "GOLDEN_PATH", dataset)
    monkeypatch.setattr(runner, "HOLDOUT_BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.setenv("XCAGI_BENCH_LLM_SLEEP", "0")
    return tmp_path / "report.json"


@pytest.mark.parametrize(
    "flags", [["--holdout", "--check"], ["--holdout", "--record"], ["--check"]]
)
def test_incomplete_model_cannot_be_hidden_by_ratchet_or_record(monkeypatch, one_case, flags):
    monkeypatch.setattr(model, "request_planner_completion", lambda **kwargs: None)
    monkeypatch.setattr(runner, "_check_holdout_ratchet", lambda result: 0)
    monkeypatch.setattr(runner, "_check_ratchet", lambda result: 0)
    assert runner.main([*flags, "--llm", "--output", str(one_case)]) == 2
    assert not runner.HOLDOUT_BASELINE_PATH.exists()
    report = json.loads(one_case.read_text())
    assert report["llm"]["measurement_status"] == "unavailable_or_partial"


def test_holdout_threshold_applies_to_every_model_repetition(monkeypatch, one_case):
    answers = iter([completion("customers"), completion("products")])
    monkeypatch.setattr(model, "request_planner_completion", lambda **kwargs: next(answers))
    assert (
        runner.main(
            [
                "--holdout",
                "--llm",
                "--repeat",
                "2",
                "--min-routing-accuracy",
                "0.9",
                "--output",
                str(one_case),
            ]
        )
        == 1
    )
    report = json.loads(one_case.read_text())
    assert report["llm"]["round_accuracy"] == [1.0, 0.0]
    assert report["llm"]["model_calls"]["completed"] == 2
    assert len(report["llm"]["later_rounds"]) == 1
    assert isinstance(report["tracked_source_dirty"], bool)
    assert report["execution_mode"] == "rule_and_model_classification"


def test_rule_only_overrides_and_restores_both_semantic_engines(monkeypatch, one_case):
    from app.domain.shared_services import intent_service

    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("XCAGI_INTENT_ENGINE", "on")
    observed = []

    def recognize(text):
        observed.append(
            (os.environ["FHD_INTENT_SEMANTIC_ENABLED"], os.environ["XCAGI_INTENT_ENGINE"])
        )
        return {"tool_key": "customers"}

    monkeypatch.setattr(intent_service, "recognize_intents", recognize)
    assert runner.main(["--output", str(one_case)]) == 0
    assert observed == [("0", "off")]
    assert os.environ["FHD_INTENT_SEMANTIC_ENABLED"] == "1"
    assert os.environ["XCAGI_INTENT_ENGINE"] == "on"


def test_partial_or_cached_model_count_cannot_claim_complete_measurement():
    assert (
        runner._measurement_status({"attempted": 1, "completed": 1, "errors": []}, 2)
        == "unavailable_or_partial"
    )
    assert (
        runner._measurement_status({"attempted": 2, "completed": 1, "errors": []}, 2)
        == "unavailable_or_partial"
    )
    assert (
        runner._measurement_status({"attempted": 2, "completed": 2, "errors": []}, 2) == "measured"
    )


def test_zero_model_threshold_is_not_an_acceptance_gate():
    with pytest.raises(SystemExit) as stopped:
        runner.main(["--llm", "--min-routing-accuracy", "0"])
    assert stopped.value.code == 2
