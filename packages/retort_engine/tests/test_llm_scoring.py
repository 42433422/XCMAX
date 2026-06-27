from __future__ import annotations

from pathlib import Path

import pytest

from retort_engine.llm_scoring import attach_llm_scoring, maybe_request_llm_review


def test_maybe_request_llm_review_returns_disabled_contract_when_not_enabled(tmp_path: Path) -> None:
    result = maybe_request_llm_review(
        {},
        tmp_path,
        "assess",
        "",
        "",
        [],
        [],
        request_review=lambda **_: {"status": "should_not_run"},
    )

    assert result["status"] == "disabled"
    assert result["score_source"] == "paibi_llm_disabled"


def test_attach_llm_scoring_records_completed_scores(tmp_path: Path) -> None:
    assessment = {"metadata": {}, "evidence": ["source_files=1"]}

    def request_review(**kwargs):
        assert kwargs["evidence"] == ["source_files=1", "closed_loop_five_proofs_verified=True"]
        return {"provider": "paibi", "dispatch": {"task_id": "task-1"}, "status": "accepted"}

    def wait_review(task_id: str, *, timeout_sec: float):
        return {"task_id": task_id, "status": "completed", "scores": [{"dimension": "calibrated_overall", "value": 91, "reason": "ok", "evidence": []}]}

    records = []
    result = attach_llm_scoring(
        {"use_llm": True, "wait_llm_sec": 1, "require_deep_review": True},
        assessment,
        tmp_path,
        "assess",
        "",
        "",
        [],
        request_review=request_review,
        fetch_status=lambda _: {},
        wait_review=wait_review,
        record_deep_result=lambda **kwargs: records.append(kwargs),
        absorption_evidence=lambda _project: ["closed_loop_five_proofs_verified=True"],
    )

    assert result["metadata"]["score_source"] == "paibi_llm"
    assert result["scores"][0]["value"] == 91
    assert records


def test_attach_llm_scoring_fails_closed_when_required_scores_do_not_finish(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="deep review did not complete"):
        attach_llm_scoring(
            {"use_llm": True, "wait_llm_sec": 1, "require_deep_review": True},
            {"metadata": {}, "evidence": []},
            tmp_path,
            "assess",
            "",
            "",
            [],
            request_review=lambda **_: {"provider": "paibi", "dispatch": {"task_id": "task-1"}, "status": "accepted"},
            fetch_status=lambda _: {},
            wait_review=lambda *_args, **_kwargs: {"status": "running"},
            record_deep_result=lambda **_kwargs: None,
            absorption_evidence=lambda _project: [],
        )
