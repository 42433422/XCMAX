"""Editable preview drafts and deterministic row action overrides."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.parsers import MAX_ROWS
from app.application.etl.product_identity import provenance_validation_issues
from app.application.etl.service_support import (
    ALLOWED_VALIDATION_OPS,
    EXECUTOR,
    SUBMITTED,
    SUBMITTED_LOCK,
    apply_validation_rules,
    dump_json,
    has_blocking_issues,
    load_json,
    new_session,
    safe_error,
)
from app.application.etl.targets import TargetAdapter, get_adapter
from app.application.etl.transforms import ALLOWED_TRANSFORMS, apply_mapping
from app.db.models.etl import EtlRun, EtlRunRow
from app.infrastructure.tenant_scope import tenant_id_for_write, tenant_scope

logger = logging.getLogger(__name__)


class DraftServiceMixin:
    def update_draft(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"preview_ready", "failed", "interrupted"}:
            raise EtlConflict("ETL_RUN_NOT_EDITABLE", "当前状态不能修改预演草稿")
        draft_keys = {
            "field_mappings",
            "validation_rules",
            "match_keys",
            "allowed_update_fields",
            "action_rules",
            "target_config_id",
            "ocr_confirmed",
            "document_confirmed",
        }
        changes_draft = any(key in patch for key in draft_keys)
        overrides = patch.get("row_overrides") or {}
        if not changes_draft:
            if isinstance(overrides, dict) and overrides:
                self._apply_row_overrides(db, run.id, owner_user_id, overrides)
                self._record_correction_metrics(mapping_changed=False, overrides=overrides)
            return self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)

        draft = load_json(run.draft_json, {})
        for key in draft_keys:
            if key in patch:
                draft[key] = patch[key]
        self._validate_draft(draft, get_adapter(run.target_type))
        run.draft_json = dump_json(draft)
        run.status = "previewing"
        run.stage = "validating"
        run.progress = 20
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        self._submit_revalidation(
            run.id,
            tenant_id,
            owner_user_id,
            overrides if isinstance(overrides, dict) else {},
        )
        self._record_correction_metrics(
            mapping_changed=patch.get("field_mappings") is not None,
            overrides=overrides if isinstance(overrides, dict) else {},
        )
        db.expire_all()
        return self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)

    @staticmethod
    def _record_correction_metrics(*, mapping_changed: bool, overrides: dict[str, Any]) -> None:
        try:
            from app.utils.metrics import etl_manual_corrections_total

            if mapping_changed:
                etl_manual_corrections_total.labels("mapping").inc()
            if overrides:
                etl_manual_corrections_total.labels("row_action").inc(len(overrides))
        except Exception:  # noqa: BLE001
            logger.debug("ETL correction metrics unavailable", exc_info=True)

    def _submit_revalidation(
        self,
        run_id: str,
        tenant_id: int,
        owner_user_id: int,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            db = new_session()
            try:
                with tenant_scope(tenant_id):
                    self._revalidate_existing_rows(db, run_id, owner_user_id)
                    if overrides:
                        self._apply_row_overrides(db, run_id, owner_user_id, overrides)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                code, message = safe_error(exc)
                try:
                    with tenant_scope(tenant_id):
                        run = self._owned_run(db, run_id, owner_user_id)
                        run.status = "failed"
                        run.stage = "failed"
                        run.error_code = code
                        run.error_message = message[:500]
                        db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    logger.exception("Unable to persist ETL revalidation failure for %s", run_id)
            finally:
                db.close()
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        EXECUTOR.submit(work)

    def _validate_draft(self, draft: dict[str, Any], adapter: TargetAdapter) -> None:
        mappings = draft.get("field_mappings")
        if not isinstance(mappings, list):
            raise EtlError("ETL_MAPPINGS_INVALID", "field_mappings 必须是数组")
        if len(mappings) > 500:
            raise EtlError("ETL_MAPPINGS_INVALID", "字段映射不能超过 500 项")
        targets = {field.key for field in adapter.fields}
        seen_targets: set[str] = set()
        for item in mappings:
            target = str(item.get("target") or "").strip() if isinstance(item, dict) else ""
            if (
                not isinstance(item, dict)
                or not target
                or len(target) > 160
                or (not adapter.allow_dynamic_fields and target not in targets)
            ):
                raise EtlError("ETL_MAPPING_TARGET_INVALID", "字段映射包含未知目标字段")
            if target in seen_targets:
                raise EtlError("ETL_MAPPING_TARGET_DUPLICATE", "同一目标字段只能映射一次")
            seen_targets.add(target)
            transforms = item.get("transforms") or []
            if not isinstance(transforms, list):
                raise EtlError("ETL_TRANSFORMS_INVALID", "transforms 必须是数组")
            if len(transforms) > 20:
                raise EtlError("ETL_TRANSFORMS_INVALID", "单字段转换规则不能超过 20 项")
            for rule in transforms:
                if not isinstance(rule, dict):
                    raise EtlError("ETL_TRANSFORM_INVALID", "转换规则必须是 JSON 对象")
                if str(rule.get("op") or "").strip().lower() not in ALLOWED_TRANSFORMS:
                    raise EtlError("ETL_TRANSFORM_FORBIDDEN", "转换规则包含不允许的操作")
        allowed = set(draft.get("allowed_update_fields") or [])
        updatable = {field.key for field in adapter.fields if field.updatable}
        if not allowed.issubset(updatable):
            raise EtlError("ETL_UPDATE_FIELDS_FORBIDDEN", "包含目标不允许更新的字段")
        match_keys = draft.get("match_keys") or []
        if not isinstance(match_keys, list) or not set(match_keys).issubset(
            set(adapter.default_match_keys)
        ):
            raise EtlError("ETL_MATCH_KEYS_UNSUPPORTED", "包含目标不支持的匹配键")
        action_rules = draft.get("action_rules") or {}
        if not isinstance(action_rules, dict):
            raise EtlError("ETL_ACTION_RULES_INVALID", "action_rules 必须是 JSON 对象")
        for confirmation_key in ("ocr_confirmed", "document_confirmed"):
            if confirmation_key in draft and not isinstance(draft.get(confirmation_key), bool):
                raise EtlError(
                    "ETL_CONFIRMATION_VALUE_INVALID",
                    f"{confirmation_key} 必须是布尔值",
                )
        validation_rules = draft.get("validation_rules") or []
        if not isinstance(validation_rules, list):
            raise EtlError("ETL_VALIDATION_RULES_INVALID", "validation_rules 必须是数组")
        if len(validation_rules) > 100:
            raise EtlError("ETL_VALIDATION_RULES_INVALID", "校验规则不能超过 100 项")
        target_fields = {field.key for field in adapter.fields}
        for rule in validation_rules:
            if not isinstance(rule, dict):
                raise EtlError("ETL_VALIDATION_RULE_INVALID", "校验规则必须是 JSON 对象")
            field = str(rule.get("field") or "")
            op = str(rule.get("op") or "").lower()
            if field not in target_fields or op not in ALLOWED_VALIDATION_OPS:
                raise EtlError("ETL_VALIDATION_RULE_INVALID", "校验规则包含未知字段或操作")
            if op == "enum":
                values = rule.get("value")
                if not isinstance(values, list) or len(values) > 1000:
                    raise EtlError("ETL_VALIDATION_RULE_INVALID", "枚举校验值必须是有限数组")

    def _revalidate_existing_rows(self, db: Session, run_id: str, owner_user_id: int) -> None:
        run = self._owned_run(db, run_id, owner_user_id)
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        adapter = get_adapter(run.target_type)
        draft = load_json(run.draft_json, {})
        mappings = draft.get("field_mappings") or []
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        validation_rules = draft.get("validation_rules") or []
        counts = {"new": 0, "update": 0, "skip": 0, "error": 0}
        llm_degraded = False
        preview_cache: dict[str, Any] = {}
        last_id = 0
        processed = 0
        page_size = 500
        for _page_number in range((MAX_ROWS + page_size - 1) // page_size + 1):
            rows = (
                db.query(EtlRunRow)
                .filter(
                    EtlRunRow.run_id == run_id,
                    EtlRunRow.owner_user_id == owner_user_id,
                    EtlRunRow.id > last_id,
                )
                .order_by(EtlRunRow.id)
                .limit(page_size)
                .all()
            )
            if not rows:
                break
            for row in rows:
                last_id = row.id
                processed += 1
                if row.execution_status == "success":
                    counts[row.final_action] = counts.get(row.final_action, 0) + 1
                    continue
                issues: list[dict[str, Any]] = []
                try:
                    normalized = apply_mapping(load_json(row.source_json, {}), mappings)
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
                provenance = load_json(row.provenance_json, {})
                issues.extend(provenance_validation_issues(provenance))
                if provenance.get("ocr") and not draft.get("ocr_confirmed"):
                    issues.append(
                        {
                            "code": "ETL_OCR_CONFIRMATION_REQUIRED",
                            "severity": "error",
                            "field": "",
                            "message": "OCR 单元格尚未人工确认",
                        }
                    )
                context = self._row_context(run, upload, row.source_row)
                context["_preview_cache"] = preview_cache
                decision = adapter.preview(
                    db,
                    normalized,
                    allowed_update_fields=allowed_updates,
                    context=context,
                )
                issues.extend(decision.issues or [])
                action = "error" if has_blocking_issues(issues) else decision.action
                row.normalized_json = dump_json(normalized)
                row.validation_json = dump_json(issues)
                row.suggested_action = decision.action
                row.final_action = action
                row.action_overridden = False
                row.match_ref = decision.match_ref or None
                row.before_json = dump_json(decision.before or {})
                row.after_json = dump_json(decision.after or {})
                advisory = self._adviser.suggest(
                    deterministic_action=decision.action,
                    deterministic_reason=decision.reason,
                    normalized=normalized,
                    before=decision.before or {},
                    after=decision.after or {},
                )
                llm_degraded = llm_degraded or bool(advisory.get("degraded"))
                row.llm_suggestion_json = dump_json(advisory)
                counts[action] += 1
            run.progress = min(95, 20 + int(processed / max(1, run.total_rows) * 75))
            run.processed_rows = processed
            db.commit()
        self._set_run_counts(run, counts)
        summary = load_json(run.summary_json, {})
        summary["llm_degraded"] = llm_degraded
        summary["llm_advisory_only"] = True
        run.summary_json = dump_json(summary)
        run.status = "preview_ready"
        run.stage = "preview_ready"
        run.progress = 100
        run.error_code = None
        run.error_message = None
        db.commit()

    def _apply_row_overrides(
        self, db: Session, run_id: str, owner_user_id: int, overrides: dict[str, Any]
    ) -> None:
        run = self._owned_run(db, run_id, owner_user_id)
        adapter = get_adapter(run.target_type)
        allowed_actions = set(adapter.actions) | {"skip"}
        draft = load_json(run.draft_json, {})
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        for raw_id, action in overrides.items():
            if str(action) not in allowed_actions:
                raise EtlError("ETL_ROW_ACTION_INVALID", f"不允许的逐行动作: {action}")
            row = (
                db.query(EtlRunRow)
                .filter(
                    EtlRunRow.id == int(raw_id),
                    EtlRunRow.run_id == run_id,
                    EtlRunRow.owner_user_id == owner_user_id,
                )
                .first()
            )
            if row is None:
                raise EtlNotFound("预演行")
            if row.execution_status == "success":
                raise EtlConflict("ETL_ROW_ALREADY_EXECUTED", "已执行成功的行不能再次修改动作")
            if load_json(row.validation_json, []):
                raise EtlConflict(
                    "ETL_INVALID_ROW_CANNOT_OVERRIDE", "存在校验错误的行只能保持错误状态"
                )
            if action == "update" and not row.match_ref:
                raise EtlConflict(
                    "ETL_ROW_UPDATE_REQUIRES_MATCH",
                    "更新动作必须先匹配到现有数据",
                )
            if action == "update" and not allowed_updates:
                raise EtlConflict(
                    "ETL_ROW_UPDATE_FIELDS_REQUIRED",
                    "更新动作必须先确认允许更新的字段",
                )
            if action == "new" and (row.match_ref or row.suggested_action == "skip"):
                raise EtlConflict(
                    "ETL_DUPLICATE_CANNOT_FORCE_NEW",
                    "已匹配的重复数据不能强制新增，请修改匹配字段后重新预演",
                )
            row.final_action = str(action)
            row.action_overridden = True
        counts = {
            action: db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run_id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.final_action == action,
            )
            .count()
            for action in ("new", "update", "skip", "error")
        }
        self._set_run_counts(run, counts)
        db.commit()

    def _set_run_counts(self, run: EtlRun, counts: dict[str, int]) -> None:
        run.new_rows = counts.get("new", 0)
        run.update_rows = counts.get("update", 0)
        run.skip_rows = counts.get("skip", 0)
        run.error_rows = counts.get("error", 0)
        summary = load_json(run.summary_json, {})
        summary["counts"] = counts
        run.summary_json = dump_json(summary)
