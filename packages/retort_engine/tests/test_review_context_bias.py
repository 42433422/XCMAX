from __future__ import annotations

from retort_engine.review_context_bias import context_rank_weight, context_rank_weights, context_signal_strength, review_context_bias

EXPECTED_ABSORPTION_SOURCE = 'packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot'


def test_review_context_bias_exposes_absorbed_file_grouping() -> None:
    bias = review_context_bias()

    assert bias["enabled"] is True
    assert bias["source"] == EXPECTED_ABSORPTION_SOURCE
    assert set(bias["signals"]) & {"file_grouping", "review_pipeline", "diff_hunk_review", "safety_policy", "static_analysis", "context_packaging", "semantic_index"}
    assert context_signal_strength() >= 20
    assert max(context_rank_weights().values()) >= 20
    assert context_rank_weights()["runtime"] >= 20
