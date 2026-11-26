"""Bind explicit execution approval to the exact completed preview being reviewed."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any

from sqlalchemy import true
from sqlalchemy.orm import Session, object_session

from app.application.elt.errors import EltConflict
from app.application.elt.service_source import SourceServiceMixin
from app.application.elt.service_support import MAX_FILE_BYTES, dump_json, load_json, new_id
from app.db.models.elt import EltRun, EltRunRow, EltTargetConfig, EltUpload

REVIEW_KEY = "_preview_review"
CONFIRMATION_KEY = "execution_confirmation"


def _changed() -> EltConflict:
    return EltConflict("ELT_PREVIEW_CHANGED", "预演内容或目标已变化，请重新预演并确认当前内容")


def invalidate_preview(run: EltRun) -> None:
    details = load_json(run.summary_json, {})
    details.pop(REVIEW_KEY, None)
    details.pop(CONFIRMATION_KEY, None)
    run.summary_json = dump_json(details)
    run.confirmed_at = None


def preview_revision(run: EltRun) -> str | None:
    # Revalidation and row overrides may commit intermediate rows while their
    # owner is still active. Never present those rows as a confirmable preview.
    if run.status != "preview_ready" or run.operation_token or run.rollback_status:
        return None
    review = load_json(run.summary_json, {}).get(REVIEW_KEY, {})
    if not isinstance(review, dict) or not review.get("nonce"):
        return None
    value = review.get("revision")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _snapshot(db: Session, run: EltRun, nonce: str) -> tuple[str, dict[str, Any] | None]:
    """Hash only reviewed content, excluding progress, leases and unrelated metadata.

    Production writers call this while holding the existing operation owner.
    Target values are captured once and returned for the worker's actual dispatch,
    so a second config read cannot silently redirect an approved webhook.
    """
    db.flush()
    upload = (
        db.query(EltUpload)
        .filter(
            EltUpload.id == run.upload_id,
            EltUpload.tenant_id == run.tenant_id,
            EltUpload.owner_user_id == run.owner_user_id,
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
        if dataset is not None:
            dataset.close()
    except EltConflict as exc:
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
            db.query(EltTargetConfig)
            .filter(
                EltTargetConfig.id == str(draft.get("target_config_id") or ""),
                EltTargetConfig.tenant_id == run.tenant_id,
                EltTargetConfig.owner_user_id == run.owner_user_id,
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
            EltRunRow.id,
            EltRunRow.source_sheet,
            EltRunRow.source_row,
            EltRunRow.source_json,
            EltRunRow.normalized_json,
            EltRunRow.provenance_json,
            EltRunRow.validation_json,
            EltRunRow.final_action,
            EltRunRow.match_ref,
            EltRunRow.before_json,
            EltRunRow.after_json,
            EltRunRow.execution_status,
        )
        .filter(
            EltRunRow.run_id == run.id,
            EltRunRow.tenant_id == run.tenant_id,
            EltRunRow.owner_user_id == run.owner_user_id,
            # 导出仍使用 skip/error 行的追踪值或表名，必须绑定它们的确认。
            # 其他目标只哈希写入行，避免全量判重时的逐行序列化开销。
            true()
            if run.target_type in {"shipment_records", "export_xlsx", "export_csv"}
            else EltRunRow.final_action.in_(["new", "update"]),
        )
        .order_by(EltRunRow.id)
        .yield_per(500)
    )
    for row in rows:
        digest.update(b"\n")
        digest.update(dump_json(list(row)).encode("utf-8"))
    return digest.hexdigest(), target


def publish_preview(db: Session, run: EltRun) -> None:
    nonce = new_id()
    revision, _target = _snapshot(db, run, nonce)
    details = load_json(run.summary_json, {})
    details[REVIEW_KEY] = {"nonce": nonce, "revision": revision}
    run.summary_json = dump_json(details)


def verify_preview(db: Session, run: EltRun, revision: str | None) -> dict[str, Any] | None:
    if revision is None or revision == "":
        raise EltConflict(
            "ELT_PREVIEW_CONFIRMATION_REQUIRED", "请重新预演并明确确认本次内容后再执行"
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


def record_confirmation(run: EltRun, revision: str, *, valid_rows_only: bool) -> None:
    details = load_json(run.summary_json, {})
    details[CONFIRMATION_KEY] = {
        "preview_revision": revision,
        "valid_rows_only": valid_rows_only,
    }
    if (db := object_session(run)) is not None:
        db.flush()
        details[CONFIRMATION_KEY]["plan_sha256"] = execution_plan_sha256(db, run)
    run.summary_json = dump_json(details)


def execution_plan_sha256(db: Session, run: EltRun) -> str:
    """Retain approved inputs after execution replaces row references and after images."""
    with db.no_autoflush:
        digest = hashlib.sha256(
            dump_json(
                {
                    "run_id": run.id,
                    "upload_id": run.upload_id,
                    "file_sha256": run.file_sha256,
                    "target_type": run.target_type,
                    "template_version_id": run.template_version_id,
                    "draft": load_json(run.draft_json, {}),
                    "source_features": load_json(run.source_features_json, {}),
                    "counts": [
                        run.total_rows,
                        run.new_rows,
                        run.update_rows,
                        run.skip_rows,
                        run.error_rows,
                    ],
                }
            ).encode()
        )
        rows = (
            db.query(EltRunRow)
            .filter_by(run_id=run.id, tenant_id=run.tenant_id, owner_user_id=run.owner_user_id)
            .order_by(EltRunRow.id)
        )
        for row in rows.yield_per(500):
            digest.update(
                dump_json(
                    [
                        row.id,
                        row.source_sheet,
                        row.source_row,
                        row.source_slice,
                        load_json(row.source_json, {}),
                        load_json(row.normalized_json, {}),
                        load_json(row.provenance_json, {}),
                        load_json(row.validation_json, []),
                        row.final_action,
                        load_json(row.before_json, {}),
                        row.match_ref if row.final_action != "new" else None,
                    ]
                ).encode()
            )
    return digest.hexdigest()


def verify_execution(db: Session, run: EltRun, *, valid_rows_only: bool) -> dict[str, Any] | None:
    confirmation = load_json(run.summary_json, {}).get(CONFIRMATION_KEY)
    if (
        not isinstance(confirmation, dict)
        or confirmation.get("valid_rows_only") is not valid_rows_only
    ):
        raise _changed()
    return verify_preview(db, run, confirmation.get("preview_revision"))


def verify_agent_preview(
    call: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Verify the original owned preview manifests without confirming a business write."""
    from app.application.elt.preview_verification import read_preview_evidence

    return read_preview_evidence(call, output, context)


def _execution_source_hash(db: Session, run: EltRun) -> str:
    """Bind the reviewed inputs that the worker does not replace with its output image."""
    digest = hashlib.sha256(str(run.draft_json).encode())
    rows = db.query(
        EltRunRow.id,
        EltRunRow.source_sheet,
        EltRunRow.source_row,
        EltRunRow.source_json,
        EltRunRow.normalized_json,
        EltRunRow.provenance_json,
        EltRunRow.validation_json,
        EltRunRow.final_action,
        EltRunRow.before_json,
    ).filter_by(run_id=run.id, tenant_id=run.tenant_id, owner_user_id=run.owner_user_id)
    for row in rows.order_by(EltRunRow.id).yield_per(500):
        digest.update(dump_json(list(row)).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _execution_run_ids(params: dict[str, Any]) -> list[str]:
    from app.domain.shared_services.tools_workflow_elt import _split_run_ids

    return _split_run_ids(params.get("run_ids")) or _split_run_ids(params.get("run_id"))


def capture_agent_execution(run: Any, step: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Freeze every original target before dispatch, retaining single-run contracts."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.elt_checkpoint_recovery import checkpoint_step
    from app.application.dataset_rag.document_lifecycle import agent_ingest_read_repository
    from app.application.elt.chat_recall import _REQUIRED_IDENTITY
    from app.application.elt.preview_verification import capture_preview_inputs
    from app.domain.shared_services.tools_workflow_elt import durable_elt_checkpoint_ids

    run_ids = _execution_run_ids(step.params)
    paths = step.params.get("file_paths")
    if paths:
        if run_ids:
            return {}
        durable = checkpoint_step(run) is step
        sources = capture_preview_inputs(step.params, context, preserve_uploads=durable)
        if not sources:
            return {}
        checkpoints = {}
        if durable:
            if any(source["file_path"] != source["upload_id"] for source in sources):
                return {}
            checkpoints = durable_elt_checkpoint_ids(
                context["run_id"], context["step_id"], [source["upload_id"] for source in sources]
            )
        origin = {key: str(context.get(key) or "").strip() for key in _REQUIRED_IDENTITY}
        bound = []
        for source in sources:
            target = {
                "file_path": source["file_path"],
                "upload_id": source["upload_id"],
                "file_sha256": source["sha256"],
                "auxiliary_store_sha256": canonical_hash(
                    str(agent_ingest_read_repository().storage_path)
                ),
            }
            if native_id := checkpoints.get(source["upload_id"]):
                target.update(
                    _capture_execution_target(native_id, context) or {"run_id": native_id}
                )
            elif all(origin.values()):
                target["origin"] = {
                    **origin,
                    "mod_id": str(context.get("mod_id") or context.get("active_mod_id") or ""),
                }
            else:
                return {}
            bound.append(target)
        return {"sources": bound}
    if not run_ids:
        return {}
    if len(run_ids) == 1:
        return _capture_execution_target(run_ids[0], context)
    return {"targets": {run_id: _capture_execution_target(run_id, context) for run_id in run_ids}}


def _capture_execution_target(run_id: str, context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope
    from app.application.elt.auxiliary_verification import capture_auxiliary_sources
    from app.application.elt.row_verification import ROW_TARGETS
    from app.application.elt.service_history import HistoryServiceMixin
    from app.domain.shared_services.tools_workflow_elt import _companion_summary
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        with _transaction_read_scope(context, {"elt.execute"}, "elt") as (db, tenant):
            row = (
                db.query(EltRun)
                .filter_by(
                    id=run_id,
                    tenant_id=tenant,
                    owner_user_id=int(context["user_id"]),
                )
                .one_or_none()
            )
            revision = preview_revision(row) if row is not None else None
            if (
                row is None
                or row.target_type not in ROW_TARGETS | {"dynamic_table"}
                or not revision
            ):
                return {}
            if row.status == "preview_ready":
                verify_preview(db, row, revision)
            details = load_json(row.summary_json, {})
            parent_id = details.get("linked_from_shipment_preview")
            parent = (
                db.query(EltRun)
                .filter_by(id=parent_id, tenant_id=tenant, owner_user_id=row.owner_user_id)
                .one_or_none()
                if parent_id
                else None
            )
            if parent_id and parent is None:
                return {}
            companion = {}
            linked_id = (details.get("linked_customer_products_preview") or {}).get("run_id")
            if linked_id:
                child = (
                    db.query(EltRun)
                    .filter_by(id=linked_id, tenant_id=tenant, owner_user_id=row.owner_user_id)
                    .one_or_none()
                )
                if (
                    child is None
                    or child.target_type != "customer_products"
                    or (child.upload_id, child.file_sha256) != (row.upload_id, row.file_sha256)
                    or load_json(child.summary_json, {}).get("linked_from_shipment_preview")
                    != row.id
                    or not preview_revision(child)
                ):
                    return {}
                companion = _companion_summary(HistoryServiceMixin().run_dict(child))
            return {
                "run_id": row.id,
                "upload_id": row.upload_id,
                "file_sha256": row.file_sha256,
                "target_type": row.target_type,
                "preview_revision": revision,
                "plan_sha256": execution_plan_sha256(db, row),
                "source_sha256": _execution_source_hash(db, row),
                **capture_auxiliary_sources(row),
                # These are the reviewed, pre-dispatch projections. The writer
                # later replaces after_json, so never accept that replacement
                # as the only proof of the requested customer/product values.
                "expected_rows": {
                    str(item.id): load_json(item.after_json, {})
                    for item in db.query(EltRunRow)
                    .filter_by(run_id=row.id, tenant_id=tenant, owner_user_id=row.owner_user_id)
                    .filter(EltRunRow.final_action.in_(("new", "update")))
                },
                "companion_preview": companion,
                "parent_run_id": parent_id,
                "parent_source_sha256": _execution_source_hash(db, parent) if parent else "",
            }
    except RECOVERABLE_ERRORS:
        return {}


def _execution_receipt_readback(
    db: Session, row: EltRun, *, valid_rows_only: bool
) -> dict[str, Any] | None:
    """Read the owned operation ledger and its actual target records without replay."""
    from app.application.elt.dynamic_verification import verify_dynamic_effects
    from app.application.elt.row_verification import verify_row_effects
    from app.domain.task_lifecycle.results import execution_result_requires_reconciliation

    receipt = load_json(row.receipt_json, {})
    details = load_json(row.summary_json, {})
    if (
        row.status != "completed"
        or not (row.confirmed_at and row.executed_at)
        or row.rollback_status
        or row.rolled_back_at
        or row.operation_token
        or row.operation_kind
        or not isinstance(receipt, dict)
        or execution_result_requires_reconciliation(receipt)
        or execution_result_requires_reconciliation(details)
        or receipt.get("run_id") != row.id
        or receipt.get("target_type") != row.target_type
        or receipt.get("executed_rows") != row.executed_rows
        or receipt.get("partial") is not bool(row.error_rows and valid_rows_only)
        or (row.error_rows and not valid_rows_only)
    ):
        return None
    rows = (
        db.query(EltRunRow)
        .filter_by(run_id=row.id, tenant_id=row.tenant_id, owner_user_id=row.owner_user_id)
        .order_by(EltRunRow.id)
        .all()
    )
    expected = [item for item in rows if item.final_action in {"new", "update"}]
    if (
        len(rows) != row.total_rows
        or any(item.execution_status != "success" for item in expected)
        or any(item.execution_status not in (None, "") for item in rows if item not in expected)
    ):
        return None
    if row.target_type == "dynamic_table":
        return verify_dynamic_effects(db, row, rows, receipt)
    if len(expected) != row.executed_rows:
        return None
    return verify_row_effects(db, row, rows)


def verify_agent_execution(
    step: Any, call: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read the original approved SQL import and its rows; never recover or execute a run."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.tool_permission import (
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report
    from app.domain.task_lifecycle.results import (
        execution_result_error,
        execution_result_requires_reconciliation,
    )

    baseline = (call.metadata.get("verification_contract") or {}).get("elt_execution_baseline")
    if not isinstance(baseline, dict) or not baseline:
        return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
    key = idempotency_scope_key(context, step.tool_id, step.action, step.params)
    claim = _reread_claim(key, durable_read_only=True)
    if claim is None or claim.get("inflight") or not isinstance(claim.get("output"), dict):
        return _report("inconclusive", "result_receipt_unavailable", "tool_idempotency")
    receipt_sha256 = canonical_hash(claim["output"])
    if claim.get("fingerprint") != _fingerprint(
        step.params, context
    ) or receipt_sha256 != canonical_hash(output):
        return _report("failed", "result_receipt_mismatch", "tool_idempotency")
    sources = baseline.get("sources") if step.params.get("file_paths") else None
    run_ids = _execution_run_ids(step.params)
    baselines: dict[str, Any] | None
    if sources is not None:
        items = output.get("results")
        if (
            not isinstance(sources, list)
            or not sources
            or output.get("batch") is not True
            or not isinstance(items, list)
            or len(items) != len(sources)
        ):
            return _report("failed", "result_scope_mismatch", "elt_execution")
        baselines = {}
        for source, item in zip(sources, items, strict=True):
            data = item.get("data") if isinstance(item, dict) else None
            run_id = data.get("run_id") if isinstance(data, dict) else None
            if (
                not isinstance(source, dict)
                or not isinstance(run_id, str)
                or not run_id
                or run_id in baselines
                or item.get("file_path") != source.get("file_path")
                or (source.get("run_id") and source["run_id"] != run_id)
            ):
                return _report("failed", "result_scope_mismatch", "elt_execution")
            baselines[run_id] = source
        run_ids = list(baselines)
    else:
        if not run_ids:
            return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
        baselines = {run_ids[0]: baseline} if len(run_ids) == 1 else baseline.get("targets")
        items = output.get("results") if len(run_ids) > 1 else [output]
    if not isinstance(baselines, dict) or set(baselines) != set(run_ids):
        return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
    if (
        not isinstance(items, list)
        or len(items) != len(run_ids)
        or any(not isinstance(item, dict) for item in items)
        or (
            sources is None
            and len(run_ids) > 1
            and (
                output.get("batch") is not True
                or any(not isinstance(item.get("run_id"), str) for item in items)
                or {item.get("run_id") for item in items} != set(run_ids)
            )
        )
    ):
        return _report("failed", "result_scope_mismatch", "elt_execution")
    checks = []
    for item in items:
        run_id = (
            item["data"]["run_id"]
            if sources is not None
            else item["run_id"]
            if len(run_ids) > 1
            else run_ids[0]
        )
        target = baselines[run_id]
        if not isinstance(target, dict) or not target:
            return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
        if sources is None and (step.params.get("run_ids") or len(run_ids) > 1):
            revisions = step.params.get("preview_revisions")
            if not isinstance(revisions, dict) or revisions.get(run_id) != target.get(
                "preview_revision"
            ):
                return _report("failed", "result_preview_changed", "elt_execution")
        if (
            item.get("success") is not True
            or execution_result_error(item)
            or execution_result_requires_reconciliation(item)
        ):
            return _report("inconclusive", "result_receipt_unavailable", "elt_execution")
        report = _verify_execution_target(
            {**step.params, "run_id": run_id},
            target,
            item,
            context,
            receipt_sha256,
        )
        if report["status"] != "verified" or (sources is None and len(run_ids) == 1):
            return report
        checks.extend(report["checks"])
    if (
        output.get("success") is not True
        or execution_result_error(output)
        or execution_result_requires_reconciliation(output)
        or output.get("committed")
        is not (sum(check["evidence"]["executed_rows"] for check in checks) > 0)
        or output.get("done_count") != len(run_ids)
        or output.get("run_count") != len(run_ids)
        or output.get("pending_count") != 0
        or output.get("deferred_count") != 0
        or output.get("deferred") is not False
        or output.get("deferred_run_ids", []) != []
        or output.get("truncated", False) is not False
        or not isinstance(output.get("data"), dict)
        or output["data"].get("executed_rows")
        != sum(check["evidence"]["executed_rows"] for check in checks)
    ):
        return _report("failed", "result_business_state_mismatch", "elt_execution")
    return {"status": "verified", "code": "result_verified", "checks": checks}


def _verify_execution_target(
    params: dict[str, Any],
    baseline: dict[str, Any],
    output: dict[str, Any],
    context: dict[str, Any],
    receipt_sha256: str,
) -> dict[str, Any]:
    """Reuse the original single-target SQL proof after binding the whole durable receipt."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope
    from app.application.elt.auxiliary_verification import verify_auxiliary_receipts
    from app.application.elt.batch_continuation import (
        _legacy_completed_receipt,
        unchanged_source_upload,
    )
    from app.application.elt.errors import EltError
    from app.application.elt.row_verification import _execution_rows_current
    from app.application.elt.service_history import HistoryServiceMixin
    from app.domain.shared_services.tools_workflow_elt import _summary

    returned = output.get("data")
    if not isinstance(returned, dict) or returned.get("run_id") != params.get("run_id"):
        return _report("failed", "result_scope_mismatch", "elt_execution")
    try:
        with _transaction_read_scope(context, {"elt.execute"}, "elt") as (db, tenant):
            row = (
                db.query(EltRun)
                .filter_by(
                    id=params.get("run_id"),
                    tenant_id=tenant,
                    owner_user_id=int(context["user_id"]),
                )
                .one_or_none()
            )
            parsed_here = "file_path" in baseline and "plan_sha256" not in baseline
            if (
                row is None
                or any(
                    getattr(row, attr) != baseline.get(attr)
                    for attr in ("upload_id", "file_sha256")
                )
                or (not parsed_here and row.target_type != baseline.get("target_type"))
            ):
                return _report("failed", "result_scope_mismatch", "elt_execution")
            details = load_json(row.summary_json, {})
            confirmation = details.get(CONFIRMATION_KEY)
            if not isinstance(confirmation, dict):
                return _report("failed", "result_preview_changed", "elt_execution")
            revision = (
                confirmation.get("preview_revision")
                if parsed_here
                else baseline.get("preview_revision")
            )
            plan_sha256 = (
                confirmation.get("plan_sha256") if parsed_here else baseline.get("plan_sha256")
            )
            if (
                (not parsed_here and baseline.get("run_id") != row.id)
                or (baseline.get("run_id") and baseline["run_id"] != row.id)
                or (parsed_here and not (baseline.get("run_id") or baseline.get("origin")))
                or (
                    baseline.get("origin")
                    and details.get("chat_import_origin") != baseline["origin"]
                )
                or not isinstance(revision, str)
                or re.fullmatch(r"[0-9a-f]{64}", revision) is None
                or not isinstance(plan_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None
                or (details.get(REVIEW_KEY) or {}).get("revision") != revision
                or confirmation
                != {
                    "preview_revision": revision,
                    "valid_rows_only": params.get("valid_rows_only") is True,
                    "plan_sha256": plan_sha256,
                }
                or execution_plan_sha256(db, row) != plan_sha256
                or (
                    not parsed_here
                    and _execution_source_hash(db, row) != baseline.get("source_sha256")
                )
                or not unchanged_source_upload(db, row)
                or (
                    not parsed_here
                    and details.get("linked_from_shipment_preview") != baseline.get("parent_run_id")
                )
            ):
                return _report("failed", "result_preview_changed", "elt_execution")
            current = HistoryServiceMixin().run_dict(row)
            expected = _summary(current)
            readback = _execution_receipt_readback(
                db, row, valid_rows_only=params.get("valid_rows_only") is True
            )
            if (
                readback is None
                or (
                    row.target_type in {"shipment_records", "customer_products"}
                    and (
                        (
                            not parsed_here
                            and row.target_type == "customer_products"
                            and not isinstance(baseline.get("expected_rows"), dict)
                        )
                        or not _execution_rows_current(db, row, baseline.get("expected_rows"))
                    )
                )
                or output.get("committed") is not (row.executed_rows > 0)
                or (
                    not parsed_here
                    and (returned.get("customer_products") or {})
                    != baseline.get("companion_preview")
                )
                or any(
                    returned.get(name) != value
                    for name, value in expected.items()
                    if name != "customer_products"
                )
            ):
                return _report("failed", "result_business_state_mismatch", "elt_execution")
            if parsed_here and (
                returned.get("customer_products") or details.get("linked_customer_products_preview")
            ):
                from app.application.elt.preview_verification import _native_preview

                companion = returned.get("customer_products") or {}
                link = (details.get("linked_customer_products_preview") or {}).get("run_id")
                if not link or companion.get("run_id") != link:
                    return _report("failed", "result_companion_mismatch", "elt_execution")
                child = _native_preview(
                    db,
                    companion,
                    {"upload_id": row.upload_id, "sha256": row.file_sha256},
                    context,
                    row.owner_user_id,
                )
                if (
                    child["target_type"] != "customer_products"
                    or (child["draft"].get("linked_preview") or {}).get("parent_run_id") != row.id
                    or child["details"].get("linked_from_shipment_preview")
                    not in (None, "", row.id)
                ):
                    return _report("failed", "result_companion_mismatch", "elt_execution")
            if row.target_type == "customer_products" and details.get(
                "linked_from_shipment_preview"
            ):
                parent_id = details.get("linked_from_shipment_preview")
                parent = (
                    db.query(EltRun)
                    .filter_by(id=parent_id, tenant_id=tenant, owner_user_id=row.owner_user_id)
                    .one_or_none()
                )
                if (
                    parent is None
                    or parent.target_type != "shipment_records"
                    or (parent.upload_id, parent.file_sha256) != (row.upload_id, row.file_sha256)
                    or (
                        load_json(parent.summary_json, {}).get("linked_customer_products_preview")
                        or {}
                    ).get("run_id")
                    != row.id
                    or not _legacy_completed_receipt(db, parent)
                    or (
                        not parsed_here
                        and _execution_source_hash(db, parent)
                        != baseline.get("parent_source_sha256")
                    )
                    or not _execution_rows_current(db, parent)
                ):
                    return _report("failed", "result_companion_mismatch", "elt_execution")
            # For a file parsed in this dispatch, its original operation's plan
            # digest above binds the newly produced source features. The store
            # identity was still frozen before dispatch, alongside source+origin.
            auxiliary_baseline = (
                {
                    **baseline,
                    "preview_revision": revision,
                    "source_features_sha256": canonical_hash(
                        load_json(row.source_features_json, {})
                    ),
                }
                if parsed_here
                else baseline
            )
            auxiliary = verify_auxiliary_receipts(db, row, auxiliary_baseline, returned)
            if auxiliary is not None:
                return auxiliary
            return _report(
                "verified",
                "result_verified",
                "elt_execution",
                run_id=row.id,
                tenant_id=tenant,
                owner_id=row.owner_user_id,
                preview_revision=revision,
                plan_sha256=plan_sha256,
                file_sha256=row.file_sha256,
                executed_rows=row.executed_rows,
                readback=readback,
                receipt_sha256=receipt_sha256,
                scope="current_elt_business_rows",
                business_effect_verified=True,
            )
    except (EltError, ValueError):
        return _report("failed", "result_business_state_mismatch", "elt_execution")
    except LookupError:
        return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
    except PermissionError:
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
