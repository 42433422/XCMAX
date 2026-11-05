"""Editable preview drafts and deterministic row action overrides."""

from __future__ import annotations

import logging
from contextvars import copy_context
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.elt.errors import EltConflict, EltError, EltNotFound
from app.application.elt.operation_owner import (
    activate_operation,
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.elt.parsers import MAX_ROWS
from app.application.elt.preview_confirmation import invalidate_preview, publish_preview
from app.application.elt.product_identity import provenance_validation_issues
from app.application.elt.service_support import (
    ALLOWED_VALIDATION_OPS,
    EXECUTOR,
    SUBMITTED,
    SUBMITTED_LOCK,
    apply_validation_rules,
    dump_json,
    load_json,
    new_session,
    safe_error,
)
from app.application.elt.targets import TargetAdapter, get_adapter
from app.application.elt.transforms import ALLOWED_TRANSFORMS, apply_mapping
from app.db.models.elt import EltRun, EltRunRow
from app.infrastructure.tenant_scope import tenant_id_for_write, tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class DraftServiceMixin:
    if TYPE_CHECKING:
        _adviser: Any
        _owned_run: Any
        _owned_upload_record: Any
        _row_context: Any
        _load_source_snapshot: Any
        get_run: Any

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
            raise EltConflict("ELT_RUN_NOT_EDITABLE", "当前状态不能修改预演草稿")
        draft_keys = {
            "field_mappings",
            "validation_rules",
            "match_keys",
            "allowed_update_fields",
            "action_rules",
            "target_config_id",
            "ocr_confirmed",
        }
        changes_draft = any(key in patch for key in draft_keys)
        overrides = patch.get("row_overrides") or {}
        if not changes_draft:
            if isinstance(overrides, dict) and overrides:
                operation = claim_operation(
                    db,
                    run,
                    "edit",
                    allowed_statuses={"preview_ready", "failed", "interrupted"},
                    require_unrolled_back=True,
                )
                bind_owner(db, operation)
                try:
                    db.refresh(run)
                    invalidate_preview(run)
                    self._apply_row_overrides(db, run.id, owner_user_id, overrides)
                    publish_preview(db, run)
                    finish_operation(db, operation)
                    db.commit()
                except RECOVERABLE_ERRORS as exc:
                    code, message = safe_error(exc)
                    fail_operation(db, operation, code=code, message=message)
                    raise
                finally:
                    unbind_owner(db)
                self._record_correction_metrics(mapping_changed=False, overrides=overrides)
            return cast(
                "dict[str, Any]", self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)
            )

        operation = claim_operation(
            db,
            run,
            "preview_queue",
            allowed_statuses={"preview_ready", "failed", "interrupted"},
            require_unrolled_back=True,
        )
        bind_owner(db, operation)
        committed = False
        try:
            db.refresh(run)
            # Build from the latest draft only after obtaining the existing run lock.
            draft = load_json(run.draft_json, {})
            draft.update({key: patch[key] for key in draft_keys if key in patch})
            self._validate_draft(draft, get_adapter(run.target_type))
            invalidate_preview(run)
            run.draft_json = dump_json(draft)
            run.status = "previewing"
            run.stage = "validating"
            run.progress = 20
            run.error_code = None
            run.error_message = None
            tenant_id = tenant_id_for_write()
            db.commit()
            committed = True
        finally:
            try:
                if not committed:
                    db.rollback()
            finally:
                unbind_owner(db)
        self._submit_revalidation(
            run.id,
            tenant_id,
            owner_user_id,
            overrides if isinstance(overrides, dict) else {},
            operation_token=operation.token,
        )
        self._record_correction_metrics(
            mapping_changed=patch.get("field_mappings") is not None,
            overrides=overrides if isinstance(overrides, dict) else {},
        )
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run.id, owner_user_id=owner_user_id))

    @staticmethod
    def _record_correction_metrics(*, mapping_changed: bool, overrides: dict[str, Any]) -> None:
        try:
            from app.utils.metrics import etl_manual_corrections_total

            if mapping_changed:
                etl_manual_corrections_total.labels("mapping").inc()
            if overrides:
                etl_manual_corrections_total.labels("row_action").inc(len(overrides))
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL correction metrics unavailable", exc_info=True)

    def _submit_revalidation(
        self,
        run_id: str,
        tenant_id: int,
        owner_user_id: int,
        overrides: dict[str, Any] | None = None,
        *,
        operation_token: str | None = None,
    ) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED and operation_token is None:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            from app.application.elt.llm_session_provider import (
                bind_etl_llm_owner,
                reset_etl_llm_owner,
            )

            llm_owner_token = bind_etl_llm_owner(owner_user_id)
            db = new_session()
            operation = None
            try:
                with tenant_scope(tenant_id):
                    run = self._owned_run(db, run_id, owner_user_id)
                    operation = (
                        activate_operation(db, run, "preview", operation_token)
                        if operation_token
                        else claim_operation(
                            db,
                            run,
                            "preview",
                            allowed_statuses={"previewing", "preview_ready"},
                            require_unrolled_back=True,
                        )
                    )
                    bind_owner(db, operation)
                    db.commit()
                    self._revalidate_existing_rows(db, run_id, owner_user_id, publish=False)
                    if overrides:
                        self._apply_row_overrides(db, run_id, owner_user_id, overrides)
                    run.status = run.stage = "preview_ready"
                    run.progress = 100
                    publish_preview(db, self._owned_run(db, run_id, owner_user_id))
                    finish_operation(db, operation)
                    db.commit()
            except BOUNDARY_ERRORS as exc:  # Background revalidation task boundary.
                db.rollback()
                code, message = safe_error(exc)
                try:
                    with tenant_scope(tenant_id):
                        if operation is not None:
                            fail_operation(db, operation, code=code, message=message)
                except RECOVERABLE_ERRORS:  # noqa: BLE001
                    db.rollback()
                    logger.exception("Unable to persist ETL revalidation failure for %s", run_id)
            finally:
                unbind_owner(db)
                db.close()
                reset_etl_llm_owner(llm_owner_token)
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        EXECUTOR.submit(copy_context().run, work)

    def _validate_draft(self, draft: dict[str, Any], adapter: TargetAdapter) -> None:
        mappings = draft.get("field_mappings")
        if not isinstance(mappings, list):
            raise EltError("ELT_MAPPINGS_INVALID", "field_mappings 必须是数组")
        if len(mappings) > 500:
            raise EltError("ELT_MAPPINGS_INVALID", "字段映射不能超过 500 项")
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
                raise EltError("ELT_MAPPING_TARGET_INVALID", "字段映射包含未知目标字段")
            if target in seen_targets:
                raise EltError("ELT_MAPPING_TARGET_DUPLICATE", "同一目标字段只能映射一次")
            seen_targets.add(target)
            transforms = item.get("transforms") or []
            if not isinstance(transforms, list):
                raise EltError("ELT_TRANSFORMS_INVALID", "transforms 必须是数组")
            if len(transforms) > 20:
                raise EltError("ELT_TRANSFORMS_INVALID", "单字段转换规则不能超过 20 项")
            for rule in transforms:
                if not isinstance(rule, dict):
                    raise EltError("ELT_TRANSFORM_INVALID", "转换规则必须是 JSON 对象")
                if str(rule.get("op") or "").strip().lower() not in ALLOWED_TRANSFORMS:
                    raise EltError("ELT_TRANSFORM_FORBIDDEN", "转换规则包含不允许的操作")
        allowed = set(draft.get("allowed_update_fields") or [])
        updatable = {field.key for field in adapter.fields if field.updatable}
        if not allowed.issubset(updatable):
            raise EltError("ELT_UPDATE_FIELDS_FORBIDDEN", "包含目标不允许更新的字段")
        match_keys = draft.get("match_keys") or []
        if not isinstance(match_keys, list) or not set(match_keys).issubset(
            set(adapter.default_match_keys)
        ):
            raise EltError("ELT_MATCH_KEYS_UNSUPPORTED", "包含目标不支持的匹配键")
        action_rules = draft.get("action_rules") or {}
        if not isinstance(action_rules, dict):
            raise EltError("ELT_ACTION_RULES_INVALID", "action_rules 必须是 JSON 对象")
        validation_rules = draft.get("validation_rules") or []
        if not isinstance(validation_rules, list):
            raise EltError("ELT_VALIDATION_RULES_INVALID", "validation_rules 必须是数组")
        if len(validation_rules) > 100:
            raise EltError("ELT_VALIDATION_RULES_INVALID", "校验规则不能超过 100 项")
        target_fields = {field.key for field in adapter.fields}
        for rule in validation_rules:
            if not isinstance(rule, dict):
                raise EltError("ELT_VALIDATION_RULE_INVALID", "校验规则必须是 JSON 对象")
            field = str(rule.get("field") or "")
            op = str(rule.get("op") or "").lower()
            if field not in target_fields or op not in ALLOWED_VALIDATION_OPS:
                raise EltError("ELT_VALIDATION_RULE_INVALID", "校验规则包含未知字段或操作")
            if op == "enum":
                values = rule.get("value")
                if not isinstance(values, list) or len(values) > 1000:
                    raise EltError("ELT_VALIDATION_RULE_INVALID", "枚举校验值必须是有限数组")

    def _revalidate_existing_rows(
        self, db: Session, run_id: str, owner_user_id: int, *, publish: bool = True
    ) -> None:
        run = self._owned_run(db, run_id, owner_user_id)
        snapshot = self._load_source_snapshot(db, run)
        if snapshot is not None:
            snapshot.close()
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        adapter = get_adapter(run.target_type)
        draft = load_json(run.draft_json, {})
        mappings = draft.get("field_mappings") or []
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        validation_rules = draft.get("validation_rules") or []
        counts = {"new": 0, "update": 0, "skip": 0, "error": 0}
        llm_degraded = False
        preview_cache: dict[str, Any] = {}
        advisory_jobs: list[tuple[EltRunRow, dict[str, Any]]] = []
        from app.application.elt.llm_assist import etl_row_advice_limit

        advisory_limit = etl_row_advice_limit()
        last_id = 0
        processed = 0
        page_size = 500
        for _page_number in range((MAX_ROWS + page_size - 1) // page_size + 1):
            rows = (
                db.query(EltRunRow)
                .filter(
                    EltRunRow.run_id == run_id,
                    EltRunRow.owner_user_id == owner_user_id,
                    EltRunRow.id > last_id,
                )
                .order_by(EltRunRow.id)
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
                except EltError as exc:
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
                            "code": "ELT_OCR_CONFIRMATION_REQUIRED",
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
                action = "error" if issues else decision.action
                row.normalized_json = dump_json(normalized)
                row.validation_json = dump_json(issues)
                row.suggested_action = decision.action
                row.final_action = action
                row.action_overridden = False
                row.match_ref = decision.match_ref or None
                row.before_json = dump_json(decision.before or {})
                row.after_json = dump_json(decision.after or {})
                advisory_input = {
                    "deterministic_action": decision.action,
                    "deterministic_reason": decision.reason,
                    "normalized": normalized,
                    "before": decision.before or {},
                    "after": decision.after or {},
                }
                row.llm_suggestion_json = dump_json(self._adviser.fallback(**advisory_input))
                if len(advisory_jobs) < advisory_limit:
                    advisory_jobs.append((row, advisory_input))
                counts[action] += 1
            run.progress = min(95, 20 + int(processed / max(1, run.total_rows) * 75))
            run.processed_rows = processed
            db.commit()
        if advisory_jobs:
            suggestions = self._adviser.suggest_many([payload for _row, payload in advisory_jobs])
            for (row, _payload), advisory in zip(advisory_jobs, suggestions, strict=False):
                row.llm_suggestion_json = dump_json(advisory)
                llm_degraded = llm_degraded or bool(advisory.get("degraded"))
        self._set_run_counts(run, counts)
        summary = load_json(run.summary_json, {})
        summary["llm_degraded"] = llm_degraded
        summary["llm_advisory_only"] = True
        run.summary_json = dump_json(summary)
        if publish:
            run.status = run.stage = "preview_ready"
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
                raise EltError("ELT_ROW_ACTION_INVALID", f"不允许的逐行动作: {action}")
            row = (
                db.query(EltRunRow)
                .filter(
                    EltRunRow.id == int(raw_id),
                    EltRunRow.run_id == run_id,
                    EltRunRow.owner_user_id == owner_user_id,
                )
                .first()
            )
            if row is None:
                raise EltNotFound("预演行")
            if row.execution_status in {"success", "rolled_back"}:
                raise EltConflict("ELT_ROW_ALREADY_EXECUTED", "已执行成功的行不能再次修改动作")
            if load_json(row.validation_json, []):
                raise EltConflict(
                    "ELT_INVALID_ROW_CANNOT_OVERRIDE", "存在校验错误的行只能保持错误状态"
                )
            if action == "update" and not row.match_ref:
                raise EltConflict(
                    "ELT_ROW_UPDATE_REQUIRES_MATCH",
                    "更新动作必须先匹配到现有数据",
                )
            if action == "update" and not allowed_updates:
                raise EltConflict(
                    "ELT_ROW_UPDATE_FIELDS_REQUIRED",
                    "更新动作必须先确认允许更新的字段",
                )
            if action == "new" and (row.match_ref or row.suggested_action == "skip"):
                raise EltConflict(
                    "ELT_DUPLICATE_CANNOT_FORCE_NEW",
                    "已匹配的重复数据不能强制新增，请修改匹配字段后重新预演",
                )
            row.final_action = str(action)
            row.action_overridden = True
        counts = {
            action: db.query(EltRunRow)
            .filter(
                EltRunRow.run_id == run_id,
                EltRunRow.owner_user_id == owner_user_id,
                EltRunRow.final_action == action,
            )
            .count()
            for action in ("new", "update", "skip", "error")
        }
        self._set_run_counts(run, counts)
        db.commit()

    def _set_run_counts(self, run: EltRun, counts: dict[str, int]) -> None:
        run.new_rows = counts.get("new", 0)
        run.update_rows = counts.get("update", 0)
        run.skip_rows = counts.get("skip", 0)
        run.error_rows = counts.get("error", 0)
        summary = load_json(run.summary_json, {})
        summary["counts"] = counts
        run.summary_json = dump_json(summary)
