"""Human review of existing XiaoCLifeEvent experience candidates.

Review and revocation append to the original ledger. No candidate is written
to a desktop user's private memory or granted execution authority.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from sqlalchemy import select

from modstore_server.db.xiaoc_life import XiaoCLifeEvent
from modstore_server.strategic_portfolio import PortfolioError, _row, digest
from modstore_server.xiaoc_life_policy import IDENTITY_ID, LifePolicyError
from modstore_server.xiaoc_life_reflection import (
    experience_candidate_facts,
    review_experiences,
)


def experience_scope(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Observed task category and exact comparison window, never transferable authority."""
    from modstore_server.xiaoc_life_reflection import _time

    start, end = (
        _time(candidate.get("window_start")),
        _time(candidate.get("window_end")),
    )
    metric, direction, target = (
        candidate.get("metric_id"),
        candidate.get("direction"),
        candidate.get("target"),
    )
    if (
        type(candidate.get("owner_user_id")) is not int
        or candidate["owner_user_id"] <= 0
        or not isinstance(metric, str)
        or not metric
        or direction not in ("max", "min")
        or type(target) not in (int, float)
        or (type(target) is float and not isfinite(target))
        or start is None
        or end is None
        or end <= start
        or (end - start).total_seconds() % 86400 != 0
    ):
        return None
    return {
        "category": "approved_task_with_observed_metric",
        "owner_user_id": candidate["owner_user_id"],
        "metric_id": metric,
        "direction": direction,
        "threshold": target,
        "window_days": (end - start).days,
    }


def experience_scope_matches(
    scope: dict[str, Any], hypothesis: dict[str, Any], owner_user_id: int
) -> bool:
    """A prior case may be cited in a new proposal only for the SAME measured question."""
    return (
        scope.get("category") == "approved_task_with_observed_metric"
        and type(owner_user_id) is int
        and scope.get("owner_user_id") == owner_user_id
        and scope.get("metric_id") == hypothesis.get("metric_id")
        and scope.get("direction") == hypothesis.get("direction")
        and type(scope.get("threshold")) in (int, float)
        and (type(scope["threshold"]) is int or isfinite(scope["threshold"]))
        and type(hypothesis.get("threshold")) in (int, float)
        and (type(hypothesis["threshold"]) is int or isfinite(hypothesis["threshold"]))
        and scope["threshold"] == hypothesis["threshold"]
        and type(scope.get("window_days")) is int
        and type(hypothesis.get("window_days")) is int
        and scope["window_days"] == hypothesis["window_days"]
    )


def _review_id(candidate_id: str, *, revoke: bool = False) -> str:
    return ("experience-revoke:" if revoke else "experience-review:") + digest(candidate_id)


def _validated(
    state: dict[str, Any], event: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    facts = experience_candidate_facts({**state, "events": [event]})
    if not facts:
        return None
    return event["details"]["candidate"], facts[0]


def _current_candidate(session: Any, candidate: dict[str, Any]) -> bool:
    """Read the original portfolio in the same SQL session, not the life cache."""
    try:
        row, proposal, ledger = _row(session, candidate["decision_id"], candidate["owner_user_id"])
    except PortfolioError:
        return False
    from modstore_server.business_decision_review import proposal_content

    try:
        canonical_hash = digest(proposal_content(proposal))
    except (KeyError, TypeError, ValueError):
        return False
    if (
        canonical_hash != candidate["proposal_sha256"]
        or proposal.get("proposal_sha256") != candidate["proposal_sha256"]
        or ledger.get("proposal_sha256") != candidate["proposal_sha256"]
        or row.decided_by not in ("user", "council-vote")
        or row.status not in ("approved", "executing", "completed", "reviewed")
    ):
        return False
    _, candidates = review_experiences(
        {
            **ledger,
            **proposal,
            "decision_id": candidate["decision_id"],
            "status": row.status,
        }
    )
    return any(item == candidate for item in candidates)


def _review_status(session: Any, event: dict[str, Any]) -> str:
    from modstore_server.xiaoc_life_store import _event_dict

    candidate = event["details"]["candidate"]
    expected = {
        "candidate_id": event["id"],
        "candidate_sha256": event["details"]["candidate_sha256"],
        "owner_user_id": candidate["owner_user_id"],
        "reviewer_user_id": candidate["owner_user_id"],
    }
    for revoke, allowed in (
        (True, ("revoked",)),
        (False, ("confirmed", "rejected")),
    ):
        row = session.get(XiaoCLifeEvent, _review_id(event["id"], revoke=revoke))
        if row is None:
            continue
        saved = _event_dict(row)
        if (
            row.identity_id != IDENTITY_ID
            or saved["kind"] != "experience_review"
            or saved["status"] not in allowed
            or saved["details"] != expected
            or saved["evidence_refs"] != [event["id"]]
        ):
            return "unverified"
        return str(saved["status"])
    return "pending_review"


def review_experience(
    candidate_id: str,
    *,
    candidate_sha256: str,
    action: str,
    expected_revision: int,
    actor_user_id: int,
) -> dict[str, Any]:
    """Owner-only, idempotent review. Confirmation cannot change the source."""
    from modstore_server.xiaoc_life_store import (
        _active_principal,
        _event,
        _event_dict,
        _mutate,
    )

    target_status = {
        "confirm": "confirmed",
        "reject": "rejected",
        "revoke": "revoked",
    }.get(action)
    if target_status is None:
        raise LifePolicyError("invalid experience review action")

    def apply(state: dict[str, Any], session: Any) -> dict[str, Any]:
        if (
            type(actor_user_id) is not int
            or state.get("owner_user_id") != actor_user_id
            or not _active_principal(session, actor_user_id)
        ):
            raise LifePolicyError("only the current authorized owner may review experience")
        row = session.get(XiaoCLifeEvent, candidate_id)
        if row is None or row.identity_id != IDENTITY_ID:
            raise LifePolicyError("experience candidate unavailable")
        event = _event_dict(row)
        validated = _validated(state, event)
        if validated is None or event["details"]["candidate_sha256"] != candidate_sha256:
            raise LifePolicyError("experience candidate evidence changed")
        candidate, _ = validated
        current = _review_status(session, event)
        if current == target_status:
            return {
                "candidate_id": candidate_id,
                "status": current,
                "revision": state["revision"],
            }
        if state["revision"] != expected_revision:
            raise LifePolicyError("experience review revision changed")
        if current != ("confirmed" if action == "revoke" else "pending_review"):
            raise LifePolicyError("experience review state does not permit this action")
        if action == "confirm" and not _current_candidate(session, candidate):
            raise LifePolicyError("original portfolio evidence is no longer current")
        # Invalidate in-flight cognition on a review change without adding
        # execution permissions, changing budget or rewriting the candidate.
        state["revision"] += 1
        _event(
            session,
            _review_id(candidate_id, revoke=action == "revoke"),
            kind="experience_review",
            status=target_status,
            summary="Human review of original evidence; not causal proof or execution authority.",
            evidence_refs=[candidate_id],
            details={
                "candidate_id": candidate_id,
                "candidate_sha256": candidate_sha256,
                "owner_user_id": actor_user_id,
                "reviewer_user_id": actor_user_id,
            },
        )
        return {
            "candidate_id": candidate_id,
            "status": target_status,
            "revision": state["revision"],
        }

    return _mutate(apply)


def review_facts(session: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Review-only recall with explicit provenance, applicability and conflict blocking.

    A bounded history is NOT evidence that no older conflicting record exists.
    When the review window overflows, none of its cases is eligible for reuse.
    """
    from modstore_server.xiaoc_life_store import _active_principal, _event_dict

    owner = state.get("owner_user_id")
    if type(owner) is not int or not _active_principal(session, owner):
        return []
    rows = list(
        session.scalars(
            select(XiaoCLifeEvent)
            .where(
                XiaoCLifeEvent.identity_id == IDENTITY_ID,
                XiaoCLifeEvent.kind == "experience_candidate",
            )
            .order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc())
            .limit(21)
        )
    )
    history_complete = len(rows) <= 20
    selected: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]] = []
    for row in rows[:20]:
        event = _event_dict(row)
        validated = _validated(state, event)
        if validated is None:
            history_complete = False
            continue
        candidate, fact = validated
        status = _review_status(session, event)
        if status == "unverified":
            history_complete = False
            continue
        if status not in ("confirmed", "pending_review") or not _current_candidate(
            session, candidate
        ):
            continue
        selected.append((event, fact, experience_scope(candidate), status))
    outcomes: dict[tuple[Any, ...], set[str]] = {}
    for event, _, scope, status in selected:
        if status != "confirmed" or scope is None:
            continue
        key = tuple(
            scope[field]
            for field in (
                "owner_user_id",
                "metric_id",
                "direction",
                "threshold",
                "window_days",
            )
        )
        outcomes.setdefault(key, set()).add(event["details"]["candidate"]["outcome"])
    conflicts = {key for key, values in outcomes.items() if len(values) > 1}
    # Prefer approved cases; pending cases remain visible to the owner but not cognition.
    selected.sort(key=lambda item: item[3] != "confirmed")
    facts = []
    for event, fact, scope, status in selected:
        if status == "confirmed":
            key = (
                tuple(
                    scope[field]
                    for field in (
                        "owner_user_id",
                        "metric_id",
                        "direction",
                        "threshold",
                        "window_days",
                    )
                )
                if scope is not None
                else None
            )
            blocked = (
                "conflicting_measured_outcomes"
                if key in conflicts
                else (
                    "unverified_or_truncated_review_history"
                    if not history_complete
                    else "invalid_measurement_scope" if scope is None else ""
                )
            )
            grade = {
                "evidence_grade": "verified_single_task_and_human_review",
                "causal_effect": "not_established",
                "confidence": "single_observation_not_generalizable",
                "scope": scope,
                "reuse_status": "blocked" if blocked else "advisory_proposal_only",
                "reuse_blocker": blocked or None,
            }
            fact = {
                "ref": _review_id(event["id"]),
                "text": "Historical task comparison, not a general rule or causal proof.",
                "candidate_ref": event["id"],
                "learning_assessment": grade,
                **(
                    {"experience_conflict": fact["experience_candidate"]}
                    if blocked
                    else {"reviewed_experience": fact["experience_candidate"]}
                ),
            }
        facts.append(fact)
        if len(facts) >= 2:
            break
    return facts
