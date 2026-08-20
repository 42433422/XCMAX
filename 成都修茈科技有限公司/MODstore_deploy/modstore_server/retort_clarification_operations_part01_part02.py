# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.retort_clarification_gate")


def evaluate_retort_clarification_gate(
    *,
    strategy_intent: str,
    changed_files: _facade().Sequence[_facade().Any] | None = None,
    change_request_id: int | None = None,
    proposal_id: str = "",
    run_id: str = "",
    package_id: str = "",
    auto_open: bool = True,
) -> dict[str, _facade().Any]:
    """Evaluate Retort seat with clarification loop.

    Returns effective strategy_intent, alignment assessment, blockers, and
    clarification session summary. Never leaves stale open sessions un-swept.
    """
    sweep = _facade().sweep_expired_clarifications()
    if not _facade().gate_enabled():
        assess = _facade()._load_alignment()
        assessment = assess(
            _facade()._normalize_changed_for_alignment(changed_files),
            issue_context=_facade()._text(strategy_intent, 4000),
        )
        return {
            "ok": True,
            "enabled": False,
            "effective_strategy_intent": _facade()._text(strategy_intent, 4000),
            "assessment": assessment,
            "blockers": [],
            "clarification": None,
            "sweep": sweep,
        }
    subject = _facade()._subject_key(
        change_request_id=change_request_id,
        proposal_id=proposal_id,
        run_id=run_id,
        package_id=package_id,
    )
    session = _facade()._latest_session_for_subject(subject)
    intent = _facade()._text(strategy_intent, 4000)
    blockers: list[str] = []
    if session and session.get("status") == _facade()._STATUS_ANSWERED:
        intent = _facade()._text(session.get("enriched_strategy_intent") or intent, 4000)
    elif session and session.get("status") == _facade()._STATUS_OPEN:
        blockers.append("retort_clarification_pending")
    elif session and session.get("status") == _facade()._STATUS_EXPIRED:
        fallback = _facade()._text(
            session.get("expire_fallback") or _facade().expire_fallback(), 32
        )
        if fallback == "degrade_intent":
            pass
        elif fallback == "cancel":
            blockers.append("retort_clarification_cancelled")
        else:
            blockers.append("retort_clarification_expired")
    assess = _facade()._load_alignment()
    assessment = assess(
        _facade()._normalize_changed_for_alignment(changed_files), issue_context=intent
    )
    _, needed, _ = _facade()._load_clarification_builder()
    if (
        auto_open
        and "retort_clarification_pending" not in blockers
        and ("retort_clarification_expired" not in blockers)
        and ("retort_clarification_cancelled" not in blockers)
        and needed(assessment, intent, changed_files=changed_files)
        and (not (session and session.get("status") == _facade()._STATUS_ANSWERED))
    ):
        opened = _facade().open_clarification_session(
            strategy_intent=intent,
            changed_files=changed_files,
            change_request_id=change_request_id,
            proposal_id=proposal_id,
            run_id=run_id,
            package_id=package_id,
            source="council_evaluate",
        )
        session = opened.get("session") if isinstance(opened.get("session"), dict) else session
        if opened.get("opened") or opened.get("reused"):
            blockers.append("retort_clarification_pending")
    if session and session.get("status") == _facade()._STATUS_ANSWERED:
        assessment = assess(
            _facade()._normalize_changed_for_alignment(changed_files),
            issue_context=intent,
        )
        if assessment.get("status") == "aligned" and session.get("session_id"):
            _facade().mark_clarification_resolved(str(session.get("session_id")))
            session = _facade().get_clarification(str(session.get("session_id"))) or session
    aligned = (
        assessment.get("status") == "aligned" and "retort_clarification_pending" not in blockers
    )
    if assessment.get("status") == "misaligned" and "retort_clarification_pending" not in blockers:
        blockers.append("retort_intent_misaligned")
    return {
        "ok": True,
        "enabled": True,
        "aligned": aligned,
        "effective_strategy_intent": intent,
        "assessment": assessment,
        "blockers": list(dict.fromkeys(blockers)),
        "clarification": session,
        "sweep": _facade().sweep_expired_clarifications() if sweep.get("expired_count") else sweep,
    }


def clarification_blocks_auto_approve(
    change_request_id: int,
) -> dict[str, _facade().Any]:
    """Return blocking info for maybe_auto_approve."""
    _facade().sweep_expired_clarifications()
    subject = _facade()._subject_key(change_request_id=int(change_request_id))
    session = _facade()._latest_session_for_subject(subject)
    if not session:
        return {"blocked": False, "reason": "no_session"}
    status = str(session.get("status") or "")
    if status == _facade()._STATUS_OPEN:
        return {
            "blocked": True,
            "reason": "retort_clarification_pending",
            "session_id": session.get("session_id"),
            "expires_at": session.get("expires_at"),
        }
    if status == _facade()._STATUS_EXPIRED and _facade().expire_fallback() != "degrade_intent":
        return {
            "blocked": True,
            "reason": "retort_clarification_expired",
            "session_id": session.get("session_id"),
        }
    if (
        status == _facade()._STATUS_CANCELLED
        and str(session.get("cancel_reason") or "") != "superseded"
    ):
        return {
            "blocked": True,
            "reason": "retort_clarification_cancelled",
            "session_id": session.get("session_id"),
        }
    return {
        "blocked": False,
        "reason": f"status={status}",
        "session_id": session.get("session_id"),
    }
