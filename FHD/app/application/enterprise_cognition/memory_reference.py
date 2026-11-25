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

_ERP_REFERENCE_KIND = "erp_fact_reference_v1"
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SOURCE_VERSION = re.compile(r"^sha256:[0-9a-f]{64}$")
_FACT_TOKEN = re.compile(r"^erp:[0-9a-f]{64}$")



def build_erp_field_claim(snapshot: dict[str, Any], field: str) -> dict[str, Any] | None:
    """Construct a typed candidate from an authorized, fresh ERP row only."""
    if (
        not isinstance(field, str)
        or _FIELD.fullmatch(field) is None
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
    evidence = record.get("evidence")
    if not isinstance(evidence, list):
        return (None, True) if record.get("source") == "erp_authority" else (record, False)
    bindings = [
        row
        for row in evidence
        if isinstance(row, dict) and row.get("kind") == _ERP_REFERENCE_KIND
    ]
    if not bindings:
        return (None, True) if record.get("source") == "erp_authority" else (record, False)
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
