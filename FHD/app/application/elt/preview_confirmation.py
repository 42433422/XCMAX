"""Bind explicit execution approval to the exact completed preview being reviewed."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any

from sqlalchemy import true
from sqlalchemy.orm import Session

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
    run.summary_json = dump_json(details)


def verify_execution(db: Session, run: EltRun, *, valid_rows_only: bool) -> dict[str, Any] | None:
    confirmation = load_json(run.summary_json, {}).get(CONFIRMATION_KEY)
    if (
        not isinstance(confirmation, dict)
        or confirmation.get("valid_rows_only") is not valid_rows_only
    ):
        raise _changed()
    return verify_preview(db, run, confirmation.get("preview_revision"))


def verify_agent_preview(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Verify only the owned, unchanged preview; this never confirms a business write."""
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.session import get_db
    from app.domain.shared_services.auth_service import get_auth_service
    from app.domain.shared_services.tools_workflow_elt import (
        _owned_upload,
        _pending_mappings,
        _summary,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    actor = _bound_actor(context)
    if "elt.execute" not in get_auth_service().get_user_permissions(actor):
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
    returned = output.get("data")
    if not isinstance(returned, dict) or not isinstance(returned.get("run_id"), str):
        return _report("inconclusive", "result_receipt_missing", "elt_preview")
    tenant = str(context.get("tenant_id") or "")
    if not tenant.isdecimal() or int(tenant) <= 0:
        return _report("failed", "result_scope_mismatch", "task_scope")
    token = set_request_active_mod_id("")
    try:
        with (
            agent_mod_execution_scope(context.get("_mod_authorization")),
            tenant_scope(int(tenant)),
        ):
            upload = _owned_upload(str(step.params.get("file_path") or ""), context)
            with get_db() as db:
                row = (
                    db.query(EltRun)
                    .filter_by(id=returned["run_id"], owner_user_id=actor.id, tenant_id=int(tenant))
                    .one_or_none()
                )
                if row is None or not (
                    (upload and row.upload_id == upload["id"])
                    or (not step.params.get("file_path") and step.params.get("run_id") == row.id)
                ):
                    return _report("failed", "result_scope_mismatch", "elt_preview")
                revision = preview_revision(row)
                if (
                    not revision
                    or row.executed_rows
                    or row.confirmed_at is not None
                    or load_json(row.receipt_json, {})
                    or db.query(EltRunRow.id)
                    .filter(
                        EltRunRow.run_id == row.id,
                        EltRunRow.execution_status.is_not(None),
                    )
                    .first()
                    is not None
                ):
                    return _report("inconclusive", "result_preview_not_current", "elt_preview")
                verify_preview(db, row, returned.get("preview_revision"))
                current = HistoryServiceMixin().run_dict(row)
                expected = _summary(current)
                if expected.get("customer_products"):
                    return _report(
                        "inconclusive", "result_companion_verification_required", "elt_preview"
                    )
                if any(
                    returned.get(key) != expected[key]
                    for key in (
                        "run_id",
                        "preview_revision",
                        "target_type",
                        "status",
                        "total_rows",
                        "new_rows",
                        "update_rows",
                        "skip_rows",
                        "error_rows",
                        "executed_rows",
                    )
                ):
                    return _report("failed", "result_preview_mismatch", "elt_preview")
                blocked_by_errors = (
                    bool(row.error_rows) and step.params.get("valid_rows_only") is not True
                )
                pending_mappings = _pending_mappings(current)
                executable = not (
                    blocked_by_errors
                    or (pending_mappings and step.params.get("accept_suggested") is not True)
                )
                resume_params = {}
                if blocked_by_errors:
                    resume_params["valid_rows_only"] = True
                elif not executable and pending_mappings:
                    resume_params["accept_suggested"] = True
                if (
                    output.get("preview") is not True
                    or returned.get("executable") is not executable
                    or output.get("requires_user_decision") is not (not executable)
                    or output.get("resume_params", {}) != resume_params
                    or any(value is not True for value in output.get("resume_params", {}).values())
                ):
                    return _report("failed", "result_preview_mismatch", "elt_preview")
                return _report(
                    "verified",
                    "result_preview_verified",
                    "elt_preview",
                    run_id=row.id,
                    upload_id=row.upload_id,
                    tenant_id=tenant,
                    owner_id=str(actor.id),
                    preview_revision=revision,
                    scope="preview_only",
                    business_effect_verified=False,
                    executable=executable,
                    resume_params=resume_params,
                )
    except EltConflict:
        return _report("failed", "result_preview_changed", "elt_preview")
    finally:
        reset_request_active_mod_id(token)


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


def capture_agent_execution(step: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Freeze every original target before dispatch, retaining single-run contracts."""
    run_ids = _execution_run_ids(step.params)
    if not run_ids:
        return {}
    if len(run_ids) == 1:
        return _capture_execution_target(run_ids[0], context)
    return {"targets": {run_id: _capture_execution_target(run_id, context) for run_id in run_ids}}


def _capture_execution_target(run_id: str, context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope
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
                or row.target_type not in {"shipment_records", "customer_products"}
                or not revision
            ):
                return {}
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
                "source_sha256": _execution_source_hash(db, row),
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


def _execution_rows_current(
    db: Session, run: EltRun, expected_rows: dict[str, Any] | None = None
) -> bool:
    """Compare original committed row images using the existing target snapshot readers."""
    from app.application.elt.targets.customer_product_support import (
        customer_image_matches,
        customer_values,
    )
    from app.application.elt.targets.customer_products import CustomerProductsAdapter
    from app.application.elt.targets.helpers import (
        assert_created_row_unchanged,
        assert_snapshot_unchanged,
        decimal_or_none,
        decimal_or_zero,
        integer_or_zero,
        optional_text,
    )
    from app.application.elt.targets.orders import ShipmentAdapter
    from app.application.elt.targets.products import ProductAdapter
    from app.db.models import Product, PurchaseUnit, ShipmentRecord

    rows = db.query(EltRunRow).filter_by(
        run_id=run.id,
        tenant_id=run.tenant_id,
        owner_user_id=run.owner_user_id,
        execution_status="success",
    )
    for row in rows.yield_per(500):
        after = load_json(row.after_json, {})
        if not isinstance(after, dict) or not after or not isinstance(row.match_ref, str):
            return False
        if run.target_type == "shipment_records":
            record = (
                db.query(ShipmentRecord)
                .filter_by(id=row.match_ref, tenant_id=run.tenant_id)
                .one_or_none()
            )
            if (
                record is None
                or after.get("id") != record.id
                or not set(record.to_dict()) <= set(after)
            ):
                return False
            if not ShipmentAdapter._belongs_to_current_run(record, run.id):
                return False
            assert_snapshot_unchanged(record, after, "发货记录")
            data = load_json(row.normalized_json, {})
            tin_spec = decimal_or_none(data.get("tin_spec"))
            assert_snapshot_unchanged(
                record,
                {
                    "purchase_unit": str(data.get("purchase_unit") or ""),
                    "product_name": str(data.get("product_name") or ""),
                    "model_number": optional_text(data.get("model_number")),
                    "quantity_kg": float(decimal_or_zero(data.get("quantity_kg"))),
                    "quantity_tins": integer_or_zero(data.get("quantity_tins")),
                    "tin_spec": float(tin_spec) if tin_spec is not None else None,
                    # SQLAlchemy applies ShipmentRecord's zero defaults when
                    # the worker supplies an absent optional money value.
                    "unit_price": decimal_or_zero(data.get("unit_price")),
                    "amount": decimal_or_zero(data.get("amount")),
                },
                "已审批出货内容",
            )
            if (
                not db.query(PurchaseUnit.id)
                .filter_by(tenant_id=run.tenant_id, unit_name=record.purchase_unit, is_active=True)
                .first()
            ):
                return False
        else:
            customer_id, product_id = CustomerProductsAdapter._parse_match_ref(row.match_ref)
            customer = (
                db.query(PurchaseUnit)
                .filter_by(id=customer_id, tenant_id=run.tenant_id)
                .one_or_none()
            )
            product = (
                db.query(Product).filter_by(id=product_id, tenant_id=run.tenant_id).one_or_none()
            )
            customer_after, product_after = after.get("customer"), after.get("product")
            reviewed = (expected_rows or {}).get(str(row.id)) or {}
            expected_customer, expected_product = reviewed.get("customer"), reviewed.get("product")
            if (
                customer is None
                or product is None
                or not customer.is_active
                or not isinstance(customer_after, dict)
                or not isinstance(product_after, dict)
                or not set(customer_values(customer)) <= set(customer_after)
                or not {field.key for field in ProductAdapter.fields} <= set(product_after)
                or not customer_image_matches(customer, customer_after)
                or not isinstance(expected_customer, dict)
                or not isinstance(expected_product, dict)
                or not set(customer_values(customer)) <= set(expected_customer)
                or not {field.key for field in ProductAdapter.fields} <= set(expected_product)
                or not customer_image_matches(customer, expected_customer)
                or customer.unit_name != product.unit
                or after.get("relationship")
                != {"customer_name": customer.unit_name, "product_unit": product.unit}
            ):
                return False
            assert_created_row_unchanged(product, product_after, ProductAdapter.fields, "关联产品")
            assert_created_row_unchanged(
                product, expected_product, ProductAdapter.fields, "已审批产品内容"
            )
    return True


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
    run_ids = _execution_run_ids(step.params)
    if not run_ids:
        return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
    baselines = {run_ids[0]: baseline} if len(run_ids) == 1 else baseline.get("targets")
    if not isinstance(baselines, dict) or set(baselines) != set(run_ids):
        return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
    items = output.get("results") if len(run_ids) > 1 else [output]
    if (
        not isinstance(items, list)
        or len(items) != len(run_ids)
        or any(not isinstance(item, dict) for item in items)
        or (
            len(run_ids) > 1
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
        run_id = item["run_id"] if len(run_ids) > 1 else run_ids[0]
        target = baselines[run_id]
        if not isinstance(target, dict) or not target:
            return _report("inconclusive", "result_verifier_unavailable", "elt_execution")
        if step.params.get("run_ids") or len(run_ids) > 1:
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
        if report["status"] != "verified" or len(run_ids) == 1:
            return report
        checks.extend(report["checks"])
    if (
        output.get("success") is not True
        or execution_result_error(output)
        or execution_result_requires_reconciliation(output)
        or output.get("committed") is not True
        or output.get("done_count") != len(run_ids)
        or output.get("run_count") != len(run_ids)
        or output.get("pending_count") != 0
        or output.get("deferred_count") != 0
        or output.get("deferred") is not False
        or output.get("deferred_run_ids") != []
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
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope
    from app.application.elt.batch_continuation import (
        _legacy_completed_receipt,
        unchanged_source_upload,
    )
    from app.application.elt.errors import EltError
    from app.application.elt.service_history import HistoryServiceMixin
    from app.domain.shared_services.tools_workflow_elt import _summary

    returned = output.get("data")
    if not isinstance(returned, dict) or returned.get("run_id") != params.get("run_id"):
        return _report("failed", "result_scope_mismatch", "elt_execution")
    if returned.get("knowledge") or returned.get("template"):
        return _report("inconclusive", "result_auxiliary_verification_required", "elt_execution")
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
            if row is None or any(
                getattr(row, attr) != baseline.get(attr)
                for attr in ("upload_id", "file_sha256", "target_type")
            ):
                return _report("failed", "result_scope_mismatch", "elt_execution")
            details = load_json(row.summary_json, {})
            revision = baseline["preview_revision"]
            if (
                baseline.get("run_id") != row.id
                or (details.get(REVIEW_KEY) or {}).get("revision") != revision
                or details.get(CONFIRMATION_KEY)
                != {
                    "preview_revision": revision,
                    "valid_rows_only": params.get("valid_rows_only") is True,
                }
                or _execution_source_hash(db, row) != baseline["source_sha256"]
                or not unchanged_source_upload(db, row)
                or details.get("linked_from_shipment_preview") != baseline.get("parent_run_id")
            ):
                return _report("failed", "result_preview_changed", "elt_execution")
            current = HistoryServiceMixin().run_dict(row)
            expected = _summary(current)
            if (
                not _legacy_completed_receipt(db, row)
                or row.executed_rows <= 0
                or not _execution_rows_current(db, row, baseline.get("expected_rows"))
                or output.get("committed") is not True
                or (returned.get("customer_products") or {}) != baseline.get("companion_preview")
                or any(
                    returned.get(name) != value
                    for name, value in expected.items()
                    if name != "customer_products"
                )
            ):
                return _report("failed", "result_business_state_mismatch", "elt_execution")
            if row.target_type == "customer_products":
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
                    or _execution_source_hash(db, parent) != baseline.get("parent_source_sha256")
                    or not _execution_rows_current(db, parent)
                ):
                    return _report("failed", "result_companion_mismatch", "elt_execution")
            return _report(
                "verified",
                "result_verified",
                "elt_execution",
                run_id=row.id,
                tenant_id=tenant,
                owner_id=row.owner_user_id,
                preview_revision=revision,
                executed_rows=row.executed_rows,
                receipt_sha256=receipt_sha256,
                scope="current_elt_business_rows",
                business_effect_verified=True,
            )
    except EltError:
        return _report("failed", "result_business_state_mismatch", "elt_execution")
    except PermissionError:
        return _report("inconclusive", "result_read_permission_unavailable", "task_scope")
