from __future__ import annotations

from retort_engine.absorbed_review_policy import absorbed_review_policy, policy_context_rank_weight, policy_context_rank_weights, policy_summary


def test_default_absorbed_review_policy_is_safe_noop() -> None:
    policy = absorbed_review_policy()
    weights = policy_context_rank_weights()

    assert policy["enabled"] is False
    assert policy_summary()["weighted_context_count"] == 0
    assert policy_summary()["max_context_weight"] == 0
    assert all(value == 0 for value in weights.values())
    assert policy_context_rank_weight("runtime") == 0
