from retort_engine.review_blind_acceptance import (
    PASS_RATE_FLOOR,
    build_review_blind_acceptance,
)


def test_build_review_blind_acceptance_meets_floor() -> None:
    result = build_review_blind_acceptance(".")
    assert result["summary"]["case_count"] >= 6
    assert result["summary"]["pass_rate"] >= PASS_RATE_FLOOR
    assert result["summary"]["floor_met"] is True
    assert result["summary"]["competitor_blind_excluded"] is True
    assert result["summary"]["synthesizer_must_not_rewrite"] is True
    assert result["status"] == "ready"
    assert all("case_id" in case for case in result["cases"])


def test_review_blind_manifest_is_sealed() -> None:
    result = build_review_blind_acceptance(".")
    assert result["evidence"]["oracle"] == "precommitted_expectation_not_self_scorer"
    assert (
        "competitor_blind" not in str(result["evidence"]).lower()
        or result["summary"]["competitor_blind_excluded"]
    )
