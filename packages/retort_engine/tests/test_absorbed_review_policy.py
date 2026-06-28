from __future__ import annotations

from retort_engine.absorbed_review_policy import absorbed_review_policy, policy_context_rank_weight, policy_context_rank_weights, policy_summary

EXPECTED_ABSORPTION_SOURCE = 'packages/retort_engine/.retort/cache/github/mopemope/pr-ai-review-bot'


def test_absorbed_review_policy_changes_ranking_weights() -> None:
    policy = absorbed_review_policy()
    weights = policy_context_rank_weights()

    assert policy["enabled"] is True
    assert policy["source"] == EXPECTED_ABSORPTION_SOURCE
    assert policy_summary()["weighted_context_count"] >= 3
    assert policy_summary()["max_context_weight"] >= 15
    assert max(weights.values()) >= 15
    assert policy_context_rank_weight("runtime") >= 15
