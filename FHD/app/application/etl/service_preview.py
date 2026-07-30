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


class PreviewServiceMixin:
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
