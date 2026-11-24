"""Epistemic labels for the existing scoped ERP projection, not a knowledge store."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_HISTORY_KEY = "_observation_history"
_TRUNCATED_KEY = "_observation_history_truncated"
_MAX_OBSERVATIONS = 32


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in snapshot.items() if not key.startswith("_")}
    result["knowledge_kind"] = (
        "fact" if result.get("freshness") == "fresh" and result.get("evidence") else "unknown"
    )
    return result


def observation_time(snapshot: dict[str, Any]) -> datetime:
    value = datetime.fromisoformat(snapshot["observed_at"])
    if value.tzinfo is None:
        raise ValueError("observation_time_requires_timezone")
    try:
        return value.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("observation_time_utc_out_of_range") from exc


def read_observations(
    raw: str, expected_scope: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    """Legacy current projections are observations, never reconstructed history."""
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("invalid_observation_projection")
    history = decoded.get(_HISTORY_KEY)
    if history is None:
        history = [public_snapshot(decoded)] if decoded.get("freshness") == "fresh" else []
    if not isinstance(history, list):
        raise ValueError("invalid_observation_history")
    for item in history:
        if not isinstance(item, dict) or not item.get("evidence") or not item.get("source_version"):
            raise ValueError("invalid_observation_evidence")
        if any(item.get(key) != value for key, value in expected_scope.items()):
            raise ValueError("observation_scope_mismatch")
        authority = {
            "state": item["state"],
            "source_last_changed": item["source_last_changed"],
        }
        canonical = json.dumps(
            authority, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        if item["source_version"] != "sha256:" + digest:
            raise ValueError("observation_digest_mismatch")
        observation_time(item)
    return history, decoded.get(_TRUNCATED_KEY) is True


def record_observation(raw: str | None, snapshot: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Retain conflicting observations; do not convert ambiguous ordering to a fact."""
    scope = {
        key: snapshot[key]
        for key in (
            "tenant_id",
            "actor_id",
            "mod_id",
            "entity_type",
            "entity_id",
            "source",
            "read_only",
        )
    }
    history, truncated = read_observations(raw, scope) if raw else ([], False)
    entry = public_snapshot(snapshot)
    instant = observation_time(entry)
    conflict = any(
        observation_time(item) >= instant and item["source_version"] != entry["source_version"]
        for item in history
    )
    if not any(
        observation_time(item) == instant and item["source_version"] == entry["source_version"]
        for item in history
    ):
        history.append(entry)
    history.sort(key=observation_time)
    if len(history) > _MAX_OBSERVATIONS:
        truncated = True
        history = history[-_MAX_OBSERVATIONS:]
    return {
        **entry,
        _HISTORY_KEY: history,
        _TRUNCATED_KEY: truncated,
    }, conflict


def historical_observation(raw: str, as_of: str, expected_scope: dict[str, Any]) -> dict[str, Any]:
    """Return last recorded observation, never claim continuous business validity."""
    at = datetime.fromisoformat(as_of)
    if at.tzinfo is None:
        raise ValueError("as_of_requires_timezone")
    try:
        at_utc = at.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("as_of_utc_out_of_range") from exc
    history, truncated = read_observations(raw, expected_scope)
    candidates = [item for item in history if observation_time(item) <= at_utc]
    base = {
        "as_of": at_utc.isoformat(),
        "history_truncated": truncated,
        "business_validity_verified": False,
        "current_state_verified": False,
        "temporal_semantics": "last_recorded_observation_not_effective_business_state",
    }
    if not candidates:
        return {**base, "knowledge_kind": "unknown", "reason_code": "no_observation_at_cutoff"}
    latest = observation_time(candidates[-1])
    same_time = [item for item in candidates if observation_time(item) == latest]
    if len({item["source_version"] for item in same_time}) != 1:
        return {
            **base,
            "knowledge_kind": "unknown",
            "reason_code": "conflicting_observations",
            "conflict_evidence": same_time,
        }
    observed = public_snapshot(same_time[-1])
    return {
        **base,
        "knowledge_kind": "fact",
        "observation": {**observed, "freshness": "historical"},
    }


def relationship_references(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose only explicit foreign keys in the observed, already authorized state."""
    if snapshot.get("knowledge_kind") != "fact":
        return []
    state = snapshot.get("state") or {}
    refs = []
    if snapshot.get("entity_type") == "order":
        for field, kind, relation in (
            ("customer_id", "customer", "customer"),
            ("backorder_of_id", "order", "backorder_of"),
            ("return_of_id", "order", "return_of"),
        ):
            if state.get(field) is not None:
                refs.append(
                    {"relation": relation, "entity_type": kind, "entity_id": str(state[field])}
                )
    elif snapshot.get("entity_type") in {"inventory", "production"}:
        for field, kind in (
            ("product_id", "product"),
            ("warehouse_id", "warehouse"),
            ("sales_order_id", "order"),
            ("bom_id", "bom"),
        ):
            if state.get(field) is not None:
                refs.append(
                    {"relation": field, "entity_type": kind, "entity_id": str(state[field])}
                )
    return [
        {
            **ref,
            "knowledge_kind": "fact",
            "target_visibility_verified": False,
            "evidence": snapshot["evidence"],
        }
        for ref in refs
    ]


def delivery_scenario(snapshot: dict[str, Any], quantity: str) -> dict[str, Any]:
    """Conditional arithmetic, not a statistical forecast or a causal estimate."""
    unknown = {"knowledge_kind": "unknown", "reason_code": "scenario_baseline_unavailable"}
    if (
        snapshot.get("freshness") != "fresh"
        or snapshot.get("entity_type") != "order"
        or snapshot.get("knowledge_kind") != "fact"
    ):
        return unknown
    state = snapshot.get("state") or {}
    try:
        remaining = Decimal(str(state["remaining_quantity"]))
        assumed = Decimal(quantity)
        if not remaining.is_finite() or not assumed.is_finite() or not 0 <= assumed <= remaining:
            return {**unknown, "reason_code": "scenario_quantity_out_of_range"}
    except (KeyError, InvalidOperation, ValueError):
        return unknown
    if not state.get("quantity_unit"):
        return unknown
    return {
        "knowledge_kind": "prediction",
        "method": "conditional_arithmetic",
        "metric": "remaining_quantity",
        "value": str(remaining - assumed),
        "unit": state["quantity_unit"],
        "assumptions": [
            {"knowledge_kind": "hypothesis", "additional_delivery_quantity": str(assumed)},
            {"knowledge_kind": "hypothesis", "condition": "no_other_quantity_changes"},
        ],
        "baseline_source_version": snapshot["source_version"],
        "baseline_observed_at": snapshot["observed_at"],
        "evidence": snapshot["evidence"],
        "probability": None,
        "causal_effect_verified": False,
        "business_data_written": False,
    }
