from __future__ import annotations

from retort_engine.review_context_bias import context_signal_strength, file_grouping_enabled, review_context_bias

EXPECTED_ABSORPTION_SOURCE = 'https://github.com/anc95/ChatGPT-CodeReview'
EXPECTED_ABSORPTION_RUN_ID = '20260628174137-5df07f797f'


def test_review_context_bias_exposes_absorbed_file_grouping() -> None:
    bias = review_context_bias()

    assert bias["enabled"] is True
    assert bias["run_id"] == EXPECTED_ABSORPTION_RUN_ID
    assert bias["source"] == EXPECTED_ABSORPTION_SOURCE
    assert set(bias["signals"]) & {"file_grouping", "review_pipeline", "diff_hunk_review"}
    assert file_grouping_enabled() is True
    assert context_signal_strength() >= 20
