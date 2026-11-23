"""Rules for comparable authoritative samples, independent of run persistence."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enterprise_cognition.goals import GoalBindingError, metric_value


class OutcomeEvidenceError(ValueError):
    """An absent or incompatible observation must not become business success."""


def observation_time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OutcomeEvidenceError("invalid_observation_time") from exc
    if result.tzinfo is None:
        raise OutcomeEvidenceError("unscoped_observation_time")
    return result.astimezone(UTC)


def metric_number(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise OutcomeEvidenceError("metric_unavailable") from exc
    if isinstance(value, bool) or not result.is_finite():
        raise OutcomeEvidenceError("metric_unavailable")
    return result


def authority_sample(
    snapshot: dict[str, Any], goal: dict[str, Any], *, scope: dict[str, str]
) -> dict[str, Any]:
    """Require the same reader scope, entity, metric unit, and authority evidence."""
    if (
        snapshot.get("freshness") != "fresh"
        or any(snapshot.get(key) != value for key, value in scope.items())
        or any(snapshot.get(key) != goal.get(key) for key in ("entity_type", "entity_id"))
        or not snapshot.get("source")
        or not snapshot.get("source_version")
        or not snapshot.get("evidence")
    ):
        raise OutcomeEvidenceError("authority_evidence_unavailable")
    for evidence in snapshot["evidence"]:
        if (
            not isinstance(evidence, dict)
            or any(evidence.get(key) != value for key, value in scope.items())
            or evidence.get("source") != snapshot["source"]
            or evidence.get("row_id") != goal["entity_id"]
            or evidence.get("observed_at") != snapshot.get("observed_at")
            or snapshot["source_version"] != "sha256:" + str(evidence.get("content_sha256") or "")
        ):
            raise OutcomeEvidenceError("authority_evidence_mismatch")
    try:
        value = metric_value(snapshot, goal["metric"], goal["unit"])
    except GoalBindingError as exc:
        raise OutcomeEvidenceError(str(exc)) from exc
    return {
        "value": str(value),
        "unit": goal["unit"],
        "source": snapshot["source"],
        "source_version": snapshot["source_version"],
        "observed_at": snapshot["observed_at"],
        "expires_at": snapshot["expires_at"],
        "evidence": copy.deepcopy(snapshot["evidence"]),
    }
