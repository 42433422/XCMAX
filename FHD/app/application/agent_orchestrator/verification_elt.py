"""Read a completed ELT preview without confirming or executing its business write."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any


def verify_elt_preview(step, output, context) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.elt.errors import EltConflict
    from app.application.elt.preview_confirmation import preview_revision, verify_preview
    from app.application.elt.service_history import HistoryServiceMixin
    from app.db.models.elt import EltRun
    from app.db.session import get_db
    from app.domain.shared_services.tools_workflow_elt import (
        _owned_upload,
        _pending_mappings,
        _summary,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.auth.business_scope_gate import check_owned_business_permission
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    source = "elt_preview_snapshot"
    actor = _bound_actor(context)
    tenant = check_owned_business_permission(actor, "elt.execute")
    if str(tenant) != str(context.get("tenant_id") or ""):
        return _report("failed", "result_scope_mismatch", "task_scope")
    data = output.get("data")
    if not isinstance(data, dict) or output.get("preview") is not True:
        return _report("failed", "result_elt_preview_mismatch", source)
    # Batch and linked-target previews have separate receipts. Never infer their
    # acceptance from the first file or from a caller's aggregate success flag.
    if step.params.get("file_paths"):
        return _report("inconclusive", "result_elt_preview_scope_unavailable", source)
    requested = str(step.params.get("run_id") or "")
    # The producer's Mod scope ended with its worker. Restore the original
    # binding, including an empty Mod, before selecting any evidence database.
    with ExitStack() as scope:
        token = set_request_active_mod_id("")
        scope.callback(reset_request_active_mod_id, token)
        scope.enter_context(agent_mod_execution_scope(context.get("_mod_authorization")))
        scope.enter_context(tenant_scope(tenant))
        db = scope.enter_context(get_db())
        row = (
            db.query(EltRun)
            .filter(
                EltRun.id == str(data.get("run_id") or ""),
                EltRun.tenant_id == tenant,
                EltRun.owner_user_id == actor.id,
            )
            .first()
        )
        if row is None:
            return _report("inconclusive", "result_elt_preview_unavailable", source)
        if requested:
            if requested != row.id:
                return _report("failed", "result_elt_preview_mismatch", source)
        else:
            upload = _owned_upload(str(step.params.get("file_path") or ""), context)
            if (upload.get("id"), upload.get("sha256")) != (row.upload_id, row.file_sha256):
                return _report("failed", "result_elt_preview_source_mismatch", source)
        revision = preview_revision(row)
        if not revision or row.executed_rows or row.executed_at is not None:
            return _report("inconclusive", "result_elt_preview_not_ready", source)
        actual = HistoryServiceMixin().run_dict(row)
        summary = _summary(actual)
        if (
            summary.get("customer_products")
            or (actual.get("draft") or {}).get("linked_preview")
            or (actual.get("details") or {}).get("linked_from_shipment_preview")
        ):
            return _report("inconclusive", "result_elt_preview_scope_unavailable", source)
        if any(
            data.get(key) != summary[key]
            for key in (
                "run_id",
                "target_type",
                "status",
                "preview_revision",
                "total_rows",
                "new_rows",
                "update_rows",
                "skip_rows",
                "error_rows",
                "executed_rows",
            )
        ):
            return _report("failed", "result_elt_preview_mismatch", source)
        try:
            # Recompute the original source/row/mapping/target snapshot. This
            # read port does not publish a revision, grant consent or start work.
            verify_preview(db, row, data.get("preview_revision"))
        except EltConflict:
            return _report("failed", "result_elt_preview_changed", source)
        if requested:
            # _review_existing reports this original preview only. It cannot
            # propose new execution parameters or manufacture a decision pause.
            if (
                data.get("preview_only") is not True
                or data.get("requires_user_confirmation") is not True
                or output.get("requires_user_decision", False) is not False
                or output.get("resume_params") not in (None, {})
            ):
                return _report("failed", "result_elt_preview_decision_mismatch", source)
        else:
            errors = bool(row.error_rows) and step.params.get("valid_rows_only") is not True
            mappings = bool(_pending_mappings(actual))
            executable = not errors and (
                not mappings or step.params.get("accept_suggested") is True
            )
            resume = (
                {"valid_rows_only": True}
                if errors
                else ({"accept_suggested": True} if mappings and not executable else {})
            )
            if (
                data.get("executable") is not executable
                or output.get("requires_user_decision") is not (not executable)
                or output.get("resume_params", {}) != resume
                or (not executable and not output.get("question"))
            ):
                return _report("failed", "result_elt_preview_decision_mismatch", source)
        return _report(
            "verified",
            "result_verified",
            source,
            run_id=row.id,
            upload_id=row.upload_id,
            tenant_id=str(tenant),
            owner_user_id=str(actor.id),
            preview_revision=revision,
            verification_scope="preview_snapshot",
            business_effect_verified=False,
        )
