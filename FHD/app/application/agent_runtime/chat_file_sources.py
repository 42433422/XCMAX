"""Publish bounded, host-verified file excerpts alongside an unchanged reply."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypedDict

from app.domain.task_lifecycle.agent_runtime_contract import (
    goal_answers,
    goal_evidence_snapshot,
    goal_report_coverage,
    runtime_file_evidence,
    validate_runtime_goal,
)

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun


class ChatFileSource(TypedDict):
    name: str
    excerpts: list[str]


_FILE_NAME = re.compile(r"[^/\\:\x00-\x1f\x7f]{1,255}\Z")
_PATH_TEXT = re.compile(
    r"(?i)[a-z][a-z0-9+.-]*://|[a-z]:[\\/]|(?<![\w/])(?:[~/\\]|\.{1,2}[\\/])[\w.]"
)


def released_chat_file_sources(run: AgentRun, result: dict[str, Any]) -> list[ChatFileSource]:
    """Present only references from the exact completed result and its frozen proof."""
    if (
        run.status != "completed"
        or result.get("run_id") != run.run_id
        or result.get("ok") is not True
        or result.get("execution_state") != "completed"
        or not isinstance(output := result.get("output"), str)
        or not output.strip()
    ):
        return []
    report = run.metadata.get("runtime_goal_verification") or {}
    if not isinstance(report, dict) or report.get("accepted") is not True:
        return []
    review = report.get("review")
    goals = review.get("goals") if isinstance(review, dict) else None
    if not isinstance(goals, list) or not any(
        isinstance(goal, dict) and goal.get("file_citations") for goal in goals
    ):
        return []
    try:
        if validate_runtime_goal(run) != run.metadata.get("runtime_goal_digest"):
            return []
        contract = run.metadata["runtime_goal_contract"]
        receipts, answers = result.get("business_receipts") or [], goal_answers(run)
        if not goal_report_coverage(contract, receipts, output, answers, report)["completed"]:
            return []
        snapshot = goal_evidence_snapshot(contract, receipts, output, answers)
        files = runtime_file_evidence(contract, snapshot) or {}
    except (TypeError, ValueError, KeyError):
        return []

    from app.application.agent_orchestrator.tool_permission import redact
    from app.application.ai_chat.conversation_history import _storage_safe

    public: dict[tuple[str, str], ChatFileSource] = {}
    for goal in goals:
        for citation in goal.get("file_citations") or []:
            source = files[citation["evidence_id"]]
            name, passage = source["name"].strip(), citation["source_excerpt"]
            if name in {".", ".."} or not _FILE_NAME.fullmatch(name) or redact(name) != name:
                continue
            if (
                _PATH_TEXT.search(passage)
                or redact(passage) != passage
                or _storage_safe(passage) != passage
            ):
                continue
            key = (name, source["sha256"])
            if key not in public and len(public) == 6:
                continue
            excerpts = public.setdefault(key, {"name": name, "excerpts": []})["excerpts"]
            excerpt = passage[:240].rstrip()
            if excerpt not in excerpts and len(excerpts) < 6:
                excerpts.append(excerpt)
    return list(public.values())
