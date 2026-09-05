"""Background preview creation, mapping, validation, and row materialisation."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.etl.compatibility_presets import validate_compatibility_preset
from app.application.etl.errors import EtlError
from app.application.etl.mapping_assist import (
    enhance_mappings_with_llm as enhance_mappings_with_llm,
)
from app.application.etl.parsers import (
    KNOWLEDGE_ONLY_SUFFIXES,
    ParsedDataset,
)
from app.application.etl.parsers import (
    parse_file as parse_file,
)
from app.application.etl.product_identity import provenance_validation_issues
from app.application.etl.service_preview_helpers import (
    row_context,
    suggest_mappings,
    update_linked_companion_summary,
)
from app.application.etl.service_preview_worker import PreviewWorkerMixin
from app.application.etl.service_support import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    apply_validation_rules,
    dump_json,
    load_json,
    new_id,
)
from app.application.etl.service_support import (
    EXECUTOR as EXECUTOR,
)
from app.application.etl.service_support import (
    SUBMITTED as SUBMITTED,
)
from app.application.etl.service_support import (
    SUBMITTED_LOCK as SUBMITTED_LOCK,
)
from app.application.etl.service_support import (
    new_session as new_session,
)
from app.application.etl.targets import TargetAdapter, get_adapter
from app.application.etl.transforms import apply_mapping
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class PreviewServiceMixin(PreviewWorkerMixin):
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
            from app.application.etl.target_detection import detect_etl_target

            target_detection = detect_etl_target(
                upload.storage_path,
                suffix=upload.suffix,
            )
            target_type = str(target_detection["target_type"])
        adapter = get_adapter(target_type)
        if upload.suffix in KNOWLEDGE_ONLY_SUFFIXES and adapter.type != "knowledge":
            raise EtlError(
                "ETL_KNOWLEDGE_ONLY_FILE",
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
                raise EtlError(
                    "ETL_SHIPMENT_TEMPLATE_NOT_IMPORT_TEMPLATE",
                    "发货单版式仅用于开单打印，不能作为导入字段模板",
                    status_code=409,
                )
            if template.target_type != target_type:
                raise EtlError("ETL_TEMPLATE_TARGET_MISMATCH", "模板目标与本次目标不一致")
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
                raise EtlError(
                    "ETL_TEMPLATE_PRESET_CONFLICT",
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
        run = EtlRun(
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
        companion_run: EtlRun | None = None
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
            companion_run = EtlRun(
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
        run: EtlRun,
        *,
        status: str,
    ) -> None:
        update_linked_companion_summary(db, run, status=status)

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
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL preview metrics unavailable", exc_info=True)

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
            action = "error" if issues else decision.action
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
            if index % 500 == 0:
                run.progress = min(95, 20 + int(index / max(1, len(dataset.rows)) * 75))
                run.processed_rows = index
                db.commit()
        if advisory_jobs:
            suggestions = self._adviser.suggest_many([payload for _row, payload in advisory_jobs])
            for (row_record, _payload), advisory in zip(advisory_jobs, suggestions, strict=False):
                row_record.llm_suggestion_json = dump_json(advisory)
                llm_degraded = llm_degraded or bool(advisory.get("degraded"))
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
        return suggest_mappings(dataset, adapter)

    def _row_context(self, run: EtlRun, upload: EtlUpload, source_row: int) -> dict[str, Any]:
        return row_context(run, upload, source_row)
