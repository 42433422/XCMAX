"""Bind native ELT confirmations to independently read committed business rows."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.verification_elt import (
    _database,
    _owned_run,
    capture_preview_inputs,
)
from app.application.elt.errors import EltError
from app.application.elt.preview_confirmation import (
    CONFIRMATION_KEY,
    REVIEW_KEY,
    execution_plan_sha256,
    verify_preview,
)
from app.application.elt.service_history import HistoryServiceMixin
from app.application.elt.service_support import load_json
from app.db.models.elt import EltRunRow, EltUpload
from app.domain.task_lifecycle.results import execution_result_requires_reconciliation
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _freeze_native(db, native, source):
    details = load_json(native.summary_json, {})
    revision = (details.get(REVIEW_KEY) or {}).get("revision")
    if native.status == "preview_ready":
        verify_preview(db, native, revision)
    return {
        **source,
        "run_id": native.id,
        "upload_id": native.upload_id,
        "sha256": native.file_sha256,
        "target_type": native.target_type,
        "preview_revision": revision,
        "plan_sha256": execution_plan_sha256(db, native),
    }


def capture_execution_inputs(run, step, context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.elt_checkpoint_recovery import checkpoint_step
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.elt.chat_recall import _REQUIRED_IDENTITY
    from app.domain.shared_services.tools_workflow_elt import (
        _MAX_BATCH_IMPORTS,
        _owned_upload,
        _split_paths,
        _split_run_ids,
        durable_elt_checkpoint_ids,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    context = {
        **context,
        "run_id": run.run_id,
        "step_id": step.step_id,
        **task_execution_context(run, step),
    }
    try:
        owner = _bound_actor(context).id
        ids = _split_run_ids(step.params.get("run_ids")) or _split_run_ids(
            step.params.get("run_id")
        )
        paths = list(dict.fromkeys(_split_paths(step.params.get("file_paths"))))
        if (ids and paths) or not (ids or paths) or len(ids or paths) > _MAX_BATCH_IMPORTS:
            return {}
        with _database(context) as db:
            sources: list[dict[str, Any]] = []
            if ids:
                for identity in ids:
                    native = _owned_run(db, identity, context, owner)
                    if native is None:
                        return {}
                    sources.append(_freeze_native(db, native, {}))
            else:
                checkpoints = {}
                inputs: list[dict[str, Any]]
                checkpoint = checkpoint_step(run)
                if checkpoint is not None and checkpoint is step:
                    # The approved worker requires one slot per exact upload ID;
                    # chat imports instead use the producer's source dedupe.
                    uploads = [_owned_upload(path, context) for path in paths]
                    if any(
                        path != upload.get("id")
                        for path, upload in zip(paths, uploads, strict=True)
                    ):
                        return {}
                    inputs = [
                        {"file_path": path, "upload_id": upload["id"], "sha256": upload["sha256"]}
                        for path, upload in zip(paths, uploads, strict=True)
                    ]
                    checkpoints = durable_elt_checkpoint_ids(run.run_id, checkpoint.step_id, paths)
                else:
                    inputs = capture_preview_inputs({"file_paths": paths}, context)
                if not inputs:
                    return {}
                origin = {key: str(context.get(key) or "").strip() for key in _REQUIRED_IDENTITY}
                for source in inputs:
                    checkpoint_id = checkpoints.get(source["upload_id"])
                    if checkpoint_id:
                        source["run_id"] = checkpoint_id
                        native = _owned_run(db, checkpoint_id, context, owner)
                        if native is not None:
                            source = _freeze_native(db, native, source)
                    elif all(origin.values()):
                        source["origin"] = {
                            **origin,
                            "mod_id": str(
                                context.get("mod_id") or context.get("active_mod_id") or ""
                            ),
                        }
                    else:
                        return {}
                    sources.append(source)
            return {"sources": sources}
    except (EltError,) + RECOVERABLE_ERRORS:
        return {}


def _read_native(db, source, summary, params, context, owner):
    from app.application.agent_orchestrator.verification_elt_dynamic import verify_dynamic_effects
    from app.domain.shared_services.tools_workflow_elt import _summary

    native = _owned_run(db, summary.get("run_id"), context, owner)
    if native is None or (source.get("run_id") and native.id != source["run_id"]):
        raise ValueError("native execution identity changed")
    upload = (
        db.query(EltUpload)
        .filter_by(id=native.upload_id, tenant_id=native.tenant_id, owner_user_id=owner)
        .first()
    )
    details = load_json(native.summary_json, {})
    confirmation = details.get(CONFIRMATION_KEY) or {}
    review = details.get(REVIEW_KEY) or {}
    receipt = load_json(native.receipt_json, {})
    if (
        upload is None
        or native.upload_id != source.get("upload_id")
        or upload.sha256 != native.file_sha256
        or native.file_sha256 != source.get("sha256")
        or (source.get("target_type") and native.target_type != source["target_type"])
        or (source.get("origin") and details.get("chat_import_origin") != source["origin"])
        or native.status != "completed"
        or not (native.confirmed_at and native.executed_at)
        or native.operation_token
        or native.operation_kind
        or native.rollback_status
        or native.rolled_back_at
        or not isinstance(receipt, dict)
        or execution_result_requires_reconciliation(receipt)
        or execution_result_requires_reconciliation(details)
        or receipt.get("run_id") != native.id
        or receipt.get("target_type") != native.target_type
        or receipt.get("executed_rows") != native.executed_rows
        or confirmation.get("valid_rows_only") is not (params.get("valid_rows_only") is True)
        or not review.get("revision")
        or confirmation.get("preview_revision") != review["revision"]
        or (
            source.get("preview_revision")
            and confirmation.get("preview_revision") != source["preview_revision"]
        )
        or (source.get("plan_sha256") and confirmation.get("plan_sha256") != source["plan_sha256"])
        or not confirmation.get("plan_sha256")
        or confirmation["plan_sha256"] != execution_plan_sha256(db, native)
        or (native.error_rows and params.get("valid_rows_only") is not True)
    ):
        raise ValueError("native confirmation or execution changed")
    data = HistoryServiceMixin().run_dict(native)
    if any(
        summary.get(key) != value
        for key, value in _summary(data).items()
        if key != "customer_products"
    ):
        raise ValueError("native result differs from returned summary")
    rows = (
        db.query(EltRunRow)
        .filter_by(run_id=native.id, tenant_id=native.tenant_id, owner_user_id=owner)
        .order_by(EltRunRow.id)
        .all()
    )
    expected = [row for row in rows if row.final_action in {"new", "update"}]
    if (
        len(rows) != native.total_rows
        or any(row.execution_status != "success" for row in expected)
        or any(row.execution_status not in (None, "") for row in rows if row not in expected)
        or receipt.get("partial")
        is not bool(native.error_rows and params.get("valid_rows_only") is True)
    ):
        raise ValueError("native row ledger incomplete")
    if native.target_type == "dynamic_table":
        evidence = verify_dynamic_effects(db, native, rows, receipt)
    else:
        from app.application.agent_orchestrator.verification_elt_targets import (
            ROW_TARGETS,
            verify_row_effects,
        )

        if native.target_type not in ROW_TARGETS:
            raise LookupError("native business readback unavailable")
        if len(expected) != native.executed_rows:
            raise ValueError("native row execution count differs")
        evidence = verify_row_effects(db, native, rows)
    companion = summary.get("customer_products") or {}
    link = (details.get("linked_customer_products_preview") or {}).get("run_id")
    if link or companion:
        from app.application.agent_orchestrator.verification_elt import _native_preview

        if not link or companion.get("run_id") != link:
            raise ValueError("linked preview changed")
        child = _native_preview(
            db, companion, {k: source[k] for k in ("upload_id", "sha256")}, context, owner
        )
        if (child["draft"].get("linked_preview") or {}).get("parent_run_id") != native.id:
            raise ValueError("linked preview parent changed")
        evidence["companion_preview_only"] = child["id"]
    return {
        "run_id": native.id,
        "upload_id": native.upload_id,
        "plan_sha256": confirmation["plan_sha256"],
        "executed_rows": native.executed_rows,
        **evidence,
    }


def verify_elt_execution(call, output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_readback import _report
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    acceptance = (call.metadata.get("verification_contract") or {}).get(
        "elt_execution_inputs"
    ) or {}
    sources = acceptance.get("sources")
    if not isinstance(sources, list) or not sources:
        return _report("inconclusive", "result_verifier_unavailable", "elt_native_execution")
    items = output.get("results") if output.get("batch") is True else [output]
    if not isinstance(items, list) or len(items) != len(sources):
        return _report("failed", "elt_execution_scope_mismatch", "elt_native_execution")
    try:
        owner = _bound_actor(context).id
        evidence, seen = [], set()
        with _database(context) as db:
            for source, item in zip(sources, items, strict=True):
                if (
                    not isinstance(item, dict)
                    or item.get("success") is not True
                    or item.get("deferred")
                    or item.get("requires_user_decision")
                ):
                    raise ValueError("native execution is unfinished")
                summary = item.get("data") or {}
                if not isinstance(summary, dict) or summary.get("run_id") in seen:
                    raise ValueError("native receipt is duplicated")
                seen.add(summary.get("run_id"))
                evidence.append(_read_native(db, source, summary, call.params, context, owner))
        if output.get("batch") is True and (
            output.get("run_count") != len(items)
            or output.get("done_count") != len(items)
            or (output.get("data") or {}).get("executed_rows")
            != sum(item["executed_rows"] for item in evidence)
            or output.get("deferred_count")
            or output.get("pending_count")
            or output.get("truncated")
        ):
            raise ValueError("native execution batch is incomplete")
    except LookupError:
        return _report("inconclusive", "result_verifier_unavailable", "elt_native_execution")
    except (EltError, ValueError):
        return _report("failed", "elt_execution_evidence_mismatch", "elt_native_execution")
    return _report(
        "verified",
        "verified_elt_business_effects",
        "elt_native_execution",
        imports=evidence,
        business_effect_verified=True,
    )
