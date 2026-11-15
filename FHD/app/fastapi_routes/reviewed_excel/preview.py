"""Reviewed Excel template routes: preview."""

from __future__ import annotations

import hashlib
import json
import logging
from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.post("/api/templates/reviewed-excel/preview")
async def reviewed_excel_preview(
    request: Request,
    file: UploadFile = File(...),
    expected_actor: str = Form(..., max_length=80),
    classification_id: str = Form("", max_length=36),
    classification_version: str = Form("", max_length=64),
    region_sheet: str = Form("", max_length=200),
    region_range: str = Form("", max_length=60),
    auto_slice_index: int = Form(-1),
    print_area_mode: str = Form("source", max_length=16),
    user=Depends(support._manage),
):
    support._expected_actor(expected_actor, user)
    tenant, owner = support._identity(user)
    model_session = app_gateway.require_model_session(request, tenant, owner)
    if not classification_id or not classification_version:
        raise HTTPException(status_code=409, detail="请先建立文件分类记录，再生成候选")
    from app.application.reviewed_excel_audit import (
        call_key,
        is_live,
        live_claims,
        mark_live,
        owner_stamp,
        recovery_action,
    )

    _dock_cm = support._docking_channel()
    _dock_cm.__enter__()
    _live_cm = live_claims()
    _live_cm.__enter__()
    try:
        request.state.elt_stage = "read_workbook"
        body = await support._body(file)
        review = await run_in_threadpool(app_gateway.inspect_workbook, body)
        source_restrictions = list(review.get("usage_restrictions", []))
        selected_region: dict[str, Any] | None = None
        if auto_slice_index >= 0:
            if not classification_id or not classification_version or region_sheet or region_range:
                raise app_gateway.ReviewedExcelError("自动切片选择无效")

            def select_slice():
                with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                    classification = app_gateway._classification_run(db, classification_id, tenant, owner)
                    if classification.file_sha256 != review["sha256"]:
                        raise HTTPException(status_code=409, detail="分类来源已改变，请重新选择")
                    archive_version_id = app_gateway.load_json(classification.summary_json, {}).get(
                        "archive_version_id"
                    )
                    if not archive_version_id:
                        raise app_gateway.ReviewedExcelError("自动切片须先归档原件")
                    slices, _coverage, _rows = support._auto_slices(
                        db,
                        classification_id,
                        classification_version,
                        tenant,
                        owner,
                        only_index=auto_slice_index,
                    )
                    if not slices:
                        raise HTTPException(status_code=404, detail="切片不存在")
                    selected = slices[0]
                    if selected["basis"] != "model_group":
                        raise app_gateway.ReviewedExcelError("模型尚未确定此单据的完整关系")
                    return selected, archive_version_id, classification.file_sha256

            selected_slice, archive_version_id, source_sha256 = await run_in_threadpool(
                select_slice
            )
            body = selected_slice["workbook"]
            review = await run_in_threadpool(app_gateway.inspect_workbook, body)
            fragments = selected_slice["fragments"]
            selected_region = {
                "classification_id": classification_id,
                "version": classification_version,
                "selection_basis": "model_group",
                "auto_slice_index": auto_slice_index,
                "range_objects_receipt": selected_slice["range_objects_receipt"],
                "archive_version_id": archive_version_id,
                "source_sha256": source_sha256,
                "fragments": fragments,
                "print_area_mode": "source",
                "derived_sha256": review["sha256"],
            }
        elif classification_id:
            with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                classification = app_gateway._classification_run(db, classification_id, tenant, owner)
                app_gateway._source(db, classification, tenant, owner)
                state = app_gateway.load_json(classification.draft_json, {})
                versions = state.get("versions", [])
                latest = versions[-1] if versions else {}
                if (
                    classification.file_sha256 != review["sha256"]
                    or latest.get("version") != classification_version
                    or not latest.get("confirmed")
                    or not any(
                        sheet.get("sheet") == region_sheet
                        and any(
                            region.get("range") == region_range
                            for region in sheet.get("regions", [])
                        )
                        for sheet in latest.get("sheets", [])
                    )
                ):
                    raise HTTPException(status_code=409, detail="分类来源或区域已变化，请重新确认")
                selected_region = {
                    "classification_id": classification_id,
                    "version": classification_version,
                    "sheet": region_sheet,
                    "range": region_range,
                }
                selected_region["archive_version_id"] = app_gateway.load_json(
                    classification.summary_json, {}
                ).get("archive_version_id")
                selected_region["logical_documents"] = [
                    group
                    for group in latest.get("logical_documents", [])
                    if {"sheet": region_sheet, "range": region_range} in group["fragments"]
                ]
                fragments = (
                    selected_region["logical_documents"][0]["fragments"]
                    if selected_region["logical_documents"]
                    else [{"sheet": region_sheet, "range": region_range}]
                )
                from openpyxl.utils.cell import (
                    column_index_from_string,
                    coordinate_from_string,
                )

                def inside_fragment(ref):
                    col, row = coordinate_from_string(ref["cell"])
                    col = column_index_from_string(col)
                    return any(
                        ref["sheet"] == part["sheet"] and c1 <= col <= c2 and r1 <= row <= r2
                        for part in fragments
                        for c1, r1, c2, r2 in [app_gateway.bounded_range(part["range"])]
                    )

                for sheet in latest["sheets"]:
                    for region in sheet["regions"]:
                        if {"sheet": sheet["sheet"], "range": region["range"]} in fragments:
                            if any(
                                not inside_fragment(ref) for ref in region.get("dependencies", [])
                            ):
                                raise app_gateway.ReviewedExcelError(
                                    "所选文档依赖外部说明或标题，暂不能保证保真提取"
                                )
                selected_region["source_sha256"] = review["sha256"]
                selected_region["fragments"] = fragments
                selected_region["source_print_areas"] = [
                    area
                    for area in review["read_only_print_areas"]
                    if area["sheet"] == region_sheet
                ]
                if not selected_region["source_print_areas"]:
                    original_print = next(
                        sheet["print_area"]
                        for sheet in review["sheet_overview"]
                        if sheet["sheet"] == region_sheet
                    )
                    if original_print:
                        selected_region["source_print_areas"] = [
                            {"sheet": region_sheet, "value": original_print}
                        ]
                selected_region["print_area_mode"] = print_area_mode
                object_receipt: dict = {}
                request.state.elt_stage = "extract_document"
                body = app_gateway.derive_document_workbook(
                    body, fragments, print_area_mode=print_area_mode, object_receipt=object_receipt
                )
                selected_region["range_objects_receipt"] = object_receipt
                review = app_gateway.inspect_workbook(body)
                selected_region["derived_print_area"] = next(
                    sheet["print_area"]
                    for sheet in review["sheet_overview"]
                    if sheet["sheet"] == region_sheet
                )
                selected_region["derived_sha256"] = review["sha256"]
        request.state.elt_stage = "generate_candidates"
        proposal = app_gateway.make_proposals(review)
        versions = [proposal]
        candidate_key = ""
        if classification_id:
            candidate_key = hashlib.sha256(
                app_gateway.dump_json(
                    {
                        "version": classification_version,
                        "source": review["sha256"],
                        "slice": auto_slice_index,
                        "sheet": region_sheet,
                        "range": region_range,
                    }
                ).encode()
            ).hexdigest()
            with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                classification = app_gateway._classification_run(db, classification_id, tenant, owner)
                old = classification.draft_json
                state = app_gateway.load_json(old, {})
                if (
                    not state.get("versions")
                    or state["versions"][-1].get("version") != classification_version
                ):
                    raise HTTPException(status_code=409, detail="分类版本已变化，请重新处理")
                claims = state.setdefault("template_candidate_requests", {})
                existing = claims.get(candidate_key)
                claim = None
                if existing:
                    if existing.get("state") == "completed" and existing.get("review_id"):
                        return app_gateway._stored_candidate_response(db, existing["review_id"], tenant, owner)
                    if is_live(candidate_key):
                        return JSONResponse(
                            status_code=202, content={"phase": "inflight", "retry_after": 30}
                        )
                    if existing.get("state") == "retryable":
                        action = "resend"
                    else:
                        lookup = await support._lookup_market_call(
                            existing.get("call_id"), owner, model_session
                        )
                        action = recovery_action(existing, lookup)
                    if action == "wait":
                        return JSONResponse(
                            status_code=202, content={"phase": "inflight", "retry_after": 30}
                        )
                    if action == "locked":
                        error = app_gateway._model_processing_failure(
                            app_gateway.ReviewedExcelError(
                                "上次候选请求结果未知且市场无法确认；不会重复发送。"
                                "如需放弃并重发，须由用户明确授权（可能重复计费）"
                            )
                        )
                        error.status_code = 409
                        raise error
                    claim = {**existing, "state": "sent", "owner": owner_stamp()}
                    claim["attempts"] = int(existing.get("attempts") or 1) + 1
                if len(claims) >= 200:
                    raise HTTPException(
                        status_code=409, detail="本文件候选请求已达上限，请先核对已有结果"
                    )
                claims[candidate_key] = claim or {
                    "state": "sent",
                    "call_id": uuid4().hex,
                    "owner": owner_stamp(),
                    "attempts": 1,
                }
                claims[candidate_key].update(
                    {"version": classification_version, "slice_index": auto_slice_index}
                )
                candidate_call_id = claims[candidate_key]["call_id"]
                candidate_attempt = int(claims[candidate_key].get("attempts") or 1)
                completed_batches = claims[candidate_key].get("batches") or {}
                support._recheck(request, (tenant, owner))
                app_gateway._classification_cas(db, classification, old, state)
                mark_live(candidate_key)
        else:
            candidate_attempt = 1
            completed_batches = {}

        def persist_candidate_batch(index, digest, batch_status, result):
            # Independent sessions and CAS preserve concurrent batch results
            # and unrelated changes to the same classification.
            for _ in range(5):
                with app_gateway.tenant_scope(tenant), app_gateway.get_db() as checkpoint_db:
                    classification = app_gateway._classification_run(
                        checkpoint_db, classification_id, tenant, owner
                    )
                    old = classification.draft_json
                    current = app_gateway.load_json(old, {})
                    versions_now = current.get("versions") or []
                    claim = (current.get("template_candidate_requests") or {}).get(
                        candidate_key
                    ) or {}
                    if (
                        not versions_now
                        or versions_now[-1].get("version") != classification_version
                        or claim.get("call_id") != candidate_call_id
                        or claim.get("state") != "sent"
                    ):
                        raise HTTPException(status_code=409, detail="候选任务已变化，请核对状态")
                    entry = {"digest": digest, "status": batch_status}
                    if result is not None:
                        entry["result"] = result
                    claim.setdefault("batches", {})[str(index)] = entry
                    try:
                        app_gateway._classification_cas(checkpoint_db, classification, old, current)
                        return
                    except HTTPException as exc:
                        if exc.status_code != 409:
                            raise
            raise HTTPException(status_code=409, detail="候选批次状态写入冲突，请核对")

        try:
            import asyncio

            from app.application.reviewed_excel_audit import ModelRequestNotSent

            request.state.elt_stage = "model_candidates"
            with (
                app_gateway.tenant_scope(tenant),
                app_gateway.bind_model_session(model_session),
                call_key(candidate_call_id),
            ):
                for retry in range(3):
                    try:
                        proposal = await run_in_threadpool(
                            app_gateway.refine_proposal,
                            review,
                            proposal["version"],
                            "生成三个清理候选，保留固定说明和公式",
                            owner_id=owner,
                            initial=True,
                            before_model_call=lambda: support._recheck(request, (tenant, owner)),
                            cached_batches=completed_batches,
                            batch_checkpoint=persist_candidate_batch if candidate_key else None,
                            batch_attempt=candidate_attempt,
                        )
                        break
                    except ModelRequestNotSent:
                        if retry == 2 or not candidate_key:
                            raise
                        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as retry_db:
                            classification = app_gateway._classification_run(
                                retry_db, classification_id, tenant, owner
                            )
                            old = classification.draft_json
                            state = app_gateway.load_json(old, {})
                            claim = (state.get("template_candidate_requests") or {}).get(
                                candidate_key
                            ) or {}
                            batches = claim.get("batches") or {}
                            statuses = [item.get("status") for item in batches.values()]
                            if (
                                claim.get("call_id") != candidate_call_id
                                or claim.get("state") != "sent"
                                or "not_sent" not in statuses
                                or any(
                                    status not in {"complete", "not_sent"} for status in statuses
                                )
                            ):
                                raise
                            candidate_attempt += 1
                            claim["attempts"] = candidate_attempt
                            completed_batches = batches
                            app_gateway._classification_cas(retry_db, classification, old, state)
                        await asyncio.sleep(retry + 1)
            versions.append(proposal)
        except ValueError as exc:
            # Only a call that may have been answered without our seeing it keeps the claim.
            unknown = app_gateway.model_call_outcome(exc) == "unknown"
            with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                try:
                    app_gateway._update_candidate_claim(
                        db, classification_id, candidate_key, tenant, owner, unknown=unknown
                    )
                except HTTPException:
                    # Claim already moved; still surface the model failure.
                    pass
            raise app_gateway._model_processing_failure(exc) from None
        proposal["model"]["authorization"] = app_gateway.template_model_authorization(
            model_session,
            tenant,
            owner,
            review["sha256"],
            selected_region or {},
        )
        request.state.elt_stage = "render_candidates"
        try:
            for version in versions:
                await run_in_threadpool(support._build_candidate_previews, body, review, version)
        except app_gateway.BOUNDARY_ERRORS:
            # The model has answered; rendering failed before a review or a
            # business write exists. Preserve the call record and allow the
            # user to explicitly regenerate a candidate.
            with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                classification = app_gateway._classification_run(db, classification_id, tenant, owner)
                old = classification.draft_json
                state = app_gateway.load_json(old, {})
                claims = state.get("template_candidate_requests") or {}
                claim = claims.get(candidate_key) or {}
                if claim.get("call_id") == candidate_call_id and claim.get("state") == "sent":
                    state.setdefault("candidate_render_failures", []).append(
                        {**claim, "candidate_key": candidate_key, "state": "answered_render_failed"}
                    )
                    claims.pop(candidate_key)
                    app_gateway._classification_cas(db, classification, old, state)
            raise
        support._recheck(request, (tenant, owner))
        request.state.elt_stage = "save_preview"
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            if selected_region and selected_region.get("derived_sha256"):
                current = app_gateway._classification_run(
                    db, selected_region["classification_id"], tenant, owner
                )
                app_gateway._source(db, current, tenant, owner)
                source_restrictions.extend(app_gateway._usage_restrictions(db, current, tenant, owner))
                current_versions = app_gateway.load_json(current.draft_json, {}).get("versions", [])
                if (
                    not current_versions
                    or current_versions[-1].get("version") != selected_region["version"]
                    or (
                        current_versions[-1].get("model_status") != "returned"
                        if selected_region.get("selection_basis") == "model_group"
                        else not current_versions[-1].get("confirmed")
                    )
                ):
                    raise HTTPException(status_code=409, detail="文档分类已变化，请重新生成候选")
            review["usage_restrictions"] = list(dict.fromkeys(source_restrictions))
            upload = app_gateway.UploadServiceMixin().save_upload(
                db,
                owner_user_id=owner,
                file_name=file.filename or "review.xlsx",
                content_type=file.content_type,
                stream=BytesIO(body),
            )
            run = app_gateway.EltRun(
                id=app_gateway.new_id(),
                tenant_id=tenant,
                owner_user_id=owner,
                upload_id=upload["upload_id"],
                target_type="template_review",
                status=app_gateway._READY,
                stage=app_gateway._READY,
                file_sha256=review["sha256"],
                draft_json=app_gateway.dump_json({"versions": versions}),
                summary_json=app_gateway.dump_json(
                    {
                        "kind": "reviewed_excel",
                        "selected_region": selected_region,
                        "usage_restrictions": review["usage_restrictions"],
                    }
                ),
            )
            db.add(run)
            if candidate_key:
                app_gateway._update_candidate_claim(db, classification_id, candidate_key, tenant, owner, run.id)
            else:
                db.commit()
            review_id = run.id
        return {
            "success": True,
            **review,
            "review_id": review_id,
            "proposal": proposal,
            "versions": versions,
            "selected_region": selected_region,
        }
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None
    finally:
        _live_cm.__exit__(None, None, None)
        _dock_cm.__exit__(None, None, None)

@router.get("/api/templates/reviewed-excel/reviews/{review_id}")
def reviewed_excel_history(review_id: str, user=Depends(support._read)):
    tenant, owner = support._identity(user)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        run = app_gateway._run(db, review_id, tenant, owner)
        state, versions = app_gateway._proposals(run)
        return {
            "success": True,
            "review_id": run.id,
            "source_sha256": run.file_sha256,
            "selected_region": app_gateway.load_json(run.summary_json, {}).get("selected_region"),
            "usage_restrictions": app_gateway._usage_restrictions(db, run, tenant, owner),
            "status": run.status,
            "versions": versions,
            "confirmation": state.get("confirmation"),
            "receipt": app_gateway.load_json(run.receipt_json, {}),
            "revision_parent": app_gateway.load_json(run.summary_json, {}).get("revision_parent"),
        }

@router.get(
    "/api/templates/reviewed-excel/reviews/{review_id}/versions/{version}/candidates/{candidate_id}/download"
)
def reviewed_excel_candidate_download(
    review_id: str, version: str, candidate_id: str, user=Depends(support._read)
):
    tenant, owner = support._identity(user)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        run = app_gateway._run(db, review_id, tenant, owner)
        app_gateway._review_source_version(db, run, tenant, owner)
        _state, versions = app_gateway._proposals(run)
        proposal = next((item for item in versions if item.get("version") == version), None)
        candidate = next(
            (
                item
                for item in (proposal or {}).get("candidates", [])
                if item.get("id") == candidate_id
            ),
            None,
        )
        if proposal is None or not candidate or not proposal.get("result_previews"):
            raise HTTPException(status_code=404, detail="候选模板不存在")
        body = app_gateway._source(db, run, tenant, owner)
        try:
            cleaned = app_gateway.clean_workbook(body, run.file_sha256, candidate["clear"])
        except app_gateway.ReviewedExcelError as exc:
            raise HTTPException(status_code=409, detail=app_gateway.public_excel_error(exc)) from None
    return Response(
        cleaned,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="candidate.xlsx"'},
    )

@router.post("/api/templates/reviewed-excel/refine")
async def reviewed_excel_refine(
    request: Request,
    review_id: str = Form(..., max_length=36),
    parent_version: str = Form(..., max_length=64),
    feedback: str = Form(..., max_length=1000),
    current: str = Form("[]", max_length=100_000),
    user=Depends(support._manage),
):
    tenant, owner = support._identity(user)
    model_session = app_gateway.require_model_session(request, tenant, owner)
    with support._docking_channel():
        return await _reviewed_excel_refine_body(
            request, review_id, parent_version, feedback, current, tenant, owner, model_session
        )

async def _reviewed_excel_refine_body(
    request, review_id, parent_version, feedback, current, tenant, owner, model_session
):
    try:
        current_cells = json.loads(current)
        if not isinstance(current_cells, list):
            raise app_gateway.ReviewedExcelError("当前候选无效")
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._run(db, review_id, tenant, owner)
            app_gateway._review_source_version(db, run, tenant, owner)
            state, versions = app_gateway._proposals(run)
            if run.status == app_gateway._SAVED and versions[-1]["version"] == parent_version:
                body = app_gateway._source(db, run, tenant, owner)
                app_gateway.clean_workbook(body, run.file_sha256, current_cells)
                support._recheck(request, (tenant, owner))
                run = app_gateway._fork_saved_review(
                    db, run, versions[-1], feedback, current_cells, tenant, owner
                )
                state, versions = app_gateway._proposals(run)
                if run.status in {app_gateway._READY, app_gateway._SAVED} and versions[-1]["version"] != parent_version:
                    return app_gateway._refinement_response(run, versions[-1], replayed=True)
            if run.status == app_gateway._MODEL_PENDING:
                error = app_gateway._model_processing_failure(
                    app_gateway.ReviewedExcelError("上次模型处理仍在进行或结果未知，请先核对状态；不会重复发送")
                )
                error.status_code = 409
                raise error
            if run.status != app_gateway._READY or versions[-1]["version"] != parent_version:
                raise HTTPException(status_code=409, detail="审阅版本已过期，请刷新")
            if len(versions) >= 50:
                raise app_gateway.ReviewedExcelError("提案版本已达上限")
            old_draft = run.draft_json
            body = app_gateway._source(db, run, tenant, owner)
            review = app_gateway.inspect_workbook(body)
            app_gateway.clean_workbook(body, run.file_sha256, current_cells)
            support._recheck(request, (tenant, owner))
            app_gateway._cas(db, run, old_draft, status=app_gateway._MODEL_PENDING, stage="model_candidates")
            try:
                with app_gateway.bind_model_session(model_session):
                    proposal = await run_in_threadpool(
                        app_gateway.refine_proposal,
                        review,
                        parent_version,
                        feedback,
                        owner_id=owner,
                        current=current_cells,
                        initial=True,
                        before_model_call=lambda: support._recheck(request, (tenant, owner)),
                    )
            except ValueError as exc:
                if app_gateway.model_call_outcome(exc) != "unknown":
                    app_gateway._cas(
                        db,
                        run,
                        old_draft,
                        expected_status=app_gateway._MODEL_PENDING,
                        status=app_gateway._READY,
                        stage=app_gateway._READY,
                    )
                raise app_gateway._model_processing_failure(exc) from None
            source_scope = app_gateway.load_json(run.summary_json, {}).get("selected_region") or {}
            proposal["model"]["authorization"] = app_gateway.template_model_authorization(
                model_session,
                tenant,
                owner,
                run.file_sha256,
                source_scope,
                feedback=True,
            )
            support._build_candidate_previews(body, review, proposal)
            support._recheck(request, (tenant, owner))
            versions.append(proposal)
            state["versions"] = versions
            app_gateway._cas(
                db,
                run,
                old_draft,
                expected_status=app_gateway._MODEL_PENDING,
                status=app_gateway._READY,
                stage=app_gateway._READY,
                draft_json=app_gateway.dump_json(state),
            )
            response = app_gateway._refinement_response(run, proposal)
        return response
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None
