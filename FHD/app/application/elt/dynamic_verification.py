"""Read the AI table adapter's original partitions and hashes without writing."""

from __future__ import annotations

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.elt.service_support import load_json
from app.application.elt.targets.dynamic import (
    PARTITION_MARKER,
    _fingerprint,
    _group_rows,
    _partition_headers,
    _row_hash,
    _usable_dedupe_keys,
)
from app.db.models.elt import EltDynamicRow, EltDynamicTable


def verify_dynamic_effects(db, native, rows, receipt) -> dict:
    draft = load_json(native.draft_json, {})
    headers = [
        str(item.get("target") or "")
        for item in draft.get("field_mappings") or []
        if isinstance(item, dict) and str(item.get("target") or "").strip()
    ]
    schema = draft.get("dynamic_schema") or {}
    # Use the original proposal, as the writer does. Removing a missing column
    # would verify a different business key and reject an intact source row.
    dedupe = [str(key) for key in schema.get("dedupe_keys") or []]
    payloads = []
    for row in rows:
        if row.final_action not in {"new", "update"}:
            continue
        provenance = load_json(row.provenance_json, {})
        payloads.append(
            {
                **load_json(row.normalized_json, {}),
                PARTITION_MARKER: {
                    "sheet": str(row.source_sheet or ""),
                    "table_id": str(provenance.get("table_id") or ""),
                    "table_title": str(provenance.get("table_title") or ""),
                    "table_range": str(provenance.get("table_range") or ""),
                    "row": int(row.source_row or 0),
                },
            }
        )
    groups = _group_rows(payloads)
    if not payloads:
        raise LookupError("no dynamic business rows to verify")
    declared = receipt.get("tables")
    if not isinstance(declared, list) or len(declared) != len(groups):
        raise ValueError("dynamic table receipt incomplete")
    observed, attempted, tables = set(), 0, []
    for group, report in zip(groups, declared, strict=True):
        part_rows = group["rows"]
        part_headers = _partition_headers(part_rows, headers)
        part_dedupe = _usable_dedupe_keys(dedupe, part_headers, part_rows)
        table = (
            db.query(EltDynamicTable)
            .filter_by(
                tenant_id=native.tenant_id,
                owner_user_id=native.owner_user_id,
                fingerprint=_fingerprint(part_headers, group["marker"]),
            )
            .first()
        )
        if (
            table is None
            or not isinstance(report, dict)
            or report.get("table_id") != table.id
            or load_json(table.headers_json, []) != part_headers
            or report.get("headers") != part_headers
        ):
            raise ValueError("dynamic table source changed")
        imported = set()
        for payload, identity in zip(part_rows, group["identities"], strict=True):
            material = payload if part_dedupe else {**payload, "__source__": "|".join(identity)}
            row = (
                db.query(EltDynamicRow)
                .filter_by(
                    tenant_id=native.tenant_id,
                    owner_user_id=native.owner_user_id,
                    table_id=table.id,
                    row_hash=_row_hash(material, part_dedupe),
                )
                .first()
            )
            if row is None or canonical_hash(load_json(row.payload_json, {})) != canonical_hash(
                payload
            ):
                raise ValueError("dynamic row is absent or differs from approved content")
            if row.run_id == native.id:
                imported.add(row.id)
        if report.get("inserted") != len(imported) or report.get("duplicates") != len(
            part_rows
        ) - len(imported):
            raise ValueError("dynamic insert or dedupe receipt differs from real rows")
        observed.update(imported)
        attempted += len(part_rows)
        tables.append({"table_id": table.id, "checked": len(part_rows), "inserted": len(imported)})
    owned = {
        identity
        for (identity,) in db.query(EltDynamicRow.id).filter_by(
            tenant_id=native.tenant_id, owner_user_id=native.owner_user_id, run_id=native.id
        )
    }
    if (
        owned != observed
        or native.executed_rows != len(observed)
        or receipt.get("inserted") != len(observed)
        or receipt.get("duplicates") != attempted - len(observed)
    ):
        raise ValueError("dynamic run has missing or unexpected business rows")
    return {
        "target_type": "dynamic_table",
        "rows_checked": attempted,
        "inserted": len(observed),
        "tables_sha256": canonical_hash(tables),
    }
