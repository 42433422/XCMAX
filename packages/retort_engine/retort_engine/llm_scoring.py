from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from retort_engine.paibi_status import analyze_task_blockers


EvidenceBuilder = Callable[[Path], list[str]]
ReviewRequester = Callable[..., dict[str, Any]]
StatusFetcher = Callable[[str], dict[str, Any]]
StatusWaiter = Callable[..., dict[str, Any]]
DeepResultRecorder = Callable[..., None]


def attach_llm_scoring(
    payload: dict[str, Any],
    assessment: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    tasks: list[dict[str, Any]],
    *,
    evidence_builder: EvidenceBuilder,
    request_review: ReviewRequester,
    wait_review: StatusWaiter,
    fetch_status: StatusFetcher,
    record_deep_result: DeepResultRecorder,
) -> dict[str, Any]:
    require_deep = llm_requires_deep_review(payload)
    metadata = assessment.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        assessment["metadata"] = metadata
    external_source, external_path = llm_external_reference(metadata, external_source, external_path)
    evidence = list(assessment.get("evidence", []))
    evidence.extend(evidence_builder(project))

    review = _review_or_resume(
        payload,
        project,
        mode,
        external_source,
        external_path,
        tasks,
        evidence,
        metadata,
        request_review,
    )
    assessment["llm_review"] = review
    if review.get("status") == "disabled":
        _mark_disabled(metadata, review, require_deep)
        _record_scoring_session(project, mode, review, {}, metadata)
        return assessment

    status = _collect_status(payload, review, wait_review, fetch_status)
    if status:
        assessment["llm_review_status"] = status
    retry = _retry_stale_dispatch_if_needed(
        payload,
        project,
        mode,
        external_source,
        external_path,
        tasks,
        evidence,
        metadata,
        review,
        status,
        request_review,
    )
    if retry:
        assessment["llm_retry"] = retry
        review = retry["review"]
        assessment["llm_review"] = review
        retry_payload = {**payload, "llm_task_id": "", "llm_retry_attempted": True}
        status = _collect_status(retry_payload, review, wait_review, fetch_status)
        if status:
            assessment["llm_review_status"] = status
        else:
            assessment.pop("llm_review_status", None)
    scores = status.get("scores") if isinstance(status, dict) else []
    if isinstance(scores, list) and scores:
        assessment["scores"] = scores
        metadata["score_source"] = "paibi_llm"
        metadata["llm_decision"] = "scored"
        metadata["llm_task_id"] = _task_id(payload, review, status)
        metadata["llm_score_gate"] = _score_gate("scored", require_deep, metadata.get("llm_task_id"), status)
        record_deep_result(project=project, mode=mode, review=review, status=status)
        _record_scoring_session(project, mode, review, status, metadata)
        return assessment

    _mark_pending_or_blocked(metadata, payload, review, status, require_deep)
    assessment["llm_pending_score"] = {
        "task_id": metadata.get("llm_task_id", ""),
        "score_source": metadata.get("score_source", ""),
        "decision": metadata.get("llm_decision", ""),
        "status": (status or {}).get("status") or review.get("status") or (review.get("dispatch") or {}).get("status") or "",
        "required": require_deep,
    }
    _record_scoring_session(project, mode, review, status, metadata)
    return assessment


def llm_external_reference(metadata: dict[str, Any], external_source: str, external_path: str) -> tuple[str, str]:
    state = metadata.get("absorption_state") if isinstance(metadata.get("absorption_state"), dict) else {}
    if not external_source:
        external_source = str(state.get("source") or "")
    if not external_path:
        external_path = str(state.get("external_path") or "")
    return external_source, external_path


def llm_requires_deep_review(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("require_deep_review")
        or payload.get("require_llm_scores")
        or payload.get("require_llm")
        or payload.get("llm_required")
    )


def llm_enabled(payload: dict[str, Any]) -> bool:
    return bool(payload.get("use_llm") or payload.get("paibi_llm") or payload.get("llm_review") or payload.get("llm_task_id"))


def llm_disabled_review(*, require_deep: bool = False) -> dict[str, Any]:
    return {
        "enabled": False,
        "provider": "paibi",
        "status": "disabled",
        "score_source": "paibi_llm_required" if require_deep else "paibi_llm_disabled",
        "reason": "llm_deep_review_required" if require_deep else "llm_not_requested",
        "dispatch": {"status": "disabled"},
    }


def _review_or_resume(
    payload: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    tasks: list[dict[str, Any]],
    evidence: list[str],
    metadata: dict[str, Any],
    request_review: ReviewRequester,
) -> dict[str, Any]:
    existing_task_id = str(payload.get("llm_task_id") or "").strip()
    if existing_task_id and not _truthy(payload.get("force_new_llm_review")):
        return {
            "enabled": True,
            "provider": "paibi",
            "status": "resume_existing",
            "dispatch": {"status": "resume_existing", "task_id": existing_task_id},
        }
    if not llm_enabled(payload):
        return llm_disabled_review(require_deep=llm_requires_deep_review(payload))
    review = request_review(
        project=str(project),
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        scores=[],
        tasks=tasks,
        evidence=evidence,
        metadata=metadata,
        record=False,
    )
    review["enabled"] = True
    return review


def _collect_status(payload: dict[str, Any], review: dict[str, Any], wait_review: StatusWaiter, fetch_status: StatusFetcher) -> dict[str, Any]:
    task_id = _task_id(payload, review, {})
    wait_sec = float(payload.get("wait_llm_sec") or payload.get("wait_llm_seconds") or 0)
    if wait_sec > 0 and task_id:
        return wait_review(task_id, timeout_sec=wait_sec)
    if task_id and payload.get("llm_task_id"):
        return fetch_status(task_id)
    return {}


def _mark_disabled(metadata: dict[str, Any], review: dict[str, Any], require_deep: bool) -> None:
    metadata["score_source"] = "paibi_llm_required_but_disabled" if require_deep else review.get("score_source", "paibi_llm_disabled")
    metadata["llm_decision"] = "blocked_llm_disabled" if require_deep else "disabled_no_scores"
    metadata["llm_score_gate"] = _score_gate(str(metadata["llm_decision"]), require_deep, "", {})


def _mark_pending_or_blocked(
    metadata: dict[str, Any],
    payload: dict[str, Any],
    review: dict[str, Any],
    status: dict[str, Any],
    require_deep: bool,
) -> None:
    task_id = _task_id(payload, review, status)
    current = str((status or {}).get("status") or review.get("status") or (review.get("dispatch") or {}).get("status") or "not_completed")
    blocked = current in {"failed", "blocked"} or bool(_blocked_subtasks(status)) or bool(_status_blockers(status))
    unavailable = str((review.get("dispatch") or {}).get("dispatcher") or review.get("dispatcher") or "") == "paibi_outbox"
    if blocked:
        source = "paibi_llm_blocked"
        decision = "blocked_without_scores"
    elif unavailable:
        source = "paibi_llm_unavailable"
        decision = "queued_outbox_no_scores"
    else:
        source = "paibi_llm_pending"
        decision = "awaiting_scores"
    metadata["score_source"] = source
    metadata["llm_decision"] = decision
    metadata["llm_task_id"] = task_id
    metadata["llm_required"] = require_deep
    metadata["llm_score_gate"] = _score_gate(decision, require_deep, task_id, status)


def _score_gate(decision: str, required: bool, task_id: str | Any, status: dict[str, Any]) -> dict[str, Any]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    blockers = _status_blockers(status)
    return {
        "decision": decision,
        "required": required,
        "scores_ready": decision == "scored",
        "task_id": str(task_id or ""),
        "status": str(status.get("status") or ""),
        "blocked_subtask_count": len(_blocked_subtasks(status)),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "subtask_count": len(subtasks),
    }


def _blocked_subtasks(status: dict[str, Any]) -> list[dict[str, Any]]:
    subtasks = status.get("subtasks") if isinstance(status.get("subtasks"), list) else []
    return [
        subtask
        for subtask in subtasks
        if isinstance(subtask, dict) and (bool(subtask.get("blocked")) or str(subtask.get("status") or "") in {"failed", "blocked"})
    ]


def _status_blockers(status: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(status, dict) or not status:
        return []
    blockers = status.get("blockers")
    if isinstance(blockers, list):
        return [item for item in blockers if isinstance(item, dict)]
    return analyze_task_blockers(status)


def _retry_stale_dispatch_if_needed(
    payload: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    tasks: list[dict[str, Any]],
    evidence: list[str],
    metadata: dict[str, Any],
    review: dict[str, Any],
    status: dict[str, Any],
    request_review: ReviewRequester,
) -> dict[str, Any] | None:
    if _truthy(payload.get("disable_llm_retry")) or _truthy(payload.get("llm_retry_attempted")):
        return None
    if not any(str(blocker.get("kind") or "") == "stale_dispatch" for blocker in _status_blockers(status)):
        return None
    from_task_id = _task_id(payload, review, status)
    retry_metadata = {
        **metadata,
        "llm_retry": {
            "reason": "stale_dispatch",
            "from_task_id": from_task_id,
        },
    }
    retry_review = request_review(
        project=str(project),
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        scores=[],
        tasks=tasks,
        evidence=evidence,
        metadata=retry_metadata,
        record=False,
    )
    retry_review["enabled"] = True
    to_task_id = _task_id({}, retry_review, {})
    metadata["llm_retry_reason"] = "stale_dispatch"
    metadata["llm_retry_from_task_id"] = from_task_id
    metadata["llm_retry_to_task_id"] = to_task_id
    metadata["llm_retry_status"] = retry_review.get("status", "")
    return {
        "reason": "stale_dispatch",
        "from_task_id": from_task_id,
        "to_task_id": to_task_id,
        "status": retry_review.get("status", ""),
        "review": retry_review,
    }


def _task_id(payload: dict[str, Any], review: dict[str, Any], status: dict[str, Any]) -> str:
    dispatch = review.get("dispatch") if isinstance(review.get("dispatch"), dict) else {}
    return str(status.get("task_id") or dispatch.get("task_id") or payload.get("llm_task_id") or "")


def _record_scoring_session(root: Path, mode: str, review: dict[str, Any], status: dict[str, Any], metadata: dict[str, Any]) -> None:
    path = root / ".retort" / "llm_scoring_sessions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "score_source": metadata.get("score_source"),
        "llm_decision": metadata.get("llm_decision"),
        "task_id": metadata.get("llm_task_id", ""),
        "review_status": review.get("status"),
        "status": status.get("status") if isinstance(status, dict) else "",
        "scores_ready": bool(status.get("scores")) if isinstance(status, dict) else False,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "off", "no", "disabled"}
    return bool(value)
