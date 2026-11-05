"""Background preview creation, mapping, validation, and row materialisation."""

from __future__ import annotations

import logging
import time
from contextvars import copy_context
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.elt.compatibility_presets import validate_compatibility_preset
from app.application.elt.errors import EltError
from app.application.elt.mapping_assist import (
    enhance_mappings_with_llm as enhance_mappings_with_llm,
)
from app.application.elt.operation_owner import (
    activate_operation,
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.elt.parsers import (
    KNOWLEDGE_ONLY_SUFFIXES,
    ParsedDataset,
)
from app.application.elt.parsers import (
    parse_file as parse_file,
)
from app.application.elt.preview_confirmation import publish_preview
from app.application.elt.service_preview_helpers import (
    row_context,
    suggest_mappings,
    update_linked_companion_summary,
)
from app.application.elt.service_support import dump_json, load_json, safe_error
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class PreviewWorkerMixin:
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_upload: Any
        _suggest_mappings: Any
        _persist_source_snapshot: Any
        _load_source_snapshot: Any
        _owned_upload_record: Any
        _revalidate_existing_rows: Any
        _update_linked_companion_summary: Any
        _record_preview_metrics: Any

    def _submit_preview(
        self, run_id: str, tenant_id: int, owner_user_id: int, *, operation_token: str | None = None
    ) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED and operation_token is None:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._preview_worker(run_id, owner_user_id, operation_token=operation_token)
            finally:
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        try:
            EXECUTOR.submit(copy_context().run, work)
        except RECOVERABLE_ERRORS:
            with SUBMITTED_LOCK:
                SUBMITTED.discard(run_id)
            raise

    def _preview_worker(
        self, run_id: str, owner_user_id: int, *, operation_token: str | None = None
    ) -> None:
        from app.application.elt.llm_session_provider import (
            bind_etl_llm_owner,
            reset_etl_llm_owner,
        )

        llm_owner_token = bind_etl_llm_owner(owner_user_id)
        db = new_session()
        started_at = time.monotonic()
        operation = None
        dataset = None
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
            upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
            run.status = "previewing"
            run.stage = "parsing"
            run.progress = 5
            run.error_code = None
            run.error_message = None
            db.commit()

            draft = load_json(run.draft_json, {})
            compatibility_preset_id = str(draft.get("compatibility_preset_id") or "").strip()
            dataset = self._load_source_snapshot(db, run)
            if dataset is None:
                upload = self._owned_upload(db, run.upload_id, owner_user_id)
                dataset = parse_file(
                    upload.storage_path,
                    target_type=run.target_type,
                    compatibility_preset_id=compatibility_preset_id or None,
                )
                run.stage = "loading"
                self._persist_source_snapshot(db, run, dataset)
                dataset.close()
                dataset = self._load_source_snapshot(db, run)
                assert dataset is not None
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
                from app.application.elt.service_shipment_templates import (
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
                    dataset, get_adapter(run.target_type)
                )
                draft["field_mappings"], llm_mapping = enhance_mappings_with_llm(
                    dataset,
                    get_adapter(run.target_type),
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
            run.stage = "transforming"
            run.progress = 20
            db.commit()
            self._revalidate_existing_rows(db, run.id, owner_user_id, publish=False)
            run = self._owned_run(db, run_id, owner_user_id)
            run.status = "preview_ready"
            run.stage = "preview_ready"
            run.progress = 100
            run.processed_rows = run.total_rows
            self._update_linked_companion_summary(db, run, status="preview_ready")
            publish_preview(db, run)
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
            try:
                if dataset is not None:
                    dataset.close()
            finally:
                unbind_owner(db)
                db.close()
                reset_etl_llm_owner(llm_owner_token)


from app.application.elt.service_source import SourceServiceMixin
from app.application.elt.service_support import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    new_id,
)
from app.application.elt.service_support import (
    EXECUTOR as EXECUTOR,
)
from app.application.elt.service_support import (
    SUBMITTED as SUBMITTED,
)
from app.application.elt.service_support import (
    SUBMITTED_LOCK as SUBMITTED_LOCK,
)
from app.application.elt.service_support import (
    new_session as new_session,
)
from app.application.elt.targets import TargetAdapter, get_adapter
from app.db.models.elt import EltRun, EltUpload
from app.infrastructure.tenant_scope import tenant_id_for_write


class PreviewServiceMixin(SourceServiceMixin, PreviewWorkerMixin):
    if TYPE_CHECKING:
        _adviser: Any
        _current_version: Any
        _owned_run: Any
        _owned_template: Any
        _owned_upload: Any
        get_run: Any

    def create_preview(
        self,
        db: Session,
        *,
        owner_user_id: int,
        upload_id: str,
        target_type: str,
        template_id: str | None = None,
        compatibility_preset_id: str | None = None,
        target_config_id: str | None = None,
    ) -> dict[str, Any]:
        upload = self._owned_upload(db, upload_id, owner_user_id)
        target_detection: dict[str, Any] | None = None
        if str(target_type or "").strip().lower() == "auto":
            from app.application.elt.target_detection import detect_etl_target

            target_detection = detect_etl_target(
                upload.storage_path,
                suffix=upload.suffix,
                owner_user_id=upload.owner_user_id,
            )
            target_type = str(target_detection["target_type"])
        adapter = get_adapter(target_type)
        if upload.suffix in KNOWLEDGE_ONLY_SUFFIXES and adapter.type != "knowledge":
            raise EltError(
                "ELT_KNOWLEDGE_ONLY_FILE",
                "Word/PPT 仅可进入知识库",
            )
        template = None
        version = None
        draft: dict[str, Any] = {
            "field_mappings": [],
            "validation_rules": [],
            "match_keys": list(adapter.default_match_keys),
            "allowed_update_fields": [],
            "action_rules": {"duplicate": "skip"},
            "target_config_id": target_config_id,
            "ocr_confirmed": False,
        }
        requested_preset_id = str(compatibility_preset_id or "").strip()
        if template_id:
            template = self._owned_template(db, template_id, owner_user_id)
            if template.description == ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION:
                raise EltError(
                    "ELT_SHIPMENT_TEMPLATE_NOT_IMPORT_TEMPLATE",
                    "发货单版式仅用于开单打印，不能作为导入字段模板",
                    status_code=409,
                )
            if template.target_type != target_type:
                raise EltError("ELT_TEMPLATE_TARGET_MISMATCH", "模板目标与本次目标不一致")
            version = self._current_version(db, template, owner_user_id)
            template_source_features = load_json(version.source_features_json, {})
            template_preset_id = str(
                template_source_features.get("compatibility_preset_id") or ""
            ).strip()
            if (
                requested_preset_id
                and template_preset_id
                and requested_preset_id != template_preset_id
            ):
                raise EltError(
                    "ELT_TEMPLATE_PRESET_CONFLICT",
                    "个人模板已绑定兼容预设，不能同时指定另一个预设",
                )
            requested_preset_id = requested_preset_id or template_preset_id
            draft.update(
                {
                    "field_mappings": load_json(version.field_mappings_json, []),
                    "validation_rules": load_json(version.validation_rules_json, []),
                    "match_keys": load_json(version.match_keys_json, []),
                    "allowed_update_fields": load_json(version.allowed_update_fields_json, []),
                    "action_rules": load_json(version.action_rules_json, {}),
                }
            )
        if requested_preset_id:
            validate_compatibility_preset(
                requested_preset_id,
                target_type=target_type,
                upload_suffix=upload.suffix,
            )
            draft["compatibility_preset_id"] = requested_preset_id
        run = EltRun(
            id=new_id(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            upload_id=upload.id,
            template_id=template.id if template else None,
            template_version_id=version.id if version else None,
            target_type=target_type,
            status="queued",
            stage="queued",
            progress=0,
            file_sha256=upload.sha256,
            summary_json=dump_json(
                {
                    "file_name": upload.file_name,
                    "file_sha256": upload.sha256,
                    "batch_id": upload.batch_id,
                    "relative_path": upload.relative_path or upload.file_name,
                    "requested_target_type": "auto" if target_detection else target_type,
                    "target_detection": target_detection or {},
                }
            ),
            draft_json=dump_json(draft),
            reversible=adapter.reversible,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        tenant_id = tenant_id_for_write()
        companion_run: EltRun | None = None
        # A multi-sheet delivery workbook normally contains both a printable
        # delivery-note layout and customer/product facts in supporting tabs.
        # Auto detection therefore creates a second, *preview-only* snapshot
        # of those facts.  It is not an execution, does not touch master data,
        # and keeps the primary shipment run as the task the user sees first.
        # This lets the later authenticated chat confirmation resolve exactly
        # the same uploaded evidence without making the user discover a hidden
        # second "预演客户及产品" step.
        is_auto_shipment_preview = bool(
            target_detection and adapter.type == "shipment_records" and not template_id
        )
        if is_auto_shipment_preview and upload.suffix.lower() in {".xlsx", ".xlsm"}:
            companion_adapter = get_adapter("customer_products")
            companion_draft: dict[str, Any] = {
                "field_mappings": [],
                "validation_rules": [],
                "match_keys": list(companion_adapter.default_match_keys),
                "allowed_update_fields": [],
                "action_rules": {"duplicate": "skip"},
                "target_config_id": None,
                "ocr_confirmed": False,
                "linked_preview": {
                    "kind": "shipment_companion_customer_products",
                    "parent_run_id": run_id,
                    "read_only": True,
                },
            }
            companion_run = EltRun(
                id=new_id(),
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                upload_id=upload.id,
                target_type="customer_products",
                status="queued",
                stage="queued",
                progress=0,
                file_sha256=upload.sha256,
                summary_json=dump_json(
                    {
                        "file_name": upload.file_name,
                        "file_sha256": upload.sha256,
                        "batch_id": upload.batch_id,
                        "relative_path": upload.relative_path or upload.file_name,
                        "linked_from_shipment_preview": run_id,
                        "preview_only": True,
                    }
                ),
                draft_json=dump_json(companion_draft),
                reversible=companion_adapter.reversible,
            )
            db.add(companion_run)
            primary_summary = load_json(run.summary_json, {})
            primary_summary["linked_customer_products_preview"] = {
                "run_id": companion_run.id,
                "target_type": "customer_products",
                "status": "queued",
                "preview_only": True,
                "message": "正在从同一文件的附表生成客户及产品预演；不会写入客户库或产品库。",
            }
            run.summary_json = dump_json(primary_summary)
        db.commit()
        self._submit_preview(run_id, tenant_id, owner_user_id)
        if companion_run is not None:
            self._submit_preview(companion_run.id, tenant_id, owner_user_id)
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run_id, owner_user_id=owner_user_id))

    @staticmethod
    def _update_linked_companion_summary(
        db: Session,
        run: EltRun,
        *,
        status: str,
    ) -> None:
        update_linked_companion_summary(db, run, status=status)

    @staticmethod
    def _record_preview_metrics(run: EltRun, started_at: float, *, status: str) -> None:
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
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL preview metrics unavailable", exc_info=True)

    def _suggest_mappings(
        self, dataset: ParsedDataset, adapter: TargetAdapter
    ) -> list[dict[str, Any]]:
        return suggest_mappings(dataset, adapter)

    def _row_context(self, run: EltRun, upload: EltUpload, source_row: int) -> dict[str, Any]:
        return row_context(run, upload, source_row)
