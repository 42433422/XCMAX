"""Read native, owned ELT preview manifests without admitting a business write."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.application.elt.errors import EltError
from app.application.elt.preview_confirmation import verify_preview
from app.application.elt.service_history import HistoryServiceMixin
from app.application.elt.service_support import load_json
from app.db.models.elt import EltRun, EltRunRow
from app.utils.operational_errors import RECOVERABLE_ERRORS


@contextmanager
def _database(context):
    from app.application.agent_orchestrator.verification_transactions import _transaction_read_scope

    with _transaction_read_scope(context, {"elt.execute"}, "elt") as (db, _tenant):
        yield db


def _owned_run(db, run_id, context, owner):
    return (
        db.query(EltRun)
        .filter_by(id=run_id, tenant_id=int(context["tenant_id"]), owner_user_id=owner)
        .first()
    )


def capture_preview_inputs(
    params: dict[str, Any], context: dict[str, Any], *, preserve_uploads: bool = False
) -> list[dict[str, Any]]:
    """Freeze source identity before dispatch; a returned run ID cannot choose it."""
    from app.domain.shared_services.tools_workflow_elt import (
        _MAX_BATCH_IMPORTS,
        _expand_directory_paths,
        _owned_upload,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    try:
        owner = _bound_actor(context).id
        with _database(context) as db:
            if params.get("run_id"):
                native = _owned_run(db, params["run_id"], context, owner)
                return (
                    [
                        {
                            "run_id": native.id,
                            "upload_id": native.upload_id,
                            "sha256": native.file_sha256,
                        }
                    ]
                    if native is not None
                    else []
                )
            paths = params.get("file_paths") or [params.get("file_path")]
            if (
                not isinstance(paths, list)
                or not paths
                or not all(isinstance(p, str) and p for p in paths)
            ):
                return []
            paths, unresolved = _expand_directory_paths(list(dict.fromkeys(paths)), context)
            if unresolved or len(paths) > _MAX_BATCH_IMPORTS:
                return []
            inputs, seen = [], set()
            for path in paths:
                upload = _owned_upload(path, context)
                if not upload:
                    return []
                identity = (upload["file_name"], upload["suffix"], upload["sha256"])
                if preserve_uploads or identity not in seen:
                    inputs.append(
                        {"file_path": path, "upload_id": upload["id"], "sha256": upload["sha256"]}
                    )
                    seen.add(identity)
            return inputs
    except (EltError,) + RECOVERABLE_ERRORS:
        return []


def _native_preview(db, summary, source, context, owner):
    from app.domain.shared_services.tools_workflow_elt import _summary

    if not isinstance(summary, dict):
        raise ValueError("missing native preview")
    native = _owned_run(db, summary.get("run_id"), context, owner)
    if (
        native is None
        or native.upload_id != source.get("upload_id")
        or native.file_sha256 != source.get("sha256")
        or (source.get("run_id") and native.id != source["run_id"])
        or native.status != "preview_ready"
        or native.operation_kind
        or native.operation_token
        or native.rollback_status
        or native.executed_at
        or native.executed_rows
        or load_json(native.receipt_json, {})
    ):
        raise ValueError("preview scope or phase changed")
    verify_preview(db, native, summary.get("preview_revision"))
    rows = db.query(EltRunRow.execution_status).filter_by(
        run_id=native.id, tenant_id=native.tenant_id, owner_user_id=owner
    )
    # after_json already contains the proposed image during native preview.
    # Its content is bound by verify_preview; only execution_status is a write fact.
    if any(status for (status,) in rows.yield_per(500)):
        raise ValueError("preview has an execution receipt")
    data = HistoryServiceMixin().run_dict(native)
    expected = _summary(data)
    if any(
        summary.get(key) != value for key, value in expected.items() if key != "customer_products"
    ):
        raise ValueError("preview summary changed")
    return data


def read_preview_evidence(call, output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_readback import _report
    from app.domain.shared_services.tools_workflow_elt import _pending_mappings
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    sources = (call.metadata.get("verification_contract") or {}).get("elt_preview_inputs")
    if not isinstance(sources, list) or not sources:
        return _report("inconclusive", "elt_preview_source_unavailable", "elt_preview_manifest")
    items = output.get("results") if output.get("batch") is True else [output]
    if not isinstance(items, list) or len(items) != len(sources):
        return _report("failed", "elt_preview_scope_mismatch", "elt_preview_manifest")
    evidence, decisions = [], []
    expected_resume: dict[str, bool] = {}
    try:
        owner = _bound_actor(context).id
        with _database(context) as db:
            for item, source in zip(items, sources, strict=True):
                if (
                    not isinstance(item, dict)
                    or item.get("success") is not True
                    or item.get("preview") is not True
                ):
                    raise ValueError("missing preview receipt")
                if output.get("batch") is True and item.get("file_path") != source.get("file_path"):
                    raise ValueError("preview input changed")
                summary = item.get("data") or {}
                data = _native_preview(db, summary, source, context, owner)
                if data["draft"].get("linked_preview") or data["details"].get(
                    "linked_from_shipment_preview"
                ):
                    raise ValueError("linked child requires its bound parent preview")
                link = data["details"].get("linked_customer_products_preview") or {}
                companion = summary.get("customer_products") or {}
                if link:
                    if companion.get("run_id") != link.get("run_id"):
                        raise ValueError("linked preview changed")
                    child = _native_preview(
                        db,
                        companion,
                        {k: v for k, v in source.items() if k != "run_id"},
                        context,
                        owner,
                    )
                    if (
                        child["target_type"] != "customer_products"
                        or (child["draft"].get("linked_preview") or {}).get("parent_run_id")
                        != data["id"]
                        or child["details"].get("linked_from_shipment_preview")
                        not in (None, "", data["id"])
                    ):
                        raise ValueError("linked preview owner changed")
                elif companion:
                    raise ValueError("unexpected linked preview")
                blocked_errors = bool(data["summary"]["error"]) and (
                    call.params.get("valid_rows_only") is not True
                )
                blocked_mappings = bool(_pending_mappings(data)) and (
                    call.params.get("accept_suggested") is not True
                )
                decision = not source.get("run_id") and (blocked_errors or blocked_mappings)
                resume = (
                    {}
                    if not decision
                    else {"valid_rows_only": True}
                    if blocked_errors
                    else {"accept_suggested": True}
                )
                if item.get("requires_user_decision", False) is not decision or (
                    not source.get("run_id") and summary.get("executable") is not (not decision)
                ):
                    raise ValueError("preview decision differs from native blockers")
                if source.get("run_id"):
                    if (
                        summary.get("preview_only") is not True
                        or summary.get("requires_user_confirmation") is not True
                        or item.get("resume_params") not in (None, {})
                    ):
                        raise ValueError("existing preview cannot propose execution parameters")
                elif (
                    item.get("resume_params", {}) != resume
                    or not isinstance(item.get("resume_params", {}), dict)
                    or any(value is not True for value in item.get("resume_params", {}).values())
                ):
                    raise ValueError("preview continuation differs from native blockers")
                if decision and (
                    not isinstance(item.get("question"), str) or not item["question"].strip()
                ):
                    raise ValueError("preview decision has no confirmation question")
                expected_resume.update(resume)
                decisions.append(decision)
                evidence.append(
                    {
                        "run_id": data["id"],
                        "upload_id": data["upload_id"],
                        "preview_revision": data["preview_revision"],
                    }
                )
        if output.get("batch") is True:
            ids = [] if any(decisions) else [item["run_id"] for item in evidence]
            expected = {
                "run_id": ",".join(ids),
                "run_ids": ids,
                "file_count": len(items),
                "ready_count": len(items),
                "needs_decision_count": sum(decisions),
                "executable": not any(decisions),
            }
            if (
                output.get("data") != expected
                or output.get("run_ids") != ids
                or output.get("requires_user_decision", False) is not any(decisions)
                or output.get("resume_params", {}) != expected_resume
                or not isinstance(output.get("resume_params", {}), dict)
                or any(value is not True for value in output.get("resume_params", {}).values())
                or (
                    any(decisions)
                    and (
                        not isinstance(output.get("question"), str)
                        or not output["question"].strip()
                    )
                )
                or output.get("deferred_count")
                or output.get("truncated")
            ):
                raise ValueError("batch preview incomplete")
    except (EltError, ValueError):
        return _report("failed", "result_preview_changed", "elt_preview")
    return _report(
        "verified",
        "result_preview_verified",
        "elt_preview",
        previews=evidence,
        business_effect_verified=False,
        scope="preview_only",
        executable=not any(decisions),
        resume_params=expected_resume,
    )
