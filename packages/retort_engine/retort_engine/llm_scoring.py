from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


RequestReview = Callable[..., dict[str, Any]]
FetchStatus = Callable[[str], dict[str, Any]]
WaitReview = Callable[..., dict[str, Any]]
RecordDeepResult = Callable[..., None]
EvidenceProvider = Callable[[Path], list[str]]


def attach_llm_scoring(
    payload: dict[str, Any],
    assessment: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    tasks: list[dict[str, Any]],
    *,
    request_review: RequestReview,
    fetch_status: FetchStatus,
    wait_review: WaitReview,
    record_deep_result: RecordDeepResult,
    absorption_evidence: EvidenceProvider,
) -> dict[str, Any]:
    require_deep = bool(payload.get("require_deep_review") or payload.get("require_llm_scores"))
    if not llm_enabled(payload):
        metadata = assessment.setdefault("metadata", {})
        disabled = llm_disabled_review(require_deep=require_deep)
        assessment["llm_review"] = disabled
        metadata["score_source"] = disabled["score_source"]
        if require_deep:
            raise RuntimeError("PaiBi LLM scoring is required; local scoring has been removed")
        return assessment
    metadata = assessment.get("metadata", {}) if isinstance(assessment.get("metadata"), dict) else {}
    external_source, external_path = llm_external_reference(metadata, external_source, external_path)
    evidence = list(assessment.get("evidence", []))
    evidence.extend(absorption_evidence(project))
    review = maybe_request_llm_review(
        payload,
        project,
        mode,
        external_source,
        external_path,
        [],
        tasks,
        evidence=evidence,
        metadata=metadata,
        request_review=request_review,
    )
    assessment["llm_review"] = review
    metadata = assessment.setdefault("metadata", {})
    metadata["score_source"] = "paibi_llm_pending"
    wait_sec = float(payload.get("wait_llm_sec") or payload.get("wait_llm_seconds") or 0)
    task_id = str((review.get("dispatch") or {}).get("task_id") or "")
    status: dict[str, Any] = {}
    if wait_sec > 0 and task_id:
        status = wait_review(task_id, timeout_sec=wait_sec)
    elif payload.get("llm_task_id"):
        status = fetch_status(str(payload.get("llm_task_id")))
    if status:
        assessment["llm_review_status"] = status
        if status.get("scores"):
            assessment["scores"] = status["scores"]
            metadata["score_source"] = "paibi_llm"
            metadata["llm_task_id"] = status.get("task_id")
            if require_deep:
                record_deep_result(project=project, mode=mode, review=review, status=status)
    if require_deep and metadata.get("score_source") != "paibi_llm":
        current = str((status or {}).get("status") or review.get("status") or (review.get("dispatch") or {}).get("status") or "not_completed")
        metadata["score_source"] = "paibi_llm_required_not_completed"
        raise RuntimeError(f"PaiBi LLM deep review did not complete with scores; current status: {current}")
    return assessment


def maybe_request_llm_review(
    payload: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    scores: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    request_review: RequestReview,
) -> dict[str, Any]:
    if not llm_enabled(payload):
        return llm_disabled_review(require_deep=bool(payload.get("require_deep_review") or payload.get("require_llm_scores")))
    review = request_review(
        project=str(project),
        mode=mode,
        external_source=external_source,
        external_path=external_path,
        scores=scores,
        tasks=tasks,
        evidence=evidence or [],
        metadata=metadata or {},
        record=False,
    )
    review["enabled"] = True
    return review


def llm_external_reference(metadata: dict[str, Any], external_source: str, external_path: str) -> tuple[str, str]:
    state = metadata.get("absorption_state") if isinstance(metadata.get("absorption_state"), dict) else {}
    if not external_source:
        external_source = str(state.get("source") or "")
    if not external_path:
        external_path = str(state.get("external_path") or "")
    return external_source, external_path


def llm_enabled(payload: dict[str, Any]) -> bool:
    return bool(payload.get("use_llm") or payload.get("paibi_llm") or payload.get("llm_review"))


def llm_disabled_review(*, require_deep: bool = False) -> dict[str, Any]:
    return {
        "enabled": False,
        "provider": "paibi",
        "status": "disabled",
        "score_source": "paibi_llm_required" if require_deep else "paibi_llm_disabled",
        "reason": "llm_deep_review_required" if require_deep else "llm_not_requested",
        "dispatch": {"status": "disabled"},
    }
