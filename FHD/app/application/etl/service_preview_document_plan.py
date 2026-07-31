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


class PreviewDocumentPlanMixin:
    @staticmethod
    def _new_document_draft(target_type: str) -> dict[str, Any]:
        adapter = get_adapter(target_type)
        return {
            "field_mappings": [],
            "validation_rules": [],
            "match_keys": list(adapter.default_match_keys),
            "allowed_update_fields": [],
            "action_rules": {"duplicate": "skip"},
            "target_config_id": None,
            "ocr_confirmed": False,
            "document_confirmed": False,
        }

    def _prepare_document_preview_runs(
        self,
        db: Session,
        *,
        run: EtlRun,
        upload: EtlUpload,
        understanding: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        routes = [
            dict(route)
            for route in understanding.get("document_routes") or []
            if isinstance(route, dict)
        ]
        if not routes:
            return understanding, []
        primary_index = next(
            (
                index
                for index, route in enumerate(routes)
                if str(route.get("target_type") or "") == run.target_type
            ),
            0,
        )
        primary_route = routes[primary_index]
        queued_run_ids: list[str] = []
        route_records: list[dict[str, Any]] = []
        root_run_id = run.id
        for index, route in enumerate(routes):
            target_type = str(route.get("target_type") or "export_xlsx")
            adapter = get_adapter(target_type)
            plan = scoped_document_plan(understanding, route)
            if index == primary_index:
                route_run = run
                route_run.target_type = target_type
                route_run.reversible = adapter.reversible
                route_run.draft_json = dump_json(self._new_document_draft(target_type))
                route_run_id = route_run.id
                status = "previewing"
            else:
                route_run_id = new_id()
                child_summary = {
                    "file_name": upload.file_name,
                    "file_sha256": upload.sha256,
                    "batch_id": upload.batch_id,
                    "relative_path": upload.relative_path or upload.file_name,
                    "requested_target_type": "document_route",
                    "workbook_root_run_id": root_run_id,
                    "sheet_inventory": understanding.get("sheet_inventory") or [],
                    "document_route": {**route, "run_id": route_run_id},
                    "_document_plan": plan,
                }
                db.add(
                    EtlRun(
                        id=route_run_id,
                        tenant_id=run.tenant_id,
                        owner_user_id=run.owner_user_id,
                        upload_id=upload.id,
                        target_type=target_type,
                        status="queued",
                        stage="queued",
                        progress=0,
                        file_sha256=upload.sha256,
                        summary_json=dump_json(child_summary),
                        draft_json=dump_json(self._new_document_draft(target_type)),
                        reversible=adapter.reversible,
                    )
                )
                queued_run_ids.append(route_run_id)
                status = "queued"
            route_records.append(
                {
                    **route,
                    "run_id": route_run_id,
                    "is_primary": index == primary_index,
                    "status": status,
                    "progress": 5 if index == primary_index else 0,
                }
            )
        primary_plan = scoped_document_plan(understanding, primary_route)
        summary = load_json(run.summary_json, {})
        summary.update(
            {
                "workbook_root_run_id": root_run_id,
                "sheet_inventory": understanding.get("sheet_inventory") or [],
                "document_routes": route_records,
                "document_route": route_records[primary_index],
                "workbook_document_count": len(routes),
            }
        )
        run.summary_json = dump_json(summary)
        db.flush()
        return primary_plan, queued_run_ids

    @staticmethod
    def _update_linked_companion_summary(
        db: Session,
        run: EtlRun,
        *,
        status: str,
    ) -> None:
        """Reflect a companion preview state on its shipment parent.

        The linkage is UI/trace metadata only.  It never copies rows into the
        shipment target and never changes any customer or product record.
        """

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
        link = {
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
        parent_details["linked_customer_products_preview"] = link
        parent.summary_json = dump_json(parent_details)

    @staticmethod
    def _update_document_route_summary(
        db: Session,
        run: EtlRun,
        *,
        status: str,
    ) -> None:
        details = load_json(run.summary_json, {})
        route = details.get("document_route")
        root_run_id = str(details.get("workbook_root_run_id") or "").strip()
        if not isinstance(route, dict) or not root_run_id:
            return
        with DOCUMENT_ROUTE_LOCK:
            root = (
                db.query(EtlRun)
                .filter(
                    EtlRun.id == root_run_id,
                    EtlRun.tenant_id == run.tenant_id,
                    EtlRun.owner_user_id == run.owner_user_id,
                )
                .first()
            )
            if root is None:
                return
            root_details = load_json(root.summary_json, {})
            routes = list(root_details.get("document_routes") or [])
            for index, candidate in enumerate(routes):
                if str(candidate.get("run_id") or "") != run.id:
                    continue
                routes[index] = {
                    **candidate,
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
                break
            root_details["document_routes"] = routes
            if root.id == run.id:
                root_details["document_route"] = next(
                    (
                        candidate
                        for candidate in routes
                        if str(candidate.get("run_id") or "") == run.id
                    ),
                    root_details.get("document_route"),
                )
            root.summary_json = dump_json(root_details)

    @staticmethod
    def _record_preview_metrics(run: EtlRun, started_at: float, *, status: str) -> None:
        try:
            from app.utils.metrics import (
                etl_llm_degradations_total,
                etl_rows_total,
                etl_run_duration_seconds,
                etl_runs_total,
            )

            etl_runs_total.labels("preview", run.target_type, status).inc()
            etl_run_duration_seconds.labels("preview", run.target_type).observe(
                max(0.0, time.monotonic() - started_at)
            )
            if status == "success":
                for decision, count in (
                    ("new", run.new_rows),
                    ("update", run.update_rows),
                    ("skip", run.skip_rows),
                    ("error", run.error_rows),
                ):
                    if count:
                        etl_rows_total.labels(run.target_type, decision).inc(count)
                summary = load_json(run.summary_json, {})
                if summary.get("llm_degraded"):
                    etl_llm_degradations_total.labels(run.target_type).inc()
        except Exception:  # noqa: BLE001
            logger.debug("ETL preview metrics unavailable", exc_info=True)


sync_mixin_methods(
    PreviewDocumentPlanMixin,
    target=globals(),
    source_module="app.application.etl.service_preview",
    method_names=(
        "_new_document_draft",
        "_prepare_document_preview_runs",
        "_update_linked_companion_summary",
        "_update_document_route_summary",
        "_record_preview_metrics",
    ),
)
