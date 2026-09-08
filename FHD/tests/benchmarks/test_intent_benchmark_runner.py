"""Evaluation failures must remain failures and predictions must be label-blind."""

import json
from types import SimpleNamespace

import pytest

from scripts.dev import intent_benchmark as runner
from scripts.dev import intent_benchmark_llm as model_runner


def test_bad_case_cannot_be_counted_as_correct(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"text": "anything"}]))
    with pytest.raises(ValueError, match="expected"):
        runner._load_cases(path)


def test_prediction_is_called_without_gold_label():
    calls = []

    def predict(text):
        calls.append(text)
        return {"intent": "products_query"}

    cases = [{"text": "opaque", "expected_route": "customers_query"}]
    result = runner._run_layer("llm", cases, model_runner.match_prediction, observer=predict)
    assert calls == ["opaque"]
    assert result["counts"]["core"] == {"correct": 0, "total": 1}
    assert result["failures"]["core"][0]["got"] == {"intent": "products_query"}


def test_exceptions_are_counted_once_without_exposing_error_text():
    def predict(text):
        raise RuntimeError("private provider response")

    result = runner._run_layer(
        "llm",
        [{"text": "x", "expected_route": "customers_query"}],
        model_runner.match_prediction,
        observer=predict,
    )
    assert len(result["failures"]["core"]) == 1
    assert result["failures"]["core"][0]["error"] == "RuntimeError"
    assert "private provider" not in json.dumps(result)


def test_negation_and_slots_are_not_silently_counted_as_success():
    assert not model_runner.match_prediction({"expect_negated": True}, {"intent": "shipment"})
    case = {"expected_route": "label_print", "expected_slots": {"quantity": 50}}
    assert not model_runner.match_prediction(
        case, {"intent": "label_print", "slots": {"quantity": 1}}
    )
    assert model_runner.match_prediction(case, {"intent": "label_print", "slots": {"quantity": 50}})


def test_model_evidence_restores_configuration_and_does_not_fabricate_responses(monkeypatch):
    from app.application import llm_intent_gate as gate
    from app.infrastructure.llm import structured_output

    marker = SimpleNamespace(model="test-only-model", data={"intent": "products"})
    monkeypatch.setattr(structured_output, "complete_structured_sync", lambda *a, **k: marker)
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "0")
    gate._cache["previous"] = (0, {"intent": "unknown"})
    try:
        with model_runner.observe_model_calls() as evidence:
            assert structured_output.complete_structured_sync([]) is marker
        assert evidence["attempted"] == evidence["completed"] == 1
        assert evidence["models"] == ["test-only-model"]
        assert "previous" in gate._cache
        assert not gate._gate_enabled()
    finally:
        gate._cache.clear()


def test_missing_model_is_not_reported_as_live_acceptance(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_load_cases", lambda path: [{"text": "hi", "check": "greeting"}])
    monkeypatch.setattr(model_runner, "predict", lambda text: {"intent": "greeting"})
    output = tmp_path / "result.json"
    assert runner.main(["--llm", "--output", str(output)]) == 2
    result = json.loads(output.read_text())
    assert result["llm"]["measurement_status"] == "unavailable_or_partial"
    assert result["llm"]["model_calls"]["completed"] == 0
