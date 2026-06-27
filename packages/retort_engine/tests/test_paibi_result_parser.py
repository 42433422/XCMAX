from __future__ import annotations

from retort_engine.paibi_result_parser import extract_last_json_object, normalize_llm_scores


def test_extract_last_json_object_prefers_latest_scoring_payload() -> None:
    text = """
    noise {"score_suggestion": 61, "reason": "early draft"}
    more logs {"scores": [{"dimension": "calibrated_overall", "value": 88, "reason": "final", "evidence": ["gate"]}]}
    """

    parsed = extract_last_json_object(text)

    assert parsed is not None
    assert parsed["scores"][0]["value"] == 88


def test_normalize_llm_scores_clamps_and_filters_dimensions() -> None:
    scores = normalize_llm_scores(
        {
            "scores": [
                {"dimension": "calibrated_overall", "value": 120, "reason": "too high", "evidence": ["x"]},
                {"dimension": "unknown", "value": 50},
            ]
        }
    )

    assert scores == [{"dimension": "calibrated_overall", "value": 100.0, "reason": "too high", "evidence": ["x"]}]


def test_normalize_llm_scores_promotes_score_suggestion() -> None:
    scores = normalize_llm_scores({"score_suggestion": 73.26})

    assert scores == [{"dimension": "calibrated_overall", "value": 73.3, "reason": "LLM score_suggestion normalized as calibrated_overall.", "evidence": []}]
