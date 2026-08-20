"""Pure mapping and linked-run helpers for ETL preview orchestration."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.parser_structure import header_match_score
from app.application.etl.parsers import ParsedDataset
from app.application.etl.service_support import dump_json, load_json
from app.application.etl.targets import TargetAdapter
from app.db.models.etl import EtlRun, EtlUpload
from app.utils.operational_errors import RECOVERABLE_ERRORS


def update_linked_companion_summary(db: Session, run: EtlRun, *, status: str) -> None:
    """Reflect a companion customer/product preview on its shipment parent."""
    details = load_json(run.summary_json, {})
    parent_id = str(details.get("linked_from_shipment_preview") or "").strip()
    if not parent_id:
        return
    parent = (
        db.query(EtlRun)
        .filter(
            EtlRun.id == parent_id,
            EtlRun.tenant_id == run.tenant_id,
            EtlRun.owner_user_id == run.owner_user_id,
            EtlRun.target_type == "shipment_records",
        )
        .first()
    )
    if parent is None:
        return
    parent_details = load_json(parent.summary_json, {})
    link = parent_details.get("linked_customer_products_preview")
    if not isinstance(link, dict) or str(link.get("run_id") or "") != str(run.id):
        return
    parent_details["linked_customer_products_preview"] = {
        **link,
        "status": status,
        "progress": int(run.progress or 0),
        "total_rows": int(run.total_rows or 0),
        "summary": {
            "new": int(run.new_rows or 0),
            "update": int(run.update_rows or 0),
            "skip": int(run.skip_rows or 0),
            "error": int(run.error_rows or 0),
        },
        "error": (
            {"code": run.error_code, "message": run.error_message}
            if status == "failed" and run.error_code
            else None
        ),
    }
    parent.summary_json = dump_json(parent_details)


def suggest_mappings(dataset: ParsedDataset, adapter: TargetAdapter) -> list[dict[str, Any]]:
    """Build deterministic one-to-one mappings ordered by match strength."""
    if adapter.allow_dynamic_fields:
        return [
            {
                "source": header,
                "target": header,
                "transforms": [{"op": "trim"}],
                "confidence": 1.0,
                "required": False,
            }
            for header in dataset.headers
        ]
    try:
        from app.application.excel_etl_kb import get_excel_etl_kb

        shared_synonyms = get_excel_etl_kb().synonyms()
    except RECOVERABLE_ERRORS:
        shared_synonyms = {}
    compatibility_keys = {
        "external_order_no": ("order_number",),
        "product_model": ("model_number",),
        "quantity": ("quantity_tins",),
    }
    field_candidates: list[tuple[Any, tuple[str, ...]]] = []
    for field in adapter.fields:
        synonym_keys = (field.key, *compatibility_keys.get(field.key, ()))
        shared_candidates = tuple(
            alias for key in synonym_keys for alias in shared_synonyms.get(key, [])
        )
        field_candidates.append(
            (field, (field.key, field.label, *field.aliases, *shared_candidates))
        )

    scored_pairs = sorted(
        (
            (
                header_match_score(header, candidates),
                0 if field.required else 1,
                field_index,
                header_index,
            )
            for field_index, (field, candidates) in enumerate(field_candidates)
            for header_index, header in enumerate(dataset.headers)
        ),
        key=lambda item: (-item[0], item[1], item[2], item[3]),
    )
    matched_by_field: dict[int, tuple[str, float]] = {}
    used_headers: set[int] = set()
    for score, _required_rank, field_index, header_index in scored_pairs:
        if score < 0.75:
            break
        if field_index in matched_by_field or header_index in used_headers:
            continue
        matched_by_field[field_index] = (dataset.headers[header_index], score)
        used_headers.add(header_index)

    mappings: list[dict[str, Any]] = []
    transforms_for_type = {
        "string": [{"op": "trim"}],
        "number": [{"op": "number"}],
        "integer": [{"op": "cast", "type": "integer"}],
        "date": [{"op": "date"}],
    }
    for field_index, (field, _candidates) in enumerate(field_candidates):
        matched, confidence = matched_by_field.get(field_index, ("", 0.0))
        mappings.append(
            {
                "source": matched,
                "target": field.key,
                "transforms": transforms_for_type.get(field.type, []) if matched else [],
                "confidence": round(confidence, 2),
                "required": field.required,
            }
        )
    if dataset.source_features.get("kind") == "document" and adapter.type == "knowledge":
        for mapping in mappings:
            if mapping["target"] == "document_path":
                mapping["source"] = "document_path"
                mapping["confidence"] = 1.0
    return mappings


def row_context(run: EtlRun, upload: EtlUpload, source_row: int) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "owner_user_id": run.owner_user_id,
        "file_sha256": upload.sha256,
        "file_name": upload.file_name,
        "relative_path": upload.relative_path or upload.file_name,
        "upload_path": upload.storage_path,
        "source_row": source_row,
    }
