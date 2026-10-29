"""Bind explicit execution approval to the exact completed preview being reviewed."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict
from app.application.etl.service_source import SourceServiceMixin
from app.application.etl.service_support import MAX_FILE_BYTES, dump_json, load_json, new_id
from app.db.models.etl import EtlRun, EtlRunRow, EtlTargetConfig, EtlUpload

REVIEW_KEY = "_preview_review"
CONFIRMATION_KEY = "execution_confirmation"


def _changed() -> EtlConflict:
    return EtlConflict("ETL_PREVIEW_CHANGED", "预演内容或目标已变化，请重新预演并确认当前内容")


def invalidate_preview(run: EtlRun) -> None:
    details = load_json(run.summary_json, {})
    details.pop(REVIEW_KEY, None)
    details.pop(CONFIRMATION_KEY, None)
    run.summary_json = dump_json(details)
    run.confirmed_at = None


def preview_revision(run: EtlRun) -> str | None:
    # Revalidation and row overrides may commit intermediate rows while their
    # owner is still active. Never present those rows as a confirmable preview.
    if run.status != "preview_ready" or run.operation_token or run.rollback_status:
        return None
    review = load_json(run.summary_json, {}).get(REVIEW_KEY, {})
    if not isinstance(review, dict) or not review.get("nonce"):
        return None
    value = review.get("revision")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _snapshot(db: Session, run: EtlRun, nonce: str) -> tuple[str, dict[str, Any] | None]:
    """Hash only reviewed content, excluding progress, leases and unrelated metadata.

    Production writers call this while holding the existing operation owner.
    Target values are captured once and returned for the worker's actual dispatch,
    so a second config read cannot silently redirect an approved webhook.
    """
    db.flush()
    upload = (
        db.query(EtlUpload)
        .filter(
            EtlUpload.id == run.upload_id,
            EtlUpload.tenant_id == run.tenant_id,
            EtlUpload.owner_user_id == run.owner_user_id,
        )
        .populate_existing()
        .first()
    )
    if upload is None or upload.sha256 != run.file_sha256:
        raise _changed()
    # The parsed rows can outlive the temporary upload. Only a fully validated
    # structured snapshot is allowed to substitute for a missing original.
    try:
        dataset = SourceServiceMixin()._load_source_snapshot(db, run)
    except EtlConflict as exc:
        raise _changed() from exc
    source_snapshot = (
        load_json(run.summary_json, {})["source_snapshot"] if dataset is not None else None
    )
    snapshot_only = source_snapshot is not None and run.target_type not in {
        "knowledge",
        "attendance",
    }
    source = hashlib.sha256()
    size = 0
    original_read = False
    if upload.storage_path:
        try:
            with Path(upload.storage_path).open("rb") as stream:
                original_read = True
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise _changed()
                    source.update(chunk)
        except FileNotFoundError as exc:
            if not snapshot_only:
                raise _changed() from exc
        except OSError as exc:
            raise _changed() from exc
    elif not snapshot_only:
        raise _changed()
    if original_read and (size != upload.size_bytes or source.hexdigest() != upload.sha256):
        raise _changed()
    target = None
    draft = load_json(run.draft_json, {})
    if run.target_type == "webhook":
        config = (
            db.query(EtlTargetConfig)
            .filter(
                EtlTargetConfig.id == str(draft.get("target_config_id") or ""),
                EtlTargetConfig.tenant_id == run.tenant_id,
                EtlTargetConfig.owner_user_id == run.owner_user_id,
            )
            .populate_existing()
            .first()
        )
        if config is not None:
            target = {
                "id": config.id,
                "name": config.name,
                "target_type": config.target_type,
                "endpoint_url": config.endpoint_url,
                "headers": load_json(config.headers_json, {}),
                "secret_ref": config.secret_ref,
                "is_active": config.is_active,
            }
    digest = hashlib.sha256()
    digest.update(
        dump_json(
            {
                "version": 1,
                "nonce": nonce,
                "run_id": run.id,
                "tenant_id": run.tenant_id,
                "owner_user_id": run.owner_user_id,
                "upload_id": upload.id,
                "file_sha256": upload.sha256,
                **({"source_snapshot": source_snapshot} if source_snapshot is not None else {}),
                "file_name": upload.file_name,
                "relative_path": upload.relative_path,
                "batch_id": upload.batch_id,
                "target_type": run.target_type,
                "target_config": target,
                "template_version_id": run.template_version_id,
                "draft": draft,
                "source_features": load_json(run.source_features_json, {}),
                "counts": [
                    run.total_rows,
                    run.new_rows,
                    run.update_rows,
                    run.skip_rows,
                    run.error_rows,
                    run.executed_rows,
                ],
            }
        ).encode("utf-8")
    )
    rows = (
        db.query(
            EtlRunRow.id,
            EtlRunRow.source_sheet,
            EtlRunRow.source_row,
            EtlRunRow.source_json,
            EtlRunRow.normalized_json,
            EtlRunRow.provenance_json,
            EtlRunRow.validation_json,
            EtlRunRow.final_action,
            EtlRunRow.match_ref,
            EtlRunRow.before_json,
            EtlRunRow.after_json,
            EtlRunRow.execution_status,
        )
        .filter(
            EtlRunRow.run_id == run.id,
            EtlRunRow.tenant_id == run.tenant_id,
            EtlRunRow.owner_user_id == run.owner_user_id,
        )
        .order_by(EtlRunRow.id)
        .yield_per(500)
    )
    for row in rows:
        digest.update(b"\n")
        digest.update(dump_json(list(row)).encode("utf-8"))
    return digest.hexdigest(), target


def publish_preview(db: Session, run: EtlRun) -> None:
    nonce = new_id()
    revision, _target = _snapshot(db, run, nonce)
    details = load_json(run.summary_json, {})
    details[REVIEW_KEY] = {"nonce": nonce, "revision": revision}
    run.summary_json = dump_json(details)


def verify_preview(db: Session, run: EtlRun, revision: str | None) -> dict[str, Any] | None:
    if revision is None or revision == "":
        raise EtlConflict(
            "ETL_PREVIEW_CONFIRMATION_REQUIRED", "请重新预演并明确确认本次内容后再执行"
        )
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        raise _changed()
    review = load_json(run.summary_json, {}).get(REVIEW_KEY)
    if (
        not isinstance(review, dict)
        or not isinstance(review.get("nonce"), str)
        or not isinstance(review.get("revision"), str)
        or not hmac.compare_digest(revision, review["revision"])
    ):
        raise _changed()
    current, target = _snapshot(db, run, review["nonce"])
    if not hmac.compare_digest(revision, current):
        raise _changed()
    return target


def record_confirmation(run: EtlRun, revision: str, *, valid_rows_only: bool) -> None:
    details = load_json(run.summary_json, {})
    details[CONFIRMATION_KEY] = {
        "preview_revision": revision,
        "valid_rows_only": valid_rows_only,
    }
    run.summary_json = dump_json(details)


def verify_execution(db: Session, run: EtlRun, *, valid_rows_only: bool) -> dict[str, Any] | None:
    confirmation = load_json(run.summary_json, {}).get(CONFIRMATION_KEY)
    if (
        not isinstance(confirmation, dict)
        or confirmation.get("valid_rows_only") is not valid_rows_only
    ):
        raise _changed()
    return verify_preview(db, run, confirmation.get("preview_revision"))
