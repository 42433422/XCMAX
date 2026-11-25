"""Validate ERP-bound MemoryV2 claims at recall; never create another authority."""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.enterprise_cognition.service import (
    make_fact_reference,
    verify_source_reference,
)
from app.domain.user_memory.policy import is_erp_bound_memory

_ERP_REFERENCE_KIND = "erp_fact_reference_v1"
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SOURCE_VERSION = re.compile(r"^sha256:[0-9a-f]{64}$")
_FACT_TOKEN = re.compile(r"^erp:[0-9a-f]{64}$")
# A field's presence alone does not grant it memory eligibility. Exclude free
# text notes, raw line arrays, credentials and mixed-unit aggregates.
_ALLOWED_ERP_FIELDS: dict[str, frozenset[str]] = {
    "order": frozenset(
        {
            "order_no", "customer_id", "state", "status", "invoice_status",
            "payment_state", "total_amount", "paid_amount", "currency",
            "ordered_quantity", "delivered_quantity", "returned_quantity",
            "remaining_quantity", "quantity_unit",
        }
    ),
    "inventory": frozenset(
        {
            "product_id", "warehouse_id", "transaction_type", "quantity",
            "before_quantity", "after_quantity", "transaction_date",
            "sales_order_id",
        }
    ),
    "fund": frozenset(
        {
            "transaction_type", "amount", "currency", "reference_type",
            "reference_id", "journal_entry_id", "status", "due_date",
            "transaction_date",
        }
    ),
    "journal_entry": frozenset(
        {
            "entry_no", "journal_date", "status", "reference_type",
            "reference_id", "debit_total", "credit_total", "reversed_of_id",
            "reversed_at", "credit_note_of_id", "is_credit_note",
        }
    ),
    "customer": frozenset(
        {"customer_name", "credit_limit", "credit_used", "is_credit_limited"}
    ),
}


def build_erp_field_claim(snapshot: dict[str, Any], field: str) -> dict[str, Any] | None:
    """Construct a typed candidate from an authorized, fresh ERP row only."""
    if (
        not isinstance(field, str)
        or _FIELD.fullmatch(field) is None
        or field not in _ALLOWED_ERP_FIELDS.get(snapshot.get("entity_type"), frozenset())
        or snapshot.get("freshness") != "fresh"
        or snapshot.get("retrieved_from") != "authority"
    ):
        return None
    reference = make_fact_reference(snapshot)
    state = snapshot.get("state")
    if reference is None or not isinstance(state, dict) or field not in state:
        return None
    value = state[field]
    if value is not None and type(value) not in (str, int, float, bool):
        return None
    try:
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(rendered) > 256:
        return None
    return {
        "value": {
            "statement": f"ERP {reference['entity_type']}#{reference['entity_id']}.{field} = {rendered}",
            "erp_field": field,
            "erp_value": value,
        },
        "evidence": {
            "kind": _ERP_REFERENCE_KIND,
            **reference,
            "field": field,
        },
    }


def revalidate_erp_memory(
    record: dict[str, Any],
    access: DatasetAccessContext,
    *,
    projections=None,
) -> tuple[dict[str, Any] | None, bool]:
    """Return a safe current memory claim and whether an ERP check was required.

    MemoryV2 is never the business authority. Unbound conversation memories keep
    their existing semantics, while ERP-bound claims must recheck source RBAC,
    original row identity, version and the exact field value on every recall.
    """
    if not is_erp_bound_memory(record):
        return record, False
    evidence = record.get("evidence")
    if not isinstance(evidence, list):
        return None, True
    bindings = [
        row
        for row in evidence
        if isinstance(row, dict) and row.get("kind") == _ERP_REFERENCE_KIND
    ]
    if not bindings:
        return None, True
    if len(bindings) != 1:
        return None, True
    binding = bindings[0]
    field = binding.get("field")
    version = binding.get("source_version")
    token = binding.get("fact_token")
    entity_type = binding.get("entity_type")
    entity_id = binding.get("entity_id")
    if (
        not isinstance(field, str)
        or _FIELD.fullmatch(field) is None
        or not isinstance(version, str)
        or _SOURCE_VERSION.fullmatch(version) is None
        or not isinstance(token, str)
        or _FACT_TOKEN.fullmatch(token) is None
        or not isinstance(entity_type, str)
        or not isinstance(entity_id, str)
        or not entity_id
        or len(entity_id) > 160
        or str(binding.get("tenant_id") or "") != access.tenant_id
        or str(binding.get("mod_id") or "") != access.mod_id
    ):
        return None, True
    try:
        if projections is None:
            from app.application.enterprise_cognition.projection import get_projection_service

            projections = get_projection_service()
        snapshot = projections.get(
            entity_type,
            entity_id,
            tenant_id=access.tenant_id,
            actor_id=access.actor_id,
            mod_id=access.mod_id,
            force_refresh=True,
            verify_only=True,
        )
        verification = verify_source_reference(snapshot, version, token)
    except (PermissionError, ValueError, TypeError):
        # A revoked source permission is not permission to replay stored text.
        return None, True
    if verification["status"] != "current":
        return None, True
    if str(snapshot.get("source") or "") != str(binding.get("source") or ""):
        return None, True
    claim = build_erp_field_claim(snapshot, field)
    if claim is None or claim["evidence"] != binding:
        return None, True
    stored_value = record.get("value")
    if not isinstance(stored_value, dict) or (
        stored_value.get("erp_field") != field
        or stored_value.get("erp_value") != claim["value"]["erp_value"]
    ):
        return None, True
    # Free-text in MemoryV2 is not automatically promoted to ERP truth: the
    # sentence always comes from the re-read typed source field.
    checked = {
        **record,
        "value": claim["value"],
        "statement": claim["value"]["statement"],
        "erp_fact_verification": {
            "status": "current",
            "source": snapshot["source"],
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field": field,
            "source_version": version,
            "fact_token": token,
            "checked_at": snapshot["observed_at"],
            "read_only": True,
        },
    }
    return checked, True


def sanitize_erp_memory_view(
    record: dict[str, Any], access: DatasetAccessContext
) -> dict[str, Any]:
    """Never disclose a superseded or unauthorized ERP claim in a list/graph.

    Retain only the non-sensitive memory identity and revision to allow the
    existing owner to delete/review it. Raw value, historical revisions and
    provenance are withheld until the original ERP read is authorized again.
    """
    checked, is_erp_bound = revalidate_erp_memory(record, access)
    if not is_erp_bound:
        return record
    if checked is not None:
        return checked
    sanitized = dict(record)
    sanitized.update(
        key="erp_fact_reference_redacted",
        value=None,
        statement="ERP 事实来源已变化或不可访问，需要重新核验",
        evidence=[],
        history=[],
        eligible_for_planner=False,
        strength=0.0,
        erp_fact_verification={"status": "unknown", "memory_reuse_allowed": False},
        erp_requires_reconciliation=True,
    )
    sanitized.pop("relation_path", None)
    return sanitized
