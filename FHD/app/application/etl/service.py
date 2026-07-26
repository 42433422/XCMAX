"""通用 ETL V1 编排服务。"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.application.etl.adviser import EtlRowAdviser, get_etl_row_adviser
from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.parsers import (
    KNOWLEDGE_ONLY_SUFFIXES,
    MAX_ROWS,
    OCR_SUFFIXES,
    STRUCTURED_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ParsedDataset,
    parse_file,
)
from app.application.etl.secrets import delete_webhook_secret, store_webhook_secret
from app.application.etl.targets import (
    TargetAdapter,
    get_adapter,
    json_safe,
    target_capabilities,
)
from app.application.etl.transforms import ALLOWED_TRANSFORMS, apply_mapping
from app.db import SessionLocal
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.infrastructure.tenant_scope import tenant_id_for_write, tenant_scope
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fhd-etl")
_SUBMITTED: set[str] = set()
_SUBMITTED_LOCK = threading.Lock()
_SENSITIVE_WEBHOOK_HEADER_PARTS = ("authorization", "cookie", "token", "secret", "api-key")
_ALLOWED_VALIDATION_OPS = frozenset(
    {"required", "enum", "min", "max", "min_length", "max_length"}
)


def _dump(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, default=str)


def _load(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return default
    return value


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clean_filename(value: str) -> str:
    name = Path(str(value or "upload")).name.replace("\x00", "")
    return (name[:240] or "upload").strip()


def _mapping_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _safe_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, EtlError):
        return exc.code, exc.message
    logger.exception("ETL operation failed")
    return "ETL_INTERNAL_ERROR", "ETL 处理失败，请检查文件或稍后重试"


def _sanitize_webhook_headers(headers: dict[str, Any]) -> dict[str, str]:
    if len(headers) > 40:
        raise EtlError("ETL_WEBHOOK_HEADERS_INVALID", "Webhook 请求头数量不能超过 40")
    cleaned: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        lowered = name.casefold()
        if (
            not name
            or len(name) > 128
            or len(value) > 2048
            or "\r" in name
            or "\n" in name
            or "\r" in value
            or "\n" in value
        ):
            raise EtlError("ETL_WEBHOOK_HEADERS_INVALID", "Webhook 请求头格式无效")
        if any(part in lowered for part in _SENSITIVE_WEBHOOK_HEADER_PARTS):
            raise EtlError(
                "ETL_WEBHOOK_SECRET_HEADER_FORBIDDEN",
                "敏感请求头必须通过系统凭据管理器配置",
            )
        cleaned[name] = value
    return cleaned


def _apply_validation_rules(
    data: dict[str, Any], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for rule in rules:
        field = str(rule.get("field") or "").strip()
        op = str(rule.get("op") or "").strip().lower()
        value = data.get(field)
        expected = rule.get("value")
        failed = False
        if op == "required":
            failed = value in (None, "")
        elif op == "enum":
            failed = not isinstance(expected, list) or value not in expected
        elif op in {"min", "max"}:
            try:
                actual_number = float(value)
                expected_number = float(expected)
                failed = (
                    actual_number < expected_number
                    if op == "min"
                    else actual_number > expected_number
                )
            except (TypeError, ValueError):
                failed = True
        elif op in {"min_length", "max_length"}:
            try:
                actual_length = len(str(value or ""))
                expected_length = int(expected)
                failed = (
                    actual_length < expected_length
                    if op == "min_length"
                    else actual_length > expected_length
                )
            except (TypeError, ValueError):
                failed = True
        if failed:
            issues.append(
                {
                    "code": "ETL_VALIDATION_RULE_FAILED",
                    "severity": "error",
                    "field": field,
                    "message": str(rule.get("message") or f"{field} 未通过 {op} 校验")[:300],
                }
            )
    return issues


class EtlService:
    def __init__(self, *, adviser: EtlRowAdviser | None = None) -> None:
        self._adviser = adviser or get_etl_row_adviser()

    def capabilities(self) -> dict[str, Any]:
        try:
            from app.application.shipment_etl_profile import list_profiles

            compatibility_presets = list_profiles()
        except Exception:  # noqa: BLE001 - 兼容预设不可阻断通用 ETL
            compatibility_presets = []
        return {
            "enabled": True,
            "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_rows": MAX_ROWS},
            "inputs": {
                "structured": sorted(STRUCTURED_SUFFIXES),
                "ocr": sorted(OCR_SUFFIXES),
                "knowledge_only": sorted(KNOWLEDGE_ONLY_SUFFIXES),
            },
            "transforms": sorted(ALLOWED_TRANSFORMS),
            "targets": target_capabilities(),
            "compatibility_presets": compatibility_presets,
            "execution_policy": {
                "preview_required": True,
                "confirmation_required": True,
                "default_duplicate_action": "skip",
                "default_error_policy": "block_all",
            },
        }

    def save_upload(
        self,
        db: Session,
        *,
        owner_user_id: int,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        tenant_id = tenant_id_for_write()
        safe_name = _clean_filename(file_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise EtlError("ETL_FILE_TYPE_UNSUPPORTED", f"不支持的文件类型: {suffix}")
        upload_id = _uuid()
        root = (
            Path(get_app_data_dir()).resolve()
            / "etl"
            / "uploads"
            / str(tenant_id)
            / str(owner_user_id)
        )
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / f"{upload_id}{suffix}").resolve()
        if root not in destination.parents:
            raise EtlError("ETL_UPLOAD_PATH_INVALID", "上传路径无效")

        digest = hashlib.sha256()
        total = 0
        try:
            with destination.open("xb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise EtlError(
                            "ETL_FILE_TOO_LARGE",
                            "单文件不能超过 50MB",
                            status_code=413,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if total == 0:
            destination.unlink(missing_ok=True)
            raise EtlError("ETL_FILE_EMPTY", "上传文件为空")

        upload = EtlUpload(
            id=upload_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            file_name=safe_name,
            suffix=suffix,
            content_type=str(content_type or "")[:128] or None,
            size_bytes=total,
            sha256=digest.hexdigest(),
            storage_path=str(destination),
            expires_at=_utcnow() + timedelta(days=7),
        )
        db.add(upload)
        db.flush()
        return self.upload_dict(upload)

    def upload_dict(self, upload: EtlUpload) -> dict[str, Any]:
        return {
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "suffix": upload.suffix,
            "size_bytes": upload.size_bytes,
            "sha256": upload.sha256,
            "expires_at": upload.expires_at.isoformat() if upload.expires_at else None,
        }

    def _owned_upload(self, db: Session, upload_id: str, owner_user_id: int) -> EtlUpload:
        upload = self._owned_upload_record(db, upload_id, owner_user_id)
        if upload.expires_at:
            expires_at = upload.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < _utcnow():
                raise EtlError("ETL_UPLOAD_EXPIRED", "上传文件已过期", status_code=410)
        if not upload.storage_path or not Path(upload.storage_path).is_file():
            raise EtlError("ETL_UPLOAD_MISSING", "上传文件已被清理", status_code=410)
        return upload

    @staticmethod
    def _owned_upload_record(
        db: Session, upload_id: str, owner_user_id: int
    ) -> EtlUpload:
        upload = (
            db.query(EtlUpload)
            .filter(EtlUpload.id == upload_id, EtlUpload.owner_user_id == owner_user_id)
            .first()
        )
        if upload is None:
            raise EtlNotFound("上传文件")
        return upload

    def create_preview(
        self,
        db: Session,
        *,
        owner_user_id: int,
        upload_id: str,
        target_type: str,
        template_id: str | None = None,
        target_config_id: str | None = None,
    ) -> dict[str, Any]:
        upload = self._owned_upload(db, upload_id, owner_user_id)
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
        if template_id:
            template = self._owned_template(db, template_id, owner_user_id)
            if template.target_type != target_type:
                raise EtlError("ETL_TEMPLATE_TARGET_MISMATCH", "模板目标与本次目标不一致")
            version = self._current_version(db, template, owner_user_id)
            draft.update(
                {
                    "field_mappings": _load(version.field_mappings_json, []),
                    "validation_rules": _load(version.validation_rules_json, []),
                    "match_keys": _load(version.match_keys_json, []),
                    "allowed_update_fields": _load(version.allowed_update_fields_json, []),
                    "action_rules": _load(version.action_rules_json, {}),
                }
            )
        run = EtlRun(
            id=_uuid(),
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
            draft_json=_dump(draft),
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

    def _submit_preview(self, run_id: str, tenant_id: int, owner_user_id: int) -> None:
        with _SUBMITTED_LOCK:
            if run_id in _SUBMITTED:
                return
            _SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._preview_worker(run_id, owner_user_id)
            finally:
                with _SUBMITTED_LOCK:
                    _SUBMITTED.discard(run_id)

        _EXECUTOR.submit(work)

    def _preview_worker(self, run_id: str, owner_user_id: int) -> None:
        db = SessionLocal()
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

            dataset = parse_file(upload.storage_path, target_type=run.target_type)
            run = self._owned_run(db, run_id, owner_user_id)
            draft = _load(run.draft_json, {})
            if not draft.get("field_mappings"):
                draft["field_mappings"] = self._suggest_mappings(
                    dataset, get_adapter(run.target_type)
                )
                run.draft_json = _dump(draft)
            run.total_rows = len(dataset.rows)
            run.source_features_json = _dump(dataset.source_features)
            run.summary_json = _dump({"warnings": dataset.warnings})
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
            db.commit()
            self._record_preview_metrics(run, started_at, status="success")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            code, message = _safe_error(exc)
            try:
                run = self._owned_run(db, run_id, owner_user_id)
                run.status = "failed"
                run.stage = "failed"
                run.error_code = code
                run.error_message = message[:500]
                db.commit()
                self._record_preview_metrics(run, started_at, status="failed")
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL preview failure for run %s", run_id)
        finally:
            db.close()

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
                summary = _load(run.summary_json, {})
                if summary.get("llm_degraded"):
                    etl_llm_degradations_total.labels(run.target_type).inc()
        except Exception:  # noqa: BLE001 - 遥测永不阻断 ETL
            logger.debug("ETL preview metrics unavailable", exc_info=True)

    def _materialize_preview_rows(
        self, db: Session, run: EtlRun, upload: EtlUpload, dataset: ParsedDataset
    ) -> None:
        adapter = get_adapter(run.target_type)
        draft = _load(run.draft_json, {})
        mappings = draft.get("field_mappings") or []
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        validation_rules = draft.get("validation_rules") or []
        counts = {"new": 0, "update": 0, "skip": 0, "error": 0}
        llm_degraded = False
        preview_cache: dict[str, Any] = {}
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
            issues.extend(_apply_validation_rules(normalized, validation_rules))
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
            advisory = self._adviser.suggest(
                deterministic_action=decision.action,
                deterministic_reason=decision.reason,
                normalized=normalized,
                before=decision.before or {},
                after=decision.after or {},
            )
            llm_degraded = llm_degraded or bool(advisory.get("degraded"))
            db.add(
                EtlRunRow(
                    tenant_id=tenant_id_for_write(),
                    owner_user_id=run.owner_user_id,
                    run_id=run.id,
                    source_sheet=source.sheet,
                    source_row=source.row_number,
                    source_json=_dump(source.values),
                    normalized_json=_dump(normalized),
                    provenance_json=_dump(source.provenance),
                    validation_json=_dump(issues),
                    llm_suggestion_json=_dump(advisory),
                    suggested_action=decision.action,
                    final_action=action,
                    match_ref=decision.match_ref or None,
                    before_json=_dump(decision.before or {}),
                    after_json=_dump(decision.after or {}),
                )
            )
            if index % 500 == 0:
                run.progress = min(95, 20 + int(index / max(1, len(dataset.rows)) * 75))
                run.processed_rows = index
                db.commit()
        run.new_rows = counts["new"]
        run.update_rows = counts["update"]
        run.skip_rows = counts["skip"]
        run.error_rows = counts["error"]
        summary = _load(run.summary_json, {})
        summary.update(
            {
                "counts": counts,
                "llm_degraded": llm_degraded,
                "llm_advisory_only": True,
            }
        )
        run.summary_json = _dump(summary)
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
        header_map = {_mapping_key(header): header for header in dataset.headers}
        try:
            from app.application.excel_etl_kb import get_excel_etl_kb

            shared_synonyms = get_excel_etl_kb().synonyms()
        except Exception:  # noqa: BLE001 - 同义词种子不可用时退回适配器别名
            shared_synonyms = {}
        compatibility_keys = {
            "external_order_no": ("order_number",),
            "product_model": ("model_number",),
            "quantity": ("quantity_tins",),
        }
        mappings: list[dict[str, Any]] = []
        for field in adapter.fields:
            synonym_keys = (field.key, *compatibility_keys.get(field.key, ()))
            shared_candidates = tuple(
                alias
                for synonym_key in synonym_keys
                for alias in shared_synonyms.get(synonym_key, [])
            )
            candidates = (field.key, field.label, *field.aliases, *shared_candidates)
            matched = next(
                (
                    header_map[_mapping_key(candidate)]
                    for candidate in candidates
                    if _mapping_key(candidate) in header_map
                ),
                None,
            )
            confidence = 0.98 if matched else 0.0
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
                    "source": matched or "",
                    "target": field.key,
                    "transforms": default_transforms,
                    "confidence": confidence,
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
            "upload_path": upload.storage_path,
            "source_row": source_row,
        }

    def get_run(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if self._execution_is_stale(run):
            run.status = "interrupted"
            run.stage = "interrupted"
            run.error_code = "ETL_EXECUTION_INTERRUPTED"
            run.error_message = "上次执行被意外中断，请重新预演或重试"
            db.commit()
        return self.run_dict(run)

    def list_runs(
        self, db: Session, *, owner_user_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.cleanup_retention(db, owner_user_id=owner_user_id)
        rows = (
            db.query(EtlRun)
            .filter(EtlRun.owner_user_id == owner_user_id)
            .order_by(EtlRun.created_at.desc())
            .limit(min(max(limit, 1), 100))
            .all()
        )
        interrupted = False
        for run in rows:
            if self._execution_is_stale(run):
                run.status = "interrupted"
                run.stage = "interrupted"
                run.error_code = "ETL_EXECUTION_INTERRUPTED"
                run.error_message = "上次执行被意外中断，请重新预演或重试"
                interrupted = True
        if interrupted:
            db.commit()
        return [self.run_dict(run) for run in rows]

    def cleanup_retention(self, db: Session, *, owner_user_id: int) -> dict[str, int]:
        """Apply retention without deleting the long-lived run summary."""

        now = _utcnow()
        upload_root = (Path(get_app_data_dir()).resolve() / "etl" / "uploads").resolve()
        removed_files = 0
        expired_uploads = (
            db.query(EtlUpload)
            .filter(
                EtlUpload.owner_user_id == owner_user_id,
                EtlUpload.expires_at.is_not(None),
                EtlUpload.expires_at < now,
                EtlUpload.storage_path != "",
            )
            .all()
        )
        for upload in expired_uploads:
            path = Path(upload.storage_path).resolve()
            if upload_root in path.parents and path.is_file():
                path.unlink(missing_ok=True)
                removed_files += 1
            upload.storage_path = ""

        cutoff = now - timedelta(days=90)
        old_runs = (
            db.query(EtlRun)
            .filter(
                EtlRun.owner_user_id == owner_user_id,
                EtlRun.created_at < cutoff,
            )
            .all()
        )
        old_run_ids = [run.id for run in old_runs]
        removed_rows = 0
        if old_run_ids:
            removed_rows = (
                db.query(EtlRunRow)
                .filter(
                    EtlRunRow.owner_user_id == owner_user_id,
                    EtlRunRow.run_id.in_(old_run_ids),
                )
                .delete(synchronize_session=False)
            )
            for run in old_runs:
                if run.reversible and run.rollback_status != "completed":
                    run.reversible = False
                    run.rollback_status = "expired"
        if removed_files or removed_rows or old_runs:
            db.commit()
        return {"removed_upload_files": removed_files, "removed_run_rows": removed_rows}

    @staticmethod
    def _execution_is_stale(run: EtlRun) -> bool:
        if run.status != "executing" or run.updated_at is None:
            return False
        with _SUBMITTED_LOCK:
            if run.id in _SUBMITTED:
                return False
        updated = run.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return updated < _utcnow() - timedelta(minutes=5)

    def run_dict(self, run: EtlRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "upload_id": run.upload_id,
            "template_id": run.template_id,
            "template_version_id": run.template_version_id,
            "target_type": run.target_type,
            "status": run.status,
            "stage": run.stage,
            "progress": run.progress,
            "total_rows": run.total_rows,
            "processed_rows": run.processed_rows,
            "summary": {
                "new": run.new_rows,
                "update": run.update_rows,
                "skip": run.skip_rows,
                "error": run.error_rows,
                "executed": run.executed_rows,
            },
            "details": _load(run.summary_json, {}),
            "source_features": _load(run.source_features_json, {}),
            "draft": _load(run.draft_json, {}),
            "receipt": _load(run.receipt_json, {}),
            "reversible": run.reversible,
            "rollback_status": run.rollback_status,
            "error": (
                {"code": run.error_code, "message": run.error_message} if run.error_code else None
            ),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "executed_at": run.executed_at.isoformat() if run.executed_at else None,
        }

    def get_rows(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        page: int,
        page_size: int,
        action: str | None = None,
    ) -> dict[str, Any]:
        self._owned_run(db, run_id, owner_user_id)
        query = db.query(EtlRunRow).filter(
            EtlRunRow.run_id == run_id, EtlRunRow.owner_user_id == owner_user_id
        )
        if action:
            query = query.filter(EtlRunRow.final_action == action)
        total = query.count()
        rows = (
            query.order_by(EtlRunRow.id)
            .offset((max(page, 1) - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "page": max(page, 1),
            "page_size": page_size,
            "total": total,
            "items": [self.row_dict(row) for row in rows],
        }

    def row_dict(self, row: EtlRunRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_sheet": row.source_sheet,
            "source_row": row.source_row,
            "source": _load(row.source_json, {}),
            "normalized": _load(row.normalized_json, {}),
            "provenance": _load(row.provenance_json, {}),
            "validation_issues": _load(row.validation_json, []),
            "llm_suggestion": _load(row.llm_suggestion_json, {}),
            "suggested_action": row.suggested_action,
            "final_action": row.final_action,
            "action_overridden": row.action_overridden,
            "match_ref": row.match_ref,
            "before": _load(row.before_json, {}),
            "after": _load(row.after_json, {}),
            "execution_status": row.execution_status,
            "execution_error": (
                {
                    "code": row.execution_error_code,
                    "message": row.execution_error_message,
                }
                if row.execution_error_code
                else None
            ),
        }

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
        }
        changes_draft = any(key in patch for key in draft_keys)
        overrides = patch.get("row_overrides") or {}
        if not changes_draft:
            if isinstance(overrides, dict) and overrides:
                self._apply_row_overrides(db, run.id, owner_user_id, overrides)
                self._record_correction_metrics(mapping_changed=False, overrides=overrides)
            return self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)

        draft = _load(run.draft_json, {})
        for key in draft_keys:
            if key in patch:
                draft[key] = patch[key]
        self._validate_draft(draft, get_adapter(run.target_type))
        run.draft_json = _dump(draft)
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
    def _record_correction_metrics(
        *, mapping_changed: bool, overrides: dict[str, Any]
    ) -> None:
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
        with _SUBMITTED_LOCK:
            if run_id in _SUBMITTED:
                return
            _SUBMITTED.add(run_id)

        def work() -> None:
            db = SessionLocal()
            try:
                with tenant_scope(tenant_id):
                    self._revalidate_existing_rows(db, run_id, owner_user_id)
                    if overrides:
                        self._apply_row_overrides(db, run_id, owner_user_id, overrides)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                code, message = _safe_error(exc)
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
                with _SUBMITTED_LOCK:
                    _SUBMITTED.discard(run_id)

        _EXECUTOR.submit(work)

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
            if field not in target_fields or op not in _ALLOWED_VALIDATION_OPS:
                raise EtlError("ETL_VALIDATION_RULE_INVALID", "校验规则包含未知字段或操作")
            if op == "enum":
                values = rule.get("value")
                if not isinstance(values, list) or len(values) > 1000:
                    raise EtlError("ETL_VALIDATION_RULE_INVALID", "枚举校验值必须是有限数组")

    def _revalidate_existing_rows(self, db: Session, run_id: str, owner_user_id: int) -> None:
        run = self._owned_run(db, run_id, owner_user_id)
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        adapter = get_adapter(run.target_type)
        draft = _load(run.draft_json, {})
        mappings = draft.get("field_mappings") or []
        allowed_updates = set(draft.get("allowed_update_fields") or [])
        validation_rules = draft.get("validation_rules") or []
        counts = {"new": 0, "update": 0, "skip": 0, "error": 0}
        llm_degraded = False
        preview_cache: dict[str, Any] = {}
        last_id = 0
        processed = 0
        while True:
            rows = (
                db.query(EtlRunRow)
                .filter(
                    EtlRunRow.run_id == run_id,
                    EtlRunRow.owner_user_id == owner_user_id,
                    EtlRunRow.id > last_id,
                )
                .order_by(EtlRunRow.id)
                .limit(500)
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
                    normalized = apply_mapping(_load(row.source_json, {}), mappings)
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
                issues.extend(_apply_validation_rules(normalized, validation_rules))
                provenance = _load(row.provenance_json, {})
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
                action = "error" if issues else decision.action
                row.normalized_json = _dump(normalized)
                row.validation_json = _dump(issues)
                row.suggested_action = decision.action
                row.final_action = action
                row.action_overridden = False
                row.match_ref = decision.match_ref or None
                row.before_json = _dump(decision.before or {})
                row.after_json = _dump(decision.after or {})
                advisory = self._adviser.suggest(
                    deterministic_action=decision.action,
                    deterministic_reason=decision.reason,
                    normalized=normalized,
                    before=decision.before or {},
                    after=decision.after or {},
                )
                llm_degraded = llm_degraded or bool(advisory.get("degraded"))
                row.llm_suggestion_json = _dump(advisory)
                counts[action] += 1
            run.progress = min(95, 20 + int(processed / max(1, run.total_rows) * 75))
            run.processed_rows = processed
            db.commit()
        self._set_run_counts(run, counts)
        summary = _load(run.summary_json, {})
        summary["llm_degraded"] = llm_degraded
        summary["llm_advisory_only"] = True
        run.summary_json = _dump(summary)
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
        draft = _load(run.draft_json, {})
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
            if _load(row.validation_json, []):
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
        summary = _load(run.summary_json, {})
        summary["counts"] = counts
        run.summary_json = _dump(summary)

    def execute(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        confirmed: bool,
        valid_rows_only: bool,
    ) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if not confirmed:
            raise EtlError("ETL_CONFIRMATION_REQUIRED", "执行前必须显式确认")
        if run.status != "preview_ready":
            raise EtlConflict("ETL_PREVIEW_REQUIRED", "请先完成预演再执行")
        if run.error_rows and not valid_rows_only:
            raise EtlConflict(
                "ETL_INVALID_ROWS_BLOCKED",
                "预演存在错误行；默认阻断整批。仅在明确选择“仅写入正确行”后才能继续",
            )
        get_adapter(run.target_type)
        self._owned_upload(db, run.upload_id, owner_user_id)
        draft = _load(run.draft_json, {})
        if run.target_type == "webhook":
            config_id = str(draft.get("target_config_id") or "")
            self._owned_target_config(db, config_id, owner_user_id)
        run.status = "executing"
        run.stage = "executing"
        run.progress = 0
        run.confirmed_at = _utcnow()
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        self._submit_execution(run.id, tenant_id, owner_user_id, valid_rows_only)
        db.expire_all()
        return self.get_run(db, run_id=run.id, owner_user_id=owner_user_id)

    def _submit_execution(
        self,
        run_id: str,
        tenant_id: int,
        owner_user_id: int,
        valid_rows_only: bool,
    ) -> None:
        with _SUBMITTED_LOCK:
            if run_id in _SUBMITTED:
                return
            _SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._execute_worker(run_id, owner_user_id, valid_rows_only)
            finally:
                with _SUBMITTED_LOCK:
                    _SUBMITTED.discard(run_id)

        _EXECUTOR.submit(work)

    def _execute_worker(
        self,
        run_id: str,
        owner_user_id: int,
        valid_rows_only: bool,
    ) -> None:
        db = SessionLocal()
        started_at = time.monotonic()
        try:
            run = self._owned_run(db, run_id, owner_user_id)
            upload = self._owned_upload(db, run.upload_id, owner_user_id)
            adapter = get_adapter(run.target_type)
            draft = _load(run.draft_json, {})
            target_config = None
            if run.target_type == "webhook":
                config_id = str(draft.get("target_config_id") or "")
                target_config = self._owned_target_config(db, config_id, owner_user_id)

            eligible_filters = (
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.final_action.in_(["new", "update"]),
                or_(
                    EtlRunRow.execution_status.is_(None),
                    EtlRunRow.execution_status != "success",
                ),
            )
            eligible_count = db.query(EtlRunRow).filter(*eligible_filters).count()
            context = self._row_context(run, upload, 0)
            context["_execution_cache"] = {}
            context["row_count"] = eligible_count
            context["output_headers"] = [
                str(item.get("target") or "")
                for item in draft.get("field_mappings") or []
                if str(item.get("target") or "")
            ]
            if target_config:
                context["target_config"] = {
                    "endpoint_url": target_config.endpoint_url,
                    "headers": _load(target_config.headers_json, {}),
                    "secret_ref": target_config.secret_ref,
                }

            def progress_callback(processed: int, total: int) -> None:
                current = self._owned_run(db, run_id, owner_user_id)
                current.progress = min(99, int(processed / max(1, total) * 100))
                db.commit()

            context["progress_callback"] = progress_callback
            if hasattr(adapter, "execute_batch"):
                previous = (
                    db.query(EtlRunRow)
                    .filter(
                        EtlRunRow.run_id == run.id,
                        EtlRunRow.owner_user_id == owner_user_id,
                        EtlRunRow.execution_status == "success",
                    )
                    .count()
                )
                def normalized_rows():
                    last_id = 0
                    while True:
                        page = (
                            db.query(EtlRunRow)
                            .filter(*eligible_filters, EtlRunRow.id > last_id)
                            .order_by(EtlRunRow.id)
                            .limit(500)
                            .all()
                        )
                        if not page:
                            break
                        for row in page:
                            last_id = row.id
                            yield _load(row.normalized_json, {})

                result = adapter.execute_batch(normalized_rows(), context)
                db.query(EtlRunRow).filter(*eligible_filters).update(
                    {
                        EtlRunRow.execution_status: "success",
                        EtlRunRow.execution_error_code: None,
                        EtlRunRow.execution_error_message: None,
                    },
                    synchronize_session=False,
                )
                run.executed_rows = previous + int(
                    result.get("executed") or eligible_count
                )
                run.receipt_json = _dump(result.get("receipt") or {})
                db.commit()
            else:
                eligible = (
                    db.query(EtlRunRow)
                    .filter(*eligible_filters)
                    .order_by(EtlRunRow.id)
                    .all()
                )
                self._execute_rows(
                    db,
                    run,
                    upload,
                    adapter,
                    eligible,
                    set(draft.get("allowed_update_fields") or []),
                    context,
                )
            run = self._owned_run(db, run_id, owner_user_id)
            run.status = "completed"
            run.stage = "completed"
            run.progress = 100
            run.executed_at = _utcnow()
            receipt = _load(run.receipt_json, {})
            receipt.update(
                {
                    "run_id": run.id,
                    "target_type": run.target_type,
                    "executed_rows": run.executed_rows,
                    "new_rows": run.new_rows,
                    "update_rows": run.update_rows,
                    "skip_rows": run.skip_rows,
                    "error_rows": run.error_rows,
                    "reversible": run.reversible,
                    "partial": bool(valid_rows_only and run.error_rows),
                }
            )
            run.receipt_json = _dump(receipt)
            db.commit()
            self._record_execution_metrics(run, started_at, "success")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            code, message = _safe_error(exc)
            try:
                run = self._owned_run(db, run_id, owner_user_id)
                run.status = "failed"
                run.stage = "failed"
                run.error_code = code
                run.error_message = message[:500]
                db.commit()
                self._record_execution_metrics(run, started_at, "failed")
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL execution failure for %s", run_id)
        finally:
            db.close()

    @staticmethod
    def _record_execution_metrics(run: EtlRun, started_at: float, status: str) -> None:
        try:
            from app.utils.metrics import etl_run_duration_seconds, etl_runs_total

            etl_runs_total.labels("execute", run.target_type, status).inc()
            etl_run_duration_seconds.labels("execute", run.target_type).observe(
                max(0.0, time.monotonic() - started_at)
            )
        except Exception:  # noqa: BLE001
            logger.debug("ETL execution metrics unavailable", exc_info=True)

    def _execute_rows(
        self,
        db: Session,
        run: EtlRun,
        upload: EtlUpload,
        adapter: TargetAdapter,
        rows: list[EtlRunRow],
        allowed_updates: set[str],
        base_context: dict[str, Any],
    ) -> None:
        executed = run.executed_rows
        total = len(rows)
        for chunk_start in range(0, total, 500):
            chunk = rows[chunk_start : chunk_start + 500]
            completed_in_chunk = 0
            try:
                for row in chunk:
                    context = {
                        **base_context,
                        "source_row": row.source_row,
                    }
                    result = adapter.execute_row(
                        db,
                        _load(row.normalized_json, {}),
                        action=row.final_action,
                        match_ref=str(row.match_ref or ""),
                        allowed_update_fields=allowed_updates,
                        context=context,
                    )
                    row.match_ref = str(result.get("match_ref") or row.match_ref or "")
                    row.after_json = _dump(result.get("after") or _load(row.after_json, {}))
                    row.execution_status = "success"
                    row.execution_error_code = None
                    row.execution_error_message = None
                    completed_in_chunk += 1
                executed += completed_in_chunk
                run.executed_rows = executed
                run.progress = min(99, int((chunk_start + len(chunk)) / max(1, total) * 100))
                db.commit()
            except Exception as exc:  # noqa: BLE001
                failed_row_id = row.id
                completed_row_ids = [item.id for item in chunk[:completed_in_chunk]]
                db.rollback()
                code, message = _safe_error(exc)
                # The chunk transaction is atomic for throughput.  If a later row
                # fails, replay only the successful prefix and commit it once so
                # retry/rollback retain exact per-row progress.
                for completed_row_id in completed_row_ids:
                    completed_row = db.get(EtlRunRow, completed_row_id)
                    if completed_row is None:
                        continue
                    context = {
                        **base_context,
                        "source_row": completed_row.source_row,
                    }
                    result = adapter.execute_row(
                        db,
                        _load(completed_row.normalized_json, {}),
                        action=completed_row.final_action,
                        match_ref=str(completed_row.match_ref or ""),
                        allowed_update_fields=allowed_updates,
                        context=context,
                    )
                    completed_row.match_ref = str(
                        result.get("match_ref") or completed_row.match_ref or ""
                    )
                    completed_row.after_json = _dump(
                        result.get("after") or _load(completed_row.after_json, {})
                    )
                    completed_row.execution_status = "success"
                    completed_row.execution_error_code = None
                    completed_row.execution_error_message = None
                if completed_row_ids:
                    executed += len(completed_row_ids)
                    replay_run = self._owned_run(db, run.id, run.owner_user_id)
                    replay_run.executed_rows = executed
                    db.commit()
                failed_row = db.get(EtlRunRow, failed_row_id)
                if failed_row:
                    failed_row.execution_status = "failed"
                    failed_row.execution_error_code = code
                    failed_row.execution_error_message = message[:500]
                run = self._owned_run(db, run.id, run.owner_user_id)
                run.executed_rows = executed
                db.commit()
                raise

    def retry(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"failed", "interrupted"}:
            raise EtlConflict("ETL_RETRY_NOT_ALLOWED", "当前运行无需重试")
        if run.rollback_status == "completed":
            raise EtlConflict("ETL_ALREADY_ROLLED_BACK", "本次运行已经撤销，不能重试")
        run.status = "previewing"
        rerun_parse = run.executed_rows == 0 and (
            run.total_rows == 0
            or db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
            )
            .count()
            != run.total_rows
        )
        run.stage = "parsing" if rerun_parse else "validating"
        run.progress = 5 if rerun_parse else 20
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        try:
            from app.utils.metrics import etl_retries_total

            etl_retries_total.labels(run.target_type).inc()
        except Exception:  # noqa: BLE001
            logger.debug("ETL retry metrics unavailable", exc_info=True)
        if rerun_parse:
            self._submit_preview(run_id, tenant_id, owner_user_id)
        else:
            self._submit_revalidation(run_id, tenant_id, owner_user_id)
        db.expire_all()
        return self.get_run(db, run_id=run_id, owner_user_id=owner_user_id)

    def rollback(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"completed", "failed", "interrupted"}:
            raise EtlConflict("ETL_ROLLBACK_NOT_ALLOWED", "当前运行没有可撤销的写入")
        if not run.reversible:
            raise EtlConflict("ETL_TARGET_NOT_REVERSIBLE", "导出和 Webhook 等外部目标不可撤销")
        if run.rollback_status == "completed":
            raise EtlConflict("ETL_ALREADY_ROLLED_BACK", "本次运行已经撤销")
        adapter = get_adapter(run.target_type)
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        rows = (
            db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.execution_status == "success",
            )
            .order_by(EtlRunRow.id.desc())
            .all()
        )
        if not rows:
            raise EtlConflict("ETL_ROLLBACK_EMPTY", "本次运行没有已写入的数据")
        run.rollback_status = "running"
        db.commit()
        try:
            if hasattr(adapter, "rollback_batch"):
                receipt = _load(run.receipt_json, {})
                deleted = adapter.rollback_batch(
                    self._row_context(run, upload, 0),
                    receipt,
                )
                for row in rows:
                    row.execution_status = "rolled_back"
                run.rollback_status = "completed"
                run.rolled_back_at = _utcnow()
                receipt["rollback"] = {
                    "status": "completed",
                    "rows": len(rows),
                    "deleted_records": deleted,
                    "at": run.rolled_back_at.isoformat(),
                }
                run.receipt_json = _dump(receipt)
                db.commit()
                self._record_rollback_metric(run.target_type, "success")
                return self.run_dict(run)
            for row in rows:
                adapter.rollback_row(
                    db,
                    match_ref=str(row.match_ref or ""),
                    before=_load(row.before_json, {}),
                    after=_load(row.after_json, {}),
                    context=self._row_context(run, upload, row.source_row),
                )
                row.execution_status = "rolled_back"
                db.commit()
            run = self._owned_run(db, run_id, owner_user_id)
            run.rollback_status = "completed"
            run.rolled_back_at = _utcnow()
            receipt = _load(run.receipt_json, {})
            receipt["rollback"] = {
                "status": "completed",
                "rows": len(rows),
                "at": run.rolled_back_at.isoformat(),
            }
            run.receipt_json = _dump(receipt)
            db.commit()
            self._record_rollback_metric(run.target_type, "success")
            return self.run_dict(run)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            code, message = _safe_error(exc)
            run = self._owned_run(db, run_id, owner_user_id)
            run.rollback_status = "failed"
            run.error_code = code
            run.error_message = message[:500]
            db.commit()
            self._record_rollback_metric(run.target_type, "failed")
            raise EtlError(code, message, status_code=500) from exc

    @staticmethod
    def _record_rollback_metric(target_type: str, status: str) -> None:
        try:
            from app.utils.metrics import etl_rollbacks_total

            etl_rollbacks_total.labels(target_type, status).inc()
        except Exception:  # noqa: BLE001
            logger.debug("ETL rollback metrics unavailable", exc_info=True)

    def create_template(
        self,
        db: Session,
        *,
        owner_user_id: int,
        name: str,
        target_type: str,
        draft: dict[str, Any],
        source_features: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        adapter = get_adapter(target_type)
        self._validate_draft(draft, adapter)
        template = EtlTemplate(
            id=_uuid(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            name=str(name or "").strip()[:160],
            target_type=target_type,
            current_version=1,
            description=str(description or "").strip() or None,
        )
        if not template.name:
            raise EtlError("ETL_TEMPLATE_NAME_REQUIRED", "模板名称不能为空")
        version = self._build_version(
            template=template,
            owner_user_id=owner_user_id,
            version=1,
            draft=draft,
            source_features=source_features or {},
        )
        db.add_all([template, version])
        db.flush()
        return self.template_dict(template, version)

    def update_template(
        self,
        db: Session,
        *,
        template_id: str,
        owner_user_id: int,
        draft: dict[str, Any],
        source_features: dict[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        template = self._owned_template(db, template_id, owner_user_id)
        self._validate_draft(draft, get_adapter(template.target_type))
        next_version = template.current_version + 1
        version = self._build_version(
            template=template,
            owner_user_id=owner_user_id,
            version=next_version,
            draft=draft,
            source_features=source_features or {},
        )
        if name is not None and str(name).strip():
            template.name = str(name).strip()[:160]
        if description is not None:
            template.description = str(description).strip() or None
        template.current_version = next_version
        db.add(version)
        db.flush()
        return self.template_dict(template, version)

    def _build_version(
        self,
        *,
        template: EtlTemplate,
        owner_user_id: int,
        version: int,
        draft: dict[str, Any],
        source_features: dict[str, Any],
    ) -> EtlTemplateVersion:
        return EtlTemplateVersion(
            id=_uuid(),
            template_id=template.id,
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            version=version,
            target_type=template.target_type,
            source_features_json=_dump(source_features),
            field_mappings_json=_dump(draft.get("field_mappings") or []),
            validation_rules_json=_dump(draft.get("validation_rules") or []),
            match_keys_json=_dump(draft.get("match_keys") or []),
            allowed_update_fields_json=_dump(draft.get("allowed_update_fields") or []),
            action_rules_json=_dump(draft.get("action_rules") or {}),
        )

    def list_templates(self, db: Session, *, owner_user_id: int) -> list[dict[str, Any]]:
        templates = (
            db.query(EtlTemplate)
            .filter(EtlTemplate.owner_user_id == owner_user_id, EtlTemplate.is_active.is_(True))
            .order_by(EtlTemplate.updated_at.desc())
            .all()
        )
        result = []
        for template in templates:
            version = self._current_version(db, template, owner_user_id)
            result.append(self.template_dict(template, version))
        return result

    def get_template(self, db: Session, *, template_id: str, owner_user_id: int) -> dict[str, Any]:
        template = self._owned_template(db, template_id, owner_user_id)
        return self.template_dict(
            template,
            self._current_version(db, template, owner_user_id),
        )

    def template_versions(
        self, db: Session, *, template_id: str, owner_user_id: int
    ) -> list[dict[str, Any]]:
        template = self._owned_template(db, template_id, owner_user_id)
        versions = (
            db.query(EtlTemplateVersion)
            .filter(
                EtlTemplateVersion.template_id == template.id,
                EtlTemplateVersion.owner_user_id == owner_user_id,
            )
            .order_by(EtlTemplateVersion.version.desc())
            .all()
        )
        return [self.template_dict(template, version) for version in versions]

    def delete_template(self, db: Session, *, template_id: str, owner_user_id: int) -> None:
        template = self._owned_template(db, template_id, owner_user_id)
        template.is_active = False

    def template_dict(self, template: EtlTemplate, version: EtlTemplateVersion) -> dict[str, Any]:
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "target_type": template.target_type,
            "current_version": template.current_version,
            "version": {
                "id": version.id,
                "number": version.version,
                "source_features": _load(version.source_features_json, {}),
                "field_mappings": _load(version.field_mappings_json, []),
                "validation_rules": _load(version.validation_rules_json, []),
                "match_keys": _load(version.match_keys_json, []),
                "allowed_update_fields": _load(version.allowed_update_fields_json, []),
                "action_rules": _load(version.action_rules_json, {}),
                "created_at": version.created_at.isoformat() if version.created_at else None,
            },
        }

    def _owned_template(self, db: Session, template_id: str, owner_user_id: int) -> EtlTemplate:
        template = (
            db.query(EtlTemplate)
            .filter(
                EtlTemplate.id == template_id,
                EtlTemplate.owner_user_id == owner_user_id,
                EtlTemplate.is_active.is_(True),
            )
            .first()
        )
        if template is None:
            raise EtlNotFound("模板")
        return template

    def _current_version(
        self, db: Session, template: EtlTemplate, owner_user_id: int
    ) -> EtlTemplateVersion:
        version = (
            db.query(EtlTemplateVersion)
            .filter(
                EtlTemplateVersion.template_id == template.id,
                EtlTemplateVersion.owner_user_id == owner_user_id,
                EtlTemplateVersion.version == template.current_version,
            )
            .first()
        )
        if version is None:
            raise EtlError("ETL_TEMPLATE_VERSION_MISSING", "模板版本不存在", status_code=409)
        return version

    def create_target_config(
        self,
        db: Session,
        *,
        owner_user_id: int,
        name: str,
        endpoint_url: str,
        headers: dict[str, Any],
        secret: str | None,
        secret_ref: str | None = None,
    ) -> dict[str, Any]:
        clean_headers = _sanitize_webhook_headers(headers)
        ref = secret_ref
        if secret:
            ref = store_webhook_secret(owner_user_id, secret)
        config = EtlTargetConfig(
            id=_uuid(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            name=str(name or "").strip()[:160],
            target_type="webhook",
            endpoint_url=str(endpoint_url or "").strip(),
            headers_json=_dump(clean_headers),
            secret_ref=ref,
        )
        if not config.name or not config.endpoint_url:
            if secret and ref:
                delete_webhook_secret(ref)
            raise EtlError("ETL_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.add(config)
        db.flush()
        return self.target_config_dict(config)

    def list_target_configs(self, db: Session, *, owner_user_id: int) -> list[dict[str, Any]]:
        configs = (
            db.query(EtlTargetConfig)
            .filter(
                EtlTargetConfig.owner_user_id == owner_user_id,
                EtlTargetConfig.is_active.is_(True),
            )
            .order_by(EtlTargetConfig.updated_at.desc())
            .all()
        )
        return [self.target_config_dict(config) for config in configs]

    def update_target_config(
        self,
        db: Session,
        *,
        config_id: str,
        owner_user_id: int,
        name: str,
        endpoint_url: str,
        headers: dict[str, Any],
        secret: str | None,
    ) -> dict[str, Any]:
        config = self._owned_target_config(db, config_id, owner_user_id)
        clean_headers = _sanitize_webhook_headers(headers)
        old_ref = config.secret_ref
        replacement_ref = store_webhook_secret(owner_user_id, secret) if secret else old_ref
        config.name = str(name or "").strip()[:160]
        config.endpoint_url = str(endpoint_url or "").strip()
        config.headers_json = _dump(clean_headers)
        config.secret_ref = replacement_ref
        if not config.name or not config.endpoint_url:
            if replacement_ref and replacement_ref != old_ref:
                delete_webhook_secret(replacement_ref)
            raise EtlError("ETL_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.flush()
        if replacement_ref != old_ref:
            delete_webhook_secret(old_ref)
        return self.target_config_dict(config)

    def delete_target_config(self, db: Session, *, config_id: str, owner_user_id: int) -> None:
        config = self._owned_target_config(db, config_id, owner_user_id)
        config.is_active = False
        delete_webhook_secret(config.secret_ref)

    def target_config_dict(self, config: EtlTargetConfig) -> dict[str, Any]:
        return {
            "id": config.id,
            "name": config.name,
            "target_type": config.target_type,
            "endpoint_url": config.endpoint_url,
            "headers": _load(config.headers_json, {}),
            "has_secret": bool(config.secret_ref),
            "is_active": config.is_active,
        }

    def _owned_target_config(
        self, db: Session, config_id: str, owner_user_id: int
    ) -> EtlTargetConfig:
        config = (
            db.query(EtlTargetConfig)
            .filter(
                EtlTargetConfig.id == config_id,
                EtlTargetConfig.owner_user_id == owner_user_id,
                EtlTargetConfig.is_active.is_(True),
            )
            .first()
        )
        if config is None:
            raise EtlNotFound("Webhook 配置")
        return config

    def target_config_for_test(
        self, db: Session, *, config_id: str, owner_user_id: int
    ) -> dict[str, Any]:
        config = self._owned_target_config(db, config_id, owner_user_id)
        adapter = get_adapter("webhook")
        result = adapter.execute_batch(
            [],
            {
                "run_id": f"test-{_uuid()}",
                "connectivity_test": True,
                "row_count": 0,
                "target_config": {
                    "endpoint_url": config.endpoint_url,
                    "headers": _load(config.headers_json, {}),
                    "secret_ref": config.secret_ref,
                },
            },
        )
        return {"success": True, "receipt": result.get("receipt", {})}

    def download_path(self, db: Session, *, run_id: str, owner_user_id: int) -> Path:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.target_type not in {"export_xlsx", "export_csv"} or run.status != "completed":
            raise EtlNotFound("导出文件")
        receipt = _load(run.receipt_json, {})
        file_name = Path(str(receipt.get("file_name") or "")).name
        root = (Path(get_app_data_dir()).resolve() / "etl" / "exports").resolve()
        path = (root / file_name).resolve()
        if root not in path.parents or not path.is_file():
            raise EtlNotFound("导出文件")
        return path

    def export_error_rows(self, db: Session, *, run_id: str, owner_user_id: int) -> Path:
        run = self._owned_run(db, run_id, owner_user_id)
        rows = (
            db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.final_action == "error",
            )
            .order_by(EtlRunRow.id)
            .all()
        )
        root = Path(get_app_data_dir()).resolve() / "etl" / "error_exports"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{run.id}-errors.csv"
        import csv

        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["source_sheet", "source_row", "source_json", "issues_json"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "source_sheet": row.source_sheet,
                        "source_row": row.source_row,
                        "source_json": row.source_json,
                        "issues_json": row.validation_json,
                    }
                )
        return path

    def _owned_run(self, db: Session, run_id: str, owner_user_id: int) -> EtlRun:
        run = (
            db.query(EtlRun)
            .filter(EtlRun.id == run_id, EtlRun.owner_user_id == owner_user_id)
            .first()
        )
        if run is None:
            raise EtlNotFound("ETL 运行")
        return run


def mark_interrupted_runs_on_startup(bind: Any) -> int:
    """Recover durable in-flight runs after a desktop/backend cold start."""

    try:
        if not sa_inspect(bind).has_table("etl_runs"):
            return 0
        with bind.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE etl_runs
                    SET status = 'interrupted',
                        stage = 'interrupted',
                        error_code = 'ETL_EXECUTION_INTERRUPTED',
                        error_message = '上次处理被意外中断，请重新预演或重试',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status IN ('queued', 'previewing', 'executing')
                    """
                )
            )
            return max(0, int(result.rowcount or 0))
    except Exception:  # noqa: BLE001 - 启动恢复失败不泄露数据库细节
        logger.exception("Unable to mark interrupted ETL runs during startup")
        return 0


_SERVICE: EtlService | None = None
_SERVICE_LOCK = threading.Lock()


def get_etl_service() -> EtlService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = EtlService()
        return _SERVICE
