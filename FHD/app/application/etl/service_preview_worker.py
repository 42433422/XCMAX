"""Owned background preview jobs; public parsing hooks remain on the preview facade."""

from __future__ import annotations

import importlib
import logging
import time
from typing import TYPE_CHECKING, Any

from app.application.etl.operation_owner import (
    activate_operation,
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.etl.service_support import dump_json, load_json, safe_error
from app.db.models.etl import EtlRunRow
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _facade():
    return importlib.import_module("app.application.etl.service_preview")


class PreviewWorkerMixin:
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_upload: Any
        _suggest_mappings: Any
        _materialize_preview_rows: Any
        _update_linked_companion_summary: Any
        _record_preview_metrics: Any

    def _submit_preview(
        self, run_id: str, tenant_id: int, owner_user_id: int, *, operation_token: str | None = None
    ) -> None:
        with _facade().SUBMITTED_LOCK:
            if run_id in _facade().SUBMITTED and operation_token is None:
                return
            _facade().SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._preview_worker(run_id, owner_user_id, operation_token=operation_token)
            finally:
                with _facade().SUBMITTED_LOCK:
                    _facade().SUBMITTED.discard(run_id)

        _facade().EXECUTOR.submit(work)

    def _preview_worker(
        self, run_id: str, owner_user_id: int, *, operation_token: str | None = None
    ) -> None:
        from app.application.etl.llm_session_provider import (
            bind_etl_llm_owner,
            reset_etl_llm_owner,
        )

        llm_owner_token = bind_etl_llm_owner(owner_user_id)
        db = _facade().new_session()
        started_at = time.monotonic()
        operation = None
        try:
            run = self._owned_run(db, run_id, owner_user_id)
            operation = (
                activate_operation(db, run, "preview", operation_token)
                if operation_token
                else claim_operation(
                    db,
                    run,
                    "preview",
                    allowed_statuses={"queued", "previewing"},
                    require_unrolled_back=True,
                )
            )
            bind_owner(db, operation)
            upload = self._owned_upload(db, run.upload_id, owner_user_id)
            run.status = "previewing"
            run.stage = "parsing"
            run.progress = 5
            run.error_code = None
            run.error_message = None
            db.commit()

            draft = load_json(run.draft_json, {})
            compatibility_preset_id = str(draft.get("compatibility_preset_id") or "").strip()
            dataset = _facade().parse_file(
                upload.storage_path,
                target_type=run.target_type,
                compatibility_preset_id=compatibility_preset_id or None,
            )
            run = self._owned_run(db, run_id, owner_user_id)
            draft = load_json(run.draft_json, {})
            source_features = dict(dataset.source_features or {})
            summary = load_json(run.summary_json, {})
            if summary.get("target_detection"):
                source_features["target_detection"] = summary["target_detection"]
            if compatibility_preset_id:
                source_features["compatibility_preset_id"] = compatibility_preset_id
            if run.target_type == "shipment_records":
                # Surface an auditable, non-persistent layout candidate with
                # the preview.  The user must still explicitly save it before
                # it enters their private template library.
                from app.application.etl.service_shipment_templates import (
                    shipment_template_candidates,
                )

                candidates = shipment_template_candidates(source_features, upload.file_name)
                if candidates:
                    # Keep the legacy scalar for callers released before
                    # multi-layout selection, while exposing every auditable
                    # layout to the data-docking UI and chat resolver.
                    source_features["shipment_template_candidates"] = candidates
                    source_features["shipment_template_candidate"] = dict(candidates[0])
            if not draft.get("field_mappings"):
                deterministic_mappings = self._suggest_mappings(
                    dataset, _facade().get_adapter(run.target_type)
                )
                draft["field_mappings"], llm_mapping = _facade().enhance_mappings_with_llm(
                    dataset,
                    _facade().get_adapter(run.target_type),
                    deterministic_mappings,
                )
                source_features["llm_mapping"] = llm_mapping
                run.draft_json = dump_json(draft)
            run.total_rows = len(dataset.rows)
            run.source_features_json = dump_json(source_features)
            run.summary_json = dump_json(
                {
                    **summary,
                    "warnings": dataset.warnings,
                }
            )
            run.stage = "validating"
            run.progress = 20
            db.query(EtlRunRow).filter(
                EtlRunRow.run_id == run.id, EtlRunRow.owner_user_id == owner_user_id
            ).delete(synchronize_session=False)
            db.commit()

            self._materialize_preview_rows(db, run, upload, dataset)
            run = self._owned_run(db, run_id, owner_user_id)
            run.status = "preview_ready"
            run.stage = "preview_ready"
            run.progress = 100
            run.processed_rows = run.total_rows
            self._update_linked_companion_summary(db, run, status="preview_ready")
            finish_operation(db, operation)
            db.commit()
            self._record_preview_metrics(run, started_at, status="success")
        except BOUNDARY_ERRORS as exc:  # Background task boundary has no HTTP error handler.
            db.rollback()
            code, message = safe_error(exc)
            try:
                if operation is not None and fail_operation(
                    db, operation, code=code, message=message
                ):
                    run = self._owned_run(db, run_id, owner_user_id)
                    self._update_linked_companion_summary(db, run, status="failed")
                    db.commit()
                    self._record_preview_metrics(run, started_at, status="failed")
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL preview failure for run %s", run_id)
        finally:
            unbind_owner(db)
            db.close()
            reset_etl_llm_owner(llm_owner_token)
