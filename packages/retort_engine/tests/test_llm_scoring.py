from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.devour_session import build_devour_session
from retort_engine.llm_scoring import attach_llm_scoring, llm_external_reference
from retort_engine.paibi_llm import _extract_last_json_object


def test_resume_existing_llm_task_collects_scores_without_dispatch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    recorded: list[dict[str, Any]] = []

    def request_review(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("resume path must not dispatch a new task")

    def fetch_status(task_id: str) -> dict[str, Any]:
        assert task_id == "task-done"
        return {
            "provider": "paibi",
            "task_id": task_id,
            "status": "completed",
            "scores": [{"dimension": "calibrated_overall", "value": 87, "reason": "结构化分数"}],
            "json_result": {"score_suggestion": 87},
        }

    result = attach_llm_scoring(
        {"llm_task_id": "task-done", "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [f"root={root.name}"],
        request_review=request_review,
        wait_review=lambda *args, **kwargs: {},
        fetch_status=fetch_status,
        record_deep_result=lambda **kwargs: recorded.append(kwargs),
    )

    assert result["scores"][0]["value"] == 87
    assert result["metadata"]["score_source"] == "paibi_llm"
    assert result["metadata"]["llm_decision"] == "scored"
    assert result["metadata"]["llm_score_gate"]["scores_ready"] is True
    assert recorded and recorded[0]["status"]["task_id"] == "task-done"


def test_waiting_llm_task_is_a_recoverable_pending_gate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = attach_llm_scoring(
        {"use_llm": True, "wait_llm_sec": 1, "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [],
        request_review=lambda **kwargs: {"provider": "paibi", "status": "accepted", "dispatch": {"status": "accepted", "task_id": "task-running"}},
        wait_review=lambda task_id, **kwargs: {"provider": "paibi", "task_id": task_id, "status": "running", "subtasks": [{"status": "pending"}], "scores": []},
        fetch_status=lambda task_id: {},
        record_deep_result=lambda **kwargs: None,
    )

    assert result["scores"] == []
    assert result["metadata"]["score_source"] == "paibi_llm_pending"
    assert result["metadata"]["llm_decision"] == "awaiting_scores"
    assert result["metadata"]["llm_score_gate"]["required"] is True
    assert result["llm_pending_score"]["task_id"] == "task-running"
    session_rows = (project / ".retort" / "llm_scoring_sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(session_rows[-1])["scores_ready"] is False


def test_blocked_llm_subtask_stops_decision_without_local_scores(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = attach_llm_scoring(
        {"use_llm": True, "wait_llm_sec": 1, "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [],
        request_review=lambda **kwargs: {"provider": "paibi", "status": "accepted", "dispatch": {"status": "accepted", "task_id": "task-blocked"}},
        wait_review=lambda task_id, **kwargs: {
            "provider": "paibi",
            "task_id": task_id,
            "status": "running",
            "subtasks": [{"status": "failed", "blocked": True, "last_error": "executor missing"}],
            "scores": [],
        },
        fetch_status=lambda task_id: {},
        record_deep_result=lambda **kwargs: None,
    )

    assert result["scores"] == []
    assert result["metadata"]["score_source"] == "paibi_llm_blocked"
    assert result["metadata"]["llm_decision"] == "blocked_without_scores"
    assert result["metadata"]["llm_score_gate"]["blocked_subtask_count"] == 1


def test_stale_dispatch_llm_task_retries_once_with_new_task(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    requests: list[dict[str, Any]] = []

    def request_review(**kwargs: Any) -> dict[str, Any]:
        requests.append(kwargs)
        return {"provider": "paibi", "status": "accepted", "dispatch": {"status": "accepted", "task_id": "task-retry"}}

    def fetch_status(task_id: str) -> dict[str, Any]:
        assert task_id == "task-stale"
        return {
            "provider": "paibi",
            "task_id": task_id,
            "status": "running",
            "logs_excerpt": "依赖已满足，等待派发。 未提供远程仓库，将使用工作设备本地目录",
            "subtasks": [{"id": "sub-1", "status": "running", "progress": 0}],
            "scores": [],
        }

    result = attach_llm_scoring(
        {"llm_task_id": "task-stale", "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [],
        request_review=request_review,
        wait_review=lambda *args, **kwargs: {},
        fetch_status=fetch_status,
        record_deep_result=lambda **kwargs: None,
    )

    assert len(requests) == 1
    assert requests[0]["metadata"]["llm_retry"]["from_task_id"] == "task-stale"
    assert result["llm_retry"]["reason"] == "stale_dispatch"
    assert result["llm_retry"]["from_task_id"] == "task-stale"
    assert result["llm_retry"]["to_task_id"] == "task-retry"
    assert result["metadata"]["score_source"] == "paibi_llm_pending"
    assert result["metadata"]["llm_decision"] == "awaiting_scores"
    assert result["metadata"]["llm_task_id"] == "task-retry"
    assert result["metadata"]["llm_retry_from_task_id"] == "task-stale"
    assert result["llm_pending_score"]["task_id"] == "task-retry"


def test_stale_dispatch_without_retry_is_blocked_not_pending(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = attach_llm_scoring(
        {"llm_task_id": "task-stale", "disable_llm_retry": True, "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [],
        request_review=lambda **kwargs: (_ for _ in ()).throw(AssertionError("retry disabled")),
        wait_review=lambda *args, **kwargs: {},
        fetch_status=lambda task_id: {
            "provider": "paibi",
            "task_id": task_id,
            "status": "running",
            "logs_excerpt": "waiting for dispatch",
            "subtasks": [{"id": "sub-1", "status": "running", "progress": 0}],
            "scores": [],
        },
        record_deep_result=lambda **kwargs: None,
    )

    assert result["metadata"]["score_source"] == "paibi_llm_blocked"
    assert result["metadata"]["llm_score_gate"]["blockers"][0]["kind"] == "stale_dispatch"


def test_outbox_dispatch_is_unavailable_not_completed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = attach_llm_scoring(
        {"use_llm": True, "require_deep_review": True},
        {"project": str(project), "scores": [], "evidence": [], "metadata": {}},
        project,
        "assess",
        "",
        "",
        [],
        evidence_builder=lambda root: [],
        request_review=lambda **kwargs: {"provider": "paibi", "status": "queued_outbox", "dispatch": {"dispatcher": "paibi_outbox", "status": "queued_outbox"}},
        wait_review=lambda *args, **kwargs: {},
        fetch_status=lambda task_id: {},
        record_deep_result=lambda **kwargs: None,
    )

    assert result["metadata"]["score_source"] == "paibi_llm_unavailable"
    assert result["metadata"]["llm_decision"] == "queued_outbox_no_scores"
    assert result["llm_pending_score"]["required"] is True


def test_llm_external_reference_uses_absorption_state_when_missing() -> None:
    metadata = {"absorption_state": {"source": "https://github.com/example/upstream", "external_path": "/tmp/upstream"}}

    source, path = llm_external_reference(metadata, "", "")

    assert source == "https://github.com/example/upstream"
    assert path == "/tmp/upstream"


def test_devour_session_marks_pending_and_blocked_final_reviews(tmp_path: Path) -> None:
    base = {"project": "own", "scores": [], "evidence": ["source_files=7"], "metadata": {}}
    pending = {**base, "metadata": {"score_source": "paibi_llm_pending", "llm_task_id": "task-1"}}
    blocked = {**base, "metadata": {"score_source": "paibi_llm_blocked", "llm_task_id": "task-2"}}

    pending_session = build_devour_session(
        source="upstream",
        external_path=tmp_path,
        pre_assessment=base,
        external_assessment=base,
        own_assessment=pending,
        tasks=[],
        execution={"status": "applied", "gates_passed": True},
        branch_state={},
        absorption_state={},
        llm_review={"dispatch": {"status": "accepted", "task_id": "task-1"}},
    )
    blocked_session = build_devour_session(
        source="upstream",
        external_path=tmp_path,
        pre_assessment=base,
        external_assessment=base,
        own_assessment=blocked,
        tasks=[],
        execution={"status": "applied", "gates_passed": True},
        branch_state={},
        absorption_state={},
        llm_review={"dispatch": {"status": "accepted", "task_id": "task-2"}},
    )

    assert pending_session["status"] == "absorbed_awaiting_final_llm_score"
    assert pending_session["final_self_review"]["status"] == "paibi_llm_pending"
    assert blocked_session["status"] == "final_deep_review_blocked"
    assert blocked_session["final_self_review"]["status"] == "paibi_llm_blocked"


def test_paibi_log_json_extraction_prefers_last_scored_object() -> None:
    first = {"score_suggestion": 72, "scores": [{"dimension": "calibrated_overall", "value": 72}]}
    last = {"score_suggestion": 88, "scores": [{"dimension": "calibrated_overall", "value": 88}]}

    result = _extract_last_json_object(f"old {json.dumps(first)}\nnew {json.dumps(last)}")

    assert result == last
