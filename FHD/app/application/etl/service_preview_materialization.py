"""Background preview creation, mapping, validation, and row materialisation."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.compatibility_presets import validate_compatibility_preset
from app.application.etl.document_routing import (
    build_sheet_inventory,
    scoped_document_plan,
)
from app.application.etl.errors import EtlConflict, EtlError
from app.application.etl.mapping_assist import enhance_mappings_with_llm
from app.application.etl.parser_structure import header_match_score
from app.application.etl.parsers import (
    KNOWLEDGE_ONLY_SUFFIXES,
    OCR_SUFFIXES,
    ParsedDataset,
    parse_file,
)
from app.application.etl.product_identity import provenance_validation_issues
from app.application.etl.service_support import (
    DOCUMENT_ROUTE_LOCK,
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    EXECUTOR,
    SUBMITTED,
    SUBMITTED_LOCK,
    apply_validation_rules,
    dump_json,
    has_blocking_issues,
    load_json,
    new_id,
    new_session,
    safe_error,
)
from app.application.etl.targets import TargetAdapter, get_adapter
from app.application.etl.transforms import apply_mapping
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.infrastructure.tenant_scope import tenant_id_for_write, tenant_scope

logger = logging.getLogger(__name__)

from app.utils.mixin_module_sync import sync_mixin_methods


class PreviewMaterializationMixin:
    def _materialize_preview_rows(
        self, db: Session, run: EtlRun, upload: EtlUpload, dataset: ParsedDataset
    ) -> None:
        adapter = get_adapter(run.target_type)
        draft = load_json(run.draft_json, {})
        mappings = draft.get("field_mappings") or []
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        validation_rules = draft.get("validation_rules") or []
        counts = {"new": 0, "update": 0, "skip": 0, "error": 0}
        llm_degraded = False
        preview_cache: dict[str, Any] = {}
        advisory_jobs: list[tuple[EtlRunRow, dict[str, Any]]] = []
        from app.application.etl.llm_assist import etl_row_advice_limit

        advisory_limit = etl_row_advice_limit()
        row_count = len(dataset.rows)
        progress_interval = max(1, min(1000, (row_count + 19) // 20))
        for index, source in enumerate(dataset.rows, start=1):
            issues: list[dict[str, Any]] = []
            try:
                normalized = apply_mapping(source.values, mappings)
            except EtlError as exc:
                normalized = {}
                issues.append(
                    {
                        "code": exc.code,
                        "severity": "error",
                        "field": "",
                        "message": exc.message,
                    }
                )
            issues.extend(apply_validation_rules(normalized, validation_rules))
            issues.extend(provenance_validation_issues(source.provenance))
            if source.provenance.get("ocr") and not draft.get("ocr_confirmed"):
                issues.append(
                    {
                        "code": "ETL_OCR_CONFIRMATION_REQUIRED",
                        "severity": "error",
                        "field": "",
                        "message": "OCR 单元格尚未人工确认",
                    }
                )
            context = self._row_context(run, upload, source.row_number)
            context["_preview_cache"] = preview_cache
            decision = adapter.preview(
                db,
                normalized,
                allowed_update_fields=allowed_updates,
                context=context,
            )
            issues.extend(decision.issues or [])
            action = "error" if has_blocking_issues(issues) else decision.action
            counts[action] = counts.get(action, 0) + 1
            advisory_input = {
                "deterministic_action": decision.action,
                "deterministic_reason": decision.reason,
                "normalized": normalized,
                "before": decision.before or {},
                "after": decision.after or {},
            }
            advisory = self._adviser.fallback(**advisory_input)
            row_record = EtlRunRow(
                tenant_id=tenant_id_for_write(),
                owner_user_id=run.owner_user_id,
                run_id=run.id,
                source_sheet=source.sheet,
                source_row=source.row_number,
                source_json=dump_json(source.values),
                normalized_json=dump_json(normalized),
                provenance_json=dump_json(source.provenance),
                validation_json=dump_json(issues),
                llm_suggestion_json=dump_json(advisory),
                suggested_action=decision.action,
                final_action=action,
                match_ref=decision.match_ref or None,
                before_json=dump_json(decision.before or {}),
                after_json=dump_json(decision.after or {}),
            )
            db.add(row_record)
            if len(advisory_jobs) < advisory_limit:
                advisory_jobs.append((row_record, advisory_input))
            if index % progress_interval == 0 or index == row_count:
                run.progress = min(90, 70 + int(index / max(1, row_count) * 20))
                run.processed_rows = index
                db.commit()
        run.progress = max(int(run.progress or 0), 92)
        db.commit()
        if advisory_jobs:
            suggestions = self._adviser.suggest_many([payload for _row, payload in advisory_jobs])
            for (row_record, _payload), advisory in zip(advisory_jobs, suggestions, strict=False):
                row_record.llm_suggestion_json = dump_json(advisory)
                llm_degraded = llm_degraded or bool(advisory.get("degraded"))
        run.progress = 95
        run.new_rows = counts["new"]
        run.update_rows = counts["update"]
        run.skip_rows = counts["skip"]
        run.error_rows = counts["error"]
        summary = load_json(run.summary_json, {})
        summary.update(
            {
                "counts": counts,
                "llm_degraded": llm_degraded,
                "llm_advisory_only": True,
            }
        )
        run.summary_json = dump_json(summary)
        db.commit()

    def _suggest_mappings(
        self, dataset: ParsedDataset, adapter: TargetAdapter
    ) -> list[dict[str, Any]]:
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
        except Exception:  # noqa: BLE001
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
                alias
                for synonym_key in synonym_keys
                for alias in shared_synonyms.get(synonym_key, [])
            )
            candidates = (field.key, field.label, *field.aliases, *shared_candidates)
            field_candidates.append((field, candidates))

        # Assign the strongest source/target pairs first so a generic leaf such
        # as “名称” cannot steal “产品信息/名称” from the required product field.
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
        for field_index, (field, _candidates) in enumerate(field_candidates):
            matched, confidence = matched_by_field.get(field_index, ("", 0.0))
            default_transforms: list[dict[str, Any]] = []
            if matched:
                if field.type == "string":
                    default_transforms = [{"op": "trim"}]
                elif field.type == "number":
                    default_transforms = [{"op": "number"}]
                elif field.type == "integer":
                    default_transforms = [{"op": "cast", "type": "integer"}]
                elif field.type == "date":
                    default_transforms = [{"op": "date"}]
            mappings.append(
                {
                    "source": matched,
                    "target": field.key,
                    "transforms": default_transforms,
                    "confidence": round(confidence, 2),
                    "required": field.required,
                }
            )
        if (
            dataset.source_features.get("kind") == "document"
            and adapter.type == "knowledge"
            and mappings
        ):
            for mapping in mappings:
                if mapping["target"] == "document_path":
                    mapping["source"] = "document_path"
                    mapping["confidence"] = 1.0
        return mappings

    def _row_context(self, run: EtlRun, upload: EtlUpload, source_row: int) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "owner_user_id": run.owner_user_id,
            "file_sha256": upload.sha256,
            "file_name": upload.file_name,
            "relative_path": upload.relative_path or upload.file_name,
            "upload_path": upload.storage_path,
            "source_row": source_row,
        }


sync_mixin_methods(
    PreviewMaterializationMixin,
    target=globals(),
    source_module="app.application.etl.service_preview",
    method_names=(
        "_materialize_preview_rows",
        "_suggest_mappings",
        "_row_context",
    ),
)
