"""Bounded, receipt-only checkpoints of the existing LangGraph effect boundary.

A checkpoint is evidence that a node returned, not business authority. No
checkpoint may invoke a model, dispatch work, or bypass original receipt checks.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

SCHEMA = "xiaoc-life-graph-receipt/v1"
PHASES = ("act", "reflect")
STATUSES = {"completed", "failed", "blocked", "waiting", "awaiting_worker", "interrupted"}


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _refs(values: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(value for value in values if isinstance(value, str) and 0 < len(value) <= 256)
    )[:32]


def make_checkpoint(
    claim: dict[str, Any],
    phase: str,
    *,
    result: dict[str, Any],
    actual_tokens: int | None,
    evidence_refs: list[str],
    reflection_status: str | None,
    recorded_at: str,
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError("checkpoint requires a returned effect or reflection node")
    if actual_tokens is not None and (type(actual_tokens) is not int or actual_tokens < 0):
        raise ValueError("invalid reported usage")
    result_refs: list[str] = []
    for goal in result.get("goals") or []:
        if not isinstance(goal, dict):
            continue
        for key, prefix in (
            ("id", "goal"),
            ("decision_id", "portfolio"),
            ("retort_request_id", "retort"),
        ):
            value = goal.get(key)
            if isinstance(value, str) and 0 < len(value) <= 240:
                result_refs.append(f"{prefix}:{value}")
    reported_status = result.get("status")
    body = {
        "schema": SCHEMA,
        "cycle_id": claim["cycle_id"],
        "owner_user_id": claim["owner_user_id"],
        "policy_revision": claim["policy_revision"],
        "phase": phase,
        "recorded_at": recorded_at,
        "reported_status": (
            reported_status
            if isinstance(reported_status, str) and reported_status in STATUSES
            else "unknown"
        ),
        "reported_tokens": actual_tokens,
        "evidence_refs": _refs(evidence_refs),
        "result_refs": _refs(result_refs),
        "reflection_status": (
            reflection_status
            if isinstance(reflection_status, str)
            and 0 < len(reflection_status) <= 64
            and reflection_status.replace("_", "").isalnum()
            else None
        ),
    }
    return {**body, "sha256": _digest(body)}


def _validated_body(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    body = {key: value for key, value in entry.items() if key != "sha256"}
    if set(body) != {
        "schema",
        "cycle_id",
        "owner_user_id",
        "policy_revision",
        "phase",
        "recorded_at",
        "reported_status",
        "reported_tokens",
        "evidence_refs",
        "result_refs",
        "reflection_status",
    }:
        return None
    try:
        if entry.get("sha256") != _digest(body):
            return None
        recorded = datetime.fromisoformat(body["recorded_at"])
        if recorded.tzinfo is None:
            return None
    except (TypeError, ValueError):
        return None
    if (
        body["schema"] != SCHEMA
        or not isinstance(body["cycle_id"], str)
        or not 0 < len(body["cycle_id"]) <= 96
        or type(body["owner_user_id"]) is not int
        or body["owner_user_id"] <= 0
        or type(body["policy_revision"]) is not int
        or body["policy_revision"] <= 0
        or body["phase"] not in PHASES
        or not isinstance(body["reported_status"], str)
        or body["reported_status"] not in STATUSES | {"unknown"}
    ):
        return None
    tokens = body["reported_tokens"]
    if tokens is not None and (type(tokens) is not int or tokens < 0):
        return None
    for key in ("evidence_refs", "result_refs"):
        refs = body[key]
        if not isinstance(refs, list) or refs != _refs(refs):
            return None
    status = body["reflection_status"]
    if status is not None and (
        not isinstance(status, str)
        or not 0 < len(status) <= 64
        or not status.replace("_", "").isalnum()
    ):
        return None
    return body


def same_checkpoint(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Retrying persistence of one returned node is idempotent, not a repair."""
    old, new = _validated_body(left), _validated_body(right)
    if old is None or new is None:
        return False
    return {k: v for k, v in old.items() if k != "recorded_at"} == {
        k: v for k, v in new.items() if k != "recorded_at"
    }


def zero_usage_checkpoint_compatible(
    records: Any, *, cycle_id: str, owner_user_id: int, policy_revision: int
) -> bool:
    """An empty outbound journal is not proof of zero if its receipts disagree."""
    if not isinstance(records, dict):
        return False
    if not records:
        return True
    if set(records) not in ({"act"}, {"act", "reflect"}):
        return False
    for phase, entry in records.items():
        body = _validated_body(entry)
        if (
            body is None
            or body["phase"] != phase
            or body["cycle_id"] != cycle_id
            or body["owner_user_id"] != owner_user_id
            or body["policy_revision"] != policy_revision
            or body["reported_tokens"] != 0
        ):
            return False
    return True


def recover_checkpoint(
    records: Any, *, cycle_id: str, owner_user_id: int, policy_revision: int, actual_tokens: int
) -> dict[str, Any] | None:
    """Project an existing checkpoint after independent ledger usage readback."""
    if not records:
        return None
    invalid = {"status": "invalid_checkpoint", "replayed": False, "learning_applied": False}
    if not isinstance(records, dict):
        return invalid
    phase = "reflect" if "reflect" in records else "act"
    entry = records.get(phase)
    body = _validated_body(entry)
    if (
        body is None
        or body.get("cycle_id") != cycle_id
        or body.get("owner_user_id") != owner_user_id
        or body.get("policy_revision") != policy_revision
        or body.get("phase") != phase
    ):
        return invalid
    reported = body.get("reported_tokens")
    return {
        "status": "receipt_readback_only",
        "phase": phase,
        "checkpoint_sha256": _digest(body),
        "reported_status": body.get("reported_status"),
        "recorded_at": body.get("recorded_at"),
        "evidence_refs": _refs(body.get("evidence_refs") or []),
        "result_refs": _refs(body.get("result_refs") or []),
        "reflection_status": body.get("reflection_status"),
        "usage_matches_reported": None if reported is None else reported == actual_tokens,
        "replayed": False,
        "learning_applied": False,
        "business_outcome_verified": False,
    }
