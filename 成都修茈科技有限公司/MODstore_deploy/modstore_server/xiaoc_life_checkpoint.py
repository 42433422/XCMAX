"""Bounded, receipt-only checkpoints of the existing LangGraph effect boundary.

A checkpoint is evidence that a node returned, not business authority. No
checkpoint may invoke a model, dispatch work, or bypass original receipt checks.
"""

from __future__ import annotations

import hashlib
import json
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
    return list(dict.fromkeys(
        value for value in values if isinstance(value, str) and 0 < len(value) <= 256
    ))[:32]


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
            ("id", "goal"), ("decision_id", "portfolio"), ("retort_request_id", "retort")
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
            reported_status if isinstance(reported_status, str) and reported_status in STATUSES
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


def same_checkpoint(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Retrying persistence of one returned node is idempotent."""
    return {
        key: value for key, value in left.items() if key not in {"recorded_at", "sha256"}
    } == {
        key: value for key, value in right.items() if key not in {"recorded_at", "sha256"}
    }


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
    if not isinstance(entry, dict):
        return invalid
    body = {key: value for key, value in entry.items() if key != "sha256"}
    try:
        valid = entry.get("sha256") == _digest(body)
    except (TypeError, ValueError):
        return invalid
    if (
        not valid
        or body.get("schema") != SCHEMA
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
        "checkpoint_sha256": entry["sha256"],
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
