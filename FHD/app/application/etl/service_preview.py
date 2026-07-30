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


from app.application.etl.service_preview_document_plan import PreviewDocumentPlanMixin
from app.application.etl.service_preview_materialization import PreviewMaterializationMixin


class PreviewServiceMixin(PreviewDocumentPlanMixin, PreviewMaterializationMixin):
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
            "document_confirmed": False,
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
        db.commit()
        self._submit_preview(run_id, tenant_id, owner_user_id)
        db.expire_all()
        return self.get_run(db, run_id=run_id, owner_user_id=owner_user_id)

    def reanalyze_with_llm(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
    ) -> dict[str, Any]:
        """Rebuild a degraded preview from its original upload."""

        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"preview_ready", "failed", "interrupted"}:
            raise EtlConflict("ETL_LLM_REANALYZE_NOT_ALLOWED", "当前任务正在处理，不能重复调用")
        if int(run.executed_rows or 0) > 0:
            raise EtlConflict(
                "ETL_LLM_REANALYZE_AFTER_EXECUTION",
                "任务已经写入业务数据，不能重新解释原始单据",
            )
        source_features = load_json(run.source_features_json, {})
        understanding = source_features.get("document_understanding")
        llm = understanding.get("llm") if isinstance(understanding, dict) else None
        if not isinstance(llm, dict) or not llm.get("degraded"):
            raise EtlConflict("ETL_LLM_REANALYZE_NOT_NEEDED", "当前单据理解没有降级")

        draft = load_json(run.draft_json, {})
        draft["document_confirmed"] = False
        if not run.template_id and not draft.get("compatibility_preset_id"):
            draft["field_mappings"] = []
        run.draft_json = dump_json(draft)
        run.status = "previewing"
        run.stage = "parsing"
        run.progress = 5
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()

        from app.application.etl.llm_assist import clear_etl_llm_circuit

        clear_etl_llm_circuit(owner_user_id=owner_user_id)
        self._submit_preview(run.id, tenant_id, owner_user_id)
        db.expire_all()
        return self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)

    def _submit_preview(self, run_id: str, tenant_id: int, owner_user_id: int) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._preview_worker(run_id, owner_user_id)
            finally:
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        EXECUTOR.submit(work)

    def _preview_worker(self, run_id: str, owner_user_id: int) -> None:
        from app.application.etl.llm_session_provider import (
            bind_etl_llm_owner,
            reset_etl_llm_owner,
        )

        llm_owner_token = bind_etl_llm_owner(owner_user_id)
        db = new_session()
        started_at = time.monotonic()
        try:
            run = self._owned_run(db, run_id, owner_user_id)
            upload = self._owned_upload(db, run.upload_id, owner_user_id)
            run.status = "previewing"
            run.stage = "parsing"
            run.progress = 5
            run.error_code = None
            run.error_message = None
            db.commit()
            self._update_document_route_summary(db, run, status="previewing")
            db.commit()

            draft = load_json(run.draft_json, {})
            compatibility_preset_id = str(draft.get("compatibility_preset_id") or "").strip()
            summary = load_json(run.summary_json, {})
            queued_document_run_ids: list[str] = []
            parse_source_path = upload.storage_path
            ocr_result: dict[str, Any] | None = None
            if upload.suffix.lower() in OCR_SUFFIXES and run.target_type != "knowledge":
                from app.application.shipment_excel_etl_ocr import ocr_source_to_workbook

                ocr_result = ocr_source_to_workbook(Path(upload.storage_path))
                if not ocr_result.get("success"):
                    raise EtlError(
                        str(ocr_result.get("error_code") or "ETL_OCR_FAILED").upper(),
                        "OCR 无法可靠还原表格，请更换清晰文件后重试",
                    )
                parse_source_path = str(ocr_result["file_path"])
            document_understanding: dict[str, Any] | None = None
            if (
                Path(parse_source_path).suffix.lower() in {".xlsx", ".xlsm"}
                and not compatibility_preset_id
                and run.target_type != "knowledge"
            ):
                stored_plan = summary.get("_document_plan")
                if isinstance(stored_plan, dict) and stored_plan.get("routing_scope"):
                    document_understanding = stored_plan
                else:
                    from app.application.etl.document_understanding import understand_workbook
                    from app.application.etl.workbook_evidence import (
                        build_workbook_evidence,
                        public_evidence_summary,
                    )

                    def report_document_progress(completed: int, total: int) -> None:
                        if total <= 0:
                            return
                        progress = min(50, 5 + round(45 * completed / total))
                        if progress <= int(run.progress or 0):
                            return
                        run.progress = progress
                        db.commit()

                    workbook_evidence = build_workbook_evidence(parse_source_path)
                    preliminary_inventory = build_sheet_inventory(workbook_evidence)
                    summary.update(
                        {
                            "workbook_stage": "sheet_inventory_ready",
                            "workbook_sheet_count": len(preliminary_inventory),
                            "sheet_inventory": preliminary_inventory,
                            "workbook_evidence": public_evidence_summary(workbook_evidence),
                        }
                    )
                    run.summary_json = dump_json(summary)
                    run.stage = "classifying_sheets"
                    run.progress = max(int(run.progress or 0), 15)
                    db.commit()

                    document_understanding = understand_workbook(
                        parse_source_path,
                        hinted_target_type=run.target_type,
                        hint_confidence=float(
                            (summary.get("target_detection") or {}).get("confidence") or 1.0
                        ),
                        progress_callback=report_document_progress,
                        evidence=workbook_evidence,
                    )
                    summary = load_json(run.summary_json, {})
                    summary.update(
                        {
                            "workbook_stage": "document_routes_ready",
                            "workbook_sheet_count": len(
                                document_understanding.get("sheet_inventory") or []
                            ),
                            "sheet_inventory": (
                                document_understanding.get("sheet_inventory") or []
                            ),
                        }
                    )
                    run.summary_json = dump_json(summary)
                    db.commit()
                    if (
                        summary.get("requested_target_type") == "auto"
                        and not run.template_id
                        and document_understanding.get("document_routes")
                    ):
                        (
                            document_understanding,
                            queued_document_run_ids,
                        ) = self._prepare_document_preview_runs(
                            db,
                            run=run,
                            upload=upload,
                            understanding=document_understanding,
                        )
                        draft = load_json(run.draft_json, {})
                        summary = load_json(run.summary_json, {})
                run.progress = max(int(run.progress or 0), 52)
                db.commit()
                recommended_target = str(
                    document_understanding.get("recommended_target_type") or run.target_type
                )
                if (
                    summary.get("requested_target_type") == "auto"
                    and not run.template_id
                    and recommended_target != run.target_type
                ):
                    recommended_adapter = get_adapter(recommended_target)
                    run.target_type = recommended_target
                    run.reversible = recommended_adapter.reversible
                    draft.update(
                        {
                            "field_mappings": [],
                            "validation_rules": [],
                            "match_keys": list(recommended_adapter.default_match_keys),
                            "allowed_update_fields": [],
                            "action_rules": {"duplicate": "skip"},
                            "target_config_id": None,
                            "document_confirmed": False,
                        }
                    )
                    summary["semantic_target_override"] = {
                        "target_type": recommended_target,
                        "source": document_understanding.get("source"),
                        "plan_hash": document_understanding.get("plan_hash"),
                    }
                    run.draft_json = dump_json(draft)
                    run.summary_json = dump_json(summary)
                    db.commit()
            dataset = parse_file(
                parse_source_path,
                target_type=run.target_type,
                compatibility_preset_id=compatibility_preset_id or None,
                document_plan=document_understanding,
            )
            run.progress = max(int(run.progress or 0), 60)
            db.commit()
            if ocr_result is not None:
                from app.application.etl.parser_ocr_provenance import enrich_ocr_provenance

                dataset = enrich_ocr_provenance(
                    dataset,
                    ocr_result,
                    source_suffix=upload.suffix.lower(),
                )
            run = self._owned_run(db, run_id, owner_user_id)
            draft = load_json(run.draft_json, {})
            source_features = dict(dataset.source_features or {})
            summary = load_json(run.summary_json, {})
            if document_understanding:
                source_features["document_understanding"] = document_understanding
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
            run.stage = "validating"
            run.progress = 70
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
            self._update_document_route_summary(db, run, status="preview_ready")
            db.commit()
            self._record_preview_metrics(run, started_at, status="success")
            for document_run_id in queued_document_run_ids:
                self._submit_preview(document_run_id, run.tenant_id, owner_user_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            code, message = safe_error(exc)
            try:
                run = self._owned_run(db, run_id, owner_user_id)
                run.status = "failed"
                run.stage = "failed"
                run.error_code = code
                run.error_message = message[:500]
                self._update_document_route_summary(db, run, status="failed")
                db.commit()
                self._record_preview_metrics(run, started_at, status="failed")
                summary = load_json(run.summary_json, {})
                for route in summary.get("document_routes") or []:
                    child_run_id = str(route.get("run_id") or "")
                    if child_run_id and child_run_id != run.id:
                        self._submit_preview(child_run_id, run.tenant_id, owner_user_id)
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL preview failure for run %s", run_id)
        finally:
            db.close()
            reset_etl_llm_owner(llm_owner_token)
