"""Reviewed Excel template routes: candidates."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.get(
    "/api/templates/reviewed-excel/classifications/{classification_id}/candidate-result/{version}/{slice_index}"
)
def reviewed_excel_candidate_result(
    classification_id: str, version: str, slice_index: int, user=Depends(support._read)
):
    """Read a completed candidate after a client timeout without another model call."""
    from app.application.reviewed_excel_audit import is_live

    tenant, owner = support._identity(user)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        classification = app_gateway._classification_run(db, classification_id, tenant, owner)
        state = app_gateway.load_json(classification.draft_json, {})
        versions = state.get("versions") or []
        if not versions or versions[-1].get("version") != version:
            raise HTTPException(status_code=409, detail="分类版本已变化，请刷新")
        matched = []
        pending = []
        for key, claim in (state.get("template_candidate_requests") or {}).items():
            if (
                claim.get("version") == version
                and claim.get("slice_index") == slice_index
                and claim.get("state") != "completed"
            ):
                pending.append(
                    "retryable"
                    if claim.get("state") == "retryable"
                    else "pending"
                    if is_live(key)
                    else "unknown"
                )
            if claim.get("state") != "completed" or not claim.get("review_id"):
                continue
            review = app_gateway._run(db, claim["review_id"], tenant, owner)
            scope = app_gateway.load_json(review.summary_json, {}).get("selected_region") or {}
            if (
                scope.get("classification_id") == classification_id
                and scope.get("version") == version
                and scope.get("auto_slice_index") == slice_index
            ):
                matched.append(review.id)
        if len(matched) > 1:
            raise HTTPException(status_code=409, detail="存在多份候选结果，请人工核对")
        if not matched:
            return {
                "status": "unknown"
                if "unknown" in pending
                else "retryable"
                if "retryable" in pending
                else "pending"
            }
        return {
            "status": "complete",
            "review": app_gateway._stored_candidate_response(db, matched[0], tenant, owner),
        }


@router.post(
    "/api/templates/reviewed-excel/classifications/{classification_id}/template-families/{version}"
)
def reviewed_excel_template_families(
    classification_id: str, version: str, request: Request, user=Depends(support._manage)
):
    """Record model-proposed template reuse without merging source documents."""
    from app.application.reviewed_excel_audit import call_key
    from app.application.reviewed_excel_template_families import suggest_template_families

    tenant, owner = support._identity(user)
    model_session = app_gateway.require_model_session(request, tenant, owner)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        run = app_gateway._classification_run(db, classification_id, tenant, owner)
        state = app_gateway.load_json(run.draft_json, {})
        versions = state.get("versions") or []
        if not versions or versions[-1].get("version") != version:
            raise HTTPException(status_code=409, detail="分类版本已变化，请刷新")
        saved = state.get("template_families") or {}
        if saved.get("version") == version and saved.get("status") == "complete":
            return {"status": "complete", "families": saved["families"], "replayed": True}
        if saved.get("version") == version and saved.get("status") in {
            "running",
            "outcome_unknown",
        }:
            raise HTTPException(
                status_code=409, detail="模板复用分析正在处理或结果待核对，请勿重复提交"
            )
        old = run.draft_json
        call_id = uuid4().hex
        state["template_families"] = {"version": version, "status": "running", "call_id": call_id}
        app_gateway._classification_cas(db, run, old, state)
        sent = False
        answered = False

        def mark_sent():
            nonlocal sent
            sent = True

        def mark_answered():
            nonlocal answered
            answered = True

        def settle_family(result):
            # A user can open a candidate while this model call is running.
            # Merge only our own claim into the newest classification state.
            for _ in range(3):
                db.rollback()
                db.expire_all()
                current = app_gateway._classification_run(db, classification_id, tenant, owner)
                old_draft = current.draft_json
                latest = app_gateway.load_json(old_draft, {})
                claim = latest.get("template_families") or {}
                versions = latest.get("versions") or []
                if (
                    not versions
                    or versions[-1].get("version") != version
                    or claim.get("call_id") != call_id
                ):
                    raise HTTPException(status_code=409, detail="分类或模板复用任务已变化，请刷新")
                latest["template_families"] = result
                try:
                    app_gateway._classification_cas(db, current, old_draft, latest)
                    return
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
            raise HTTPException(status_code=409, detail="分类正在更新，请稍后核对模板复用结果")

        try:
            slices = support._cached_slice_metadata(
                (tenant, owner, classification_id, version, run.file_sha256)
            )
            if slices is None:
                slices, _coverage, _rows = support._auto_slices(
                    db, classification_id, version, tenant, owner
                )
            source_body = app_gateway._source(db, run, tenant, owner)
            review = app_gateway.inspect_workbook(source_body)
            with app_gateway.bind_model_session(model_session), call_key(call_id):
                families = suggest_template_families(
                    slices,
                    review["cells"],
                    owner_id=owner,
                    source_body=source_body,
                    on_dispatch=mark_sent,
                    on_answer=mark_answered,
                )
            support._recheck(request, (tenant, owner))
            settle_family(
                {"version": version, "status": "complete", "call_id": call_id, "families": families}
            )
            return {"status": "complete", "families": families}
        except app_gateway.BOUNDARY_ERRORS as exc:
            try:
                settle_family(
                    {
                        "version": version,
                        "call_id": call_id,
                        "status": "outcome_unknown" if sent and not answered else "failed",
                        "reason": app_gateway.public_excel_error(exc),
                    }
                )
            except app_gateway.BOUNDARY_ERRORS:
                logger.exception("Could not persist template-family outcome")
            raise


@router.get(
    "/api/templates/reviewed-excel/classifications/{classification_id}/auto-slices/{version}"
)
def reviewed_excel_auto_slices(
    classification_id: str, version: str, manifest: bool = False, user=Depends(support._read)
):
    tenant, owner = support._identity(user)
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            slices, coverage, rows = support._auto_slices(
                db,
                classification_id,
                version,
                tenant,
                owner,
                with_rows=True,
                metadata_only=manifest,
            )
        return {
            "classification_id": classification_id,
            "version": version,
            "coverage": coverage,
            "row_dispositions": rows,
            "slices": [
                {
                    **{key: value for key, value in item.items() if key != "workbook"},
                    "index": index,
                    "display_name": item.get("display_name") or Path(item["filename"]).stem,
                    "type_label": item.get("type_label") or "",
                    **(
                        {"sha256": hashlib.sha256(item["workbook"]).hexdigest()}
                        if "workbook" in item
                        else {}
                    ),
                    **(
                        {
                            "selection_id": hashlib.sha256(
                                app_gateway.dump_json(
                                    {
                                        "classification": classification_id,
                                        "version": version,
                                        "source": item["source_sha256"],
                                        "index": index,
                                        "fragments": item["fragments"],
                                    }
                                ).encode()
                            ).hexdigest()
                        }
                        if manifest
                        else {}
                    ),
                }
                for index, item in enumerate(slices)
            ],
        }
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None


@router.get(
    "/api/templates/reviewed-excel/classifications/{classification_id}/auto-slices/{version}/{index}"
)
def reviewed_excel_auto_slice_download(
    classification_id: str, version: str, index: int, user=Depends(support._read)
):
    tenant, owner = support._identity(user)
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            slices, _coverage, _rows = support._auto_slices(db, classification_id, version, tenant, owner)
        if index < 0 or index >= len(slices):
            raise HTTPException(status_code=404, detail="切片不存在")
        return Response(
            slices[index]["workbook"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(slices[index]['filename'])}"
            },
        )
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None
