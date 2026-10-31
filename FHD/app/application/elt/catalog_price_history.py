"""Immutable reviewed corrections; effective prices never erase original observations."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from uuid import UUID

from app.application.elt.batch_price_sources import (
    latest_period_price,
    reject_conflicting_period_prices,
)
from app.application.elt.errors import EltConflict

MANUAL_KIND = "catalog_price_v1"
_FIELDS = {
    "kind",
    "operation_id",
    "run_id",
    "reason",
    "supersedes",
    "currency",
    "price_unit",
    "actor_id",
    "receipt_key",
}


def _invalid():
    return EltConflict(
        "CATALOG_PRICE_CORRECTION_INVALID",
        "原价格纠错链、审批回执或选中来源不可核验，未覆盖原记录",
    )


def manual_provenance(row):
    """Legacy ETL evidence is a list; a manual envelope must be exact and versioned."""
    try:
        value = json.loads(row.provenance_json)
        if isinstance(value, list):
            if any(isinstance(item, dict) and item.get("kind") == MANUAL_KIND for item in value):
                raise _invalid()
            return None
        if not isinstance(value, dict) or set(value) != _FIELDS or value["kind"] != MANUAL_KIND:
            raise _invalid()
        operation = value["operation_id"]
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise _invalid()
        if (
            not isinstance(value["run_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["run_id"])
            or not isinstance(value["reason"], str)
            or not value["reason"].strip()
            or len(value["reason"]) > 1000
            or not isinstance(value["actor_id"], str)
            or not re.fullmatch(r"[1-9][0-9]*", value["actor_id"])
            or str(row.owner_user_id) != value["actor_id"]
            or not isinstance(value["currency"], str)
            or not re.fullmatch(r"[A-Z]{3}", value["currency"])
            or not isinstance(value["price_unit"], str)
            or not value["price_unit"].strip()
            or value["price_unit"] != value["price_unit"].strip()
            or len(value["price_unit"]) > 80
            or not isinstance(value["receipt_key"], str)
            or not re.fullmatch(r"catalog-price-receipt-v1:[0-9a-f]{64}", value["receipt_key"])
            or not isinstance(value["supersedes"], list)
            or len(value["supersedes"]) > 5000
            or any(
                not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                for key in value["supersedes"]
            )
            or len(set(value["supersedes"])) != len(value["supersedes"])
        ):
            raise _invalid()
        return value
    except (ValueError, TypeError, AttributeError, KeyError):
        raise _invalid() from None


def validate_correction(effective_rows, selected_keys, start, end):
    """Select only current leaves in the exact original period, including unmarked dates."""
    if (
        not isinstance(selected_keys, list)
        or not selected_keys
        or len(selected_keys) > 5000
        or any(not isinstance(key, str) for key in selected_keys)
        or len(set(selected_keys)) != len(selected_keys)
        or (start is None) != (end is None)
        or (start is not None and end <= start)
    ):
        raise _invalid()
    by_key = {row.source_key: row for row in effective_rows}
    if len(by_key) != len(effective_rows) or any(key not in by_key for key in selected_keys):
        raise _invalid()
    selected = [by_key[key] for key in selected_keys]
    if any((row.period_start, row.period_end) != (start, end) for row in selected):
        raise _invalid()
    return selected


def effective_history(history, *, verify_manual):
    """Verify all envelopes/receipts, then remove only explicitly superseded active leaves.

    The callback must check the original immutable same-catalog receipt, full inserted
    event image and source binding. A caller cannot authorize a correction with JSON
    metadata alone. Raw rows remain the input to database revisions and rollback CAS.
    """
    active, envelopes, seen = {}, {}, set()
    previous_id = 0
    scope = None
    for row in history:
        if (
            type(row.id) is not int
            or row.id <= previous_id
            or not isinstance(row.source_key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", row.source_key)
            or row.source_key in seen
            or (row.period_start is None) != (row.period_end is None)
            or (row.period_start is not None and row.period_end <= row.period_start)
        ):
            raise _invalid()
        row_scope = (row.tenant_id, row.product_id)
        if scope is not None and row_scope != scope:
            raise _invalid()
        scope, previous_id = row_scope, row.id
        seen.add(row.source_key)
        envelope = manual_provenance(row)
        if envelope is not None:
            if verify_manual is None or verify_manual(row, envelope) is not True:
                raise _invalid()
            selected = envelope["supersedes"]
            if selected:
                originals = validate_correction(
                    list(active.values()), selected, row.period_start, row.period_end
                )
                for original in originals:
                    prior = envelopes.get(original.source_key)
                    if prior and (prior["currency"], prior["price_unit"]) != (
                        envelope["currency"],
                        envelope["price_unit"],
                    ):
                        raise _invalid()
                    del active[original.source_key]
            envelopes[row.source_key] = envelope
        active[row.source_key] = row
    return list(active.values())


def history_events(rows):
    return [
        {
            "period_start": row.period_start,
            "period_end": row.period_end,
            "price": str(row.price),
            "source_key": row.source_key,
            "period_label": row.period_label,
        }
        for row in rows
    ]


def effective_price(events):
    """Unmarked corrections remain unmarked; neither timestamps nor ordering invent a date."""
    if not events:
        raise _invalid()
    reject_conflicting_period_prices(events)
    if any(event["period_start"] is not None for event in events):
        return latest_period_price(events)
    if len({Decimal(str(event["price"])) for event in events}) != 1:
        raise EltConflict(
            "ELT_PRICE_PERIOD_CONFLICT", "未标业务时间的有效价格仍有冲突，请明确核对来源"
        )
    return min(events, key=lambda event: event["source_key"])
