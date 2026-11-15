"""Reviewed Excel template routes: intake."""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.get("/api/templates/reviewed-excel/reviews/{review_id}/intake-status")
def reviewed_excel_intake_status(review_id: str, request: Request, user=Depends(support._manage)):
    """Read the persisted preview state without starting another model request."""
    from app.application.elt.service import get_elt_service

    tenant, owner = support._identity(user)
    mod_id = support._authorize_intake(request, (tenant, owner))
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        review = app_gateway._run(db, review_id, tenant, owner)
        app_gateway._review_source_version(db, review, tenant, owner)
        state, _ = app_gateway._proposals(review)
        attempt = state.get("intake_attempt") or {}
        if attempt:
            return {"status": support._intake_attempt_status(attempt)}
        plan = state.get("intake_preview") or {}
        if not plan.get("run_id"):
            return {"status": "not_started"}
        if plan.get("mod_id") != mod_id:
            raise HTTPException(status_code=409, detail="业务空间已变化，请重新核对")
        support._authorize_intake(request, (tenant, owner), plan.get("target_type"))
        business = get_elt_service().get_run(db, run_id=plan["run_id"], owner_user_id=owner)
        return {
            "status": "created",
            "intake": {**plan, "business": business},
            "auto_ingest": app_gateway.load_json(review.receipt_json, {}).get("auto_ingest"),
        }

@router.post("/api/templates/reviewed-excel/reviews/{review_id}/intake-retry")
def reviewed_excel_intake_retry(review_id: str, request: Request, user=Depends(support._manage)):
    """Explicitly release an unknown attempt; never submit the next call here."""
    tenant, owner = support._identity(user)
    support._authorize_intake(request, (tenant, owner))
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        review = app_gateway._run(db, review_id, tenant, owner)
        app_gateway._review_source_version(db, review, tenant, owner)
        state, _ = app_gateway._proposals(review)
        attempt = state.get("intake_attempt") or {}
        if not attempt or support._intake_attempt_status(attempt) != "outcome_unknown":
            raise HTTPException(status_code=409, detail="预演仍在处理或状态已变化，请刷新")
        old = review.draft_json
        attempt["released_at"] = app_gateway.utcnow().isoformat()
        state.setdefault("intake_attempt_history", []).append(attempt)
        state.pop("intake_attempt", None)
        app_gateway._cas(db, review, old, expected_status=review.status, draft_json=app_gateway.dump_json(state))
    return {"success": True}

@router.post("/api/templates/reviewed-excel/intake-preview")
def reviewed_excel_intake_preview(
    request: Request,
    review_id: str = Form(..., max_length=36),
    proposal_version: str = Form(..., max_length=64),
    candidate_id: str = Form(..., max_length=64),
    selections: str = Form(..., max_length=500_000),
    name: str = Form(..., max_length=160),
    composer_note: str = Form("", max_length=4000),
    user=Depends(support._manage),
):
    """Stage the selected bytes and a reviewable business run; never write business/KB data."""
    from app.application.elt.auto_ingest_service import get_auto_ingest_service
    from app.application.elt.service import get_elt_service

    tenant, owner = support._identity(user)
    mod_id = support._authorize_intake(request, (tenant, owner))
    staged_path = None
    staged_committed = False
    preview_started = False
    model_started = False
    attempt_id = ""
    try:
        selected = json.loads(selections)
        if not isinstance(selected, list) or not name.strip():
            raise app_gateway.ReviewedExcelError("请选择模板并填写名称")
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            review = app_gateway._run(db, review_id, tenant, owner)
            app_gateway._review_source_version(db, review, tenant, owner)
            state, versions = app_gateway._proposals(review)
            if review.status not in {app_gateway._READY, app_gateway._SAVED} or versions[-1]["version"] != proposal_version:
                raise HTTPException(status_code=409, detail="审阅版本已变化，请重新选择候选")
            app_gateway._require_private_model(request, versions[-1], tenant, owner)
            candidate = next(
                (item for item in versions[-1]["candidates"] if item["id"] == candidate_id), None
            )
            if candidate is None:
                raise HTTPException(status_code=409, detail="候选不属于该审阅版本")
            if review.status == app_gateway._SAVED:
                confirmation = state.get("confirmation") or {}
                if (
                    confirmation.get("version"),
                    confirmation.get("candidate"),
                    confirmation.get("selected"),
                ) != (proposal_version, candidate_id, selected):
                    raise HTTPException(
                        status_code=409, detail="后台预演必须使用已保存的候选与清理范围"
                    )
            expected_status = review.status
            old_draft = review.draft_json
            key = app_gateway._intake_selection_key(
                review, proposal_version, candidate_id, selected, name, composer_note
            )
            previous = state.get("intake_preview") or {}
            if previous.get("selection_key") == key and previous.get("run_id"):
                if previous.get("mod_id") != mod_id:
                    raise HTTPException(status_code=409, detail="业务空间已变化，请重新核对")
                support._authorize_intake(request, (tenant, owner), previous.get("target_type"))
                business = get_elt_service().get_run(
                    db, run_id=previous["run_id"], owner_user_id=owner
                )
                return {
                    "success": True,
                    "intake": {**previous, "business": business},
                    "replayed": True,
                }
            if state.get("intake_attempt"):
                raise HTTPException(
                    status_code=409, detail="后台预演正在处理或结果待核对，请勿重复提交"
                )
            attempt_id = uuid4().hex
            state["intake_attempt"] = {
                "id": attempt_id,
                "selection_key": key,
                "status": "running",
                "started_at": app_gateway.utcnow().isoformat(),
                "max_duration_seconds": 1800,
            }
            claimed_draft = app_gateway.dump_json(state)
            app_gateway._cas(db, review, old_draft, expected_status=expected_status, draft_json=claimed_draft)
            old_draft = claimed_draft
            # The review upload is the template fragment. Database and knowledge
            # read the classification's archived original, which still has item rows.
            template_source = app_gateway._source(db, review, tenant, owner)
            archived = app_gateway._archived_original(db, review, tenant, owner)
            chosen = app_gateway.clean_workbook(template_source, review.file_sha256, selected)
            service = get_elt_service()
            upload = service.save_upload(
                db,
                owner_user_id=owner,
                file_name=f"{name.strip()}.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                stream=BytesIO(chosen),
            )
            # save_upload flushes a write; release SQLite's writer before any
            # potentially long workbook analysis or platform model calls.
            db.commit()
            staged_committed = True
            source = service._owned_upload(db, upload["upload_id"], owner)
            if source.tenant_id != tenant:
                raise HTTPException(status_code=403, detail="无权使用该入库预演")
            path = staged_path = Path(source.storage_path)
            from app.application.elt.auto_ingest_service import workbook_text
            from app.application.elt.candidate_table import (
                confirmed_business_table,
                dataset_from_business_rows,
                dataset_from_document_text,
                read_delivery_note_business,
            )
            from app.application.elt.llm_assist import (
                advise_business_import,
                audit_intake_calls,
                etl_llm_enabled,
            )

            original_text = workbook_text(archived)
            from app.application.elt.llm_session_provider import (
                bind_etl_llm_owner,
                reset_etl_llm_owner,
            )

            # Identity can already see the account model. Bind that same session
            # so these two lanes resolve it; each lane still has its own circuit.
            model_session = app_gateway.require_model_session(request, tenant, owner)
            owner_token = bind_etl_llm_owner(owner)

            def record_intake_call(call_id, lane, status):
                nonlocal old_draft
                calls = state["intake_attempt"].setdefault("model_calls", [])
                if status == "sent":
                    calls.append({"call_id": call_id, "lane": lane, "status": status})
                elif calls and calls[-1]["call_id"] == call_id:
                    calls[-1]["status"] = status
                else:
                    raise RuntimeError("intake model call ownership changed")
                updated = app_gateway.dump_json(state)
                app_gateway._cas(db, review, old_draft, expected_status=expected_status, draft_json=updated)
                old_draft = updated

            try:
                with app_gateway.bind_model_session(model_session), audit_intake_calls(record_intake_call):
                    model_started = True
                    business_llm = (
                        advise_business_import(original_text) if etl_llm_enabled() else None
                    )
                    ai_table = None
                    if (
                        business_llm is not None
                        and business_llm.used_llm
                        and not business_llm.degraded
                    ):
                        ai_table = dataset_from_business_rows(
                            list(business_llm.data.get("rows") or [])
                        )
                    delivery = read_delivery_note_business(archived)
                    if ai_table is not None:
                        chosen_table = ai_table
                        target_type = "shipment_records"
                        detection_reason = "database_llm"
                    elif delivery is not None:
                        chosen_table = delivery
                        target_type = "shipment_records"
                        detection_reason = "delivery_note_business_rows"
                    else:
                        confirmed = confirmed_business_table(path) or confirmed_business_table(
                            archived
                        )
                        if confirmed is None:
                            chosen_table = dataset_from_document_text(original_text, name.strip())
                            target_type = "knowledge"
                            detection_reason = "archived_document"
                        else:
                            chosen_table, target_type = confirmed
                            detection_reason = "candidate_headers"
                    from app.application.elt.auto_ingest_service import row_coverage

                    detection = {
                        "target_type": target_type,
                        "reason": detection_reason,
                        "confirmed": True,
                        "llm_lane": "database",
                        "used_llm": bool(business_llm and business_llm.used_llm),
                        "degraded": bool(business_llm and business_llm.degraded),
                        "llm_reason": (business_llm.degradation_code if business_llm else "")
                        or (
                            "no_business_rows"
                            if business_llm and business_llm.used_llm and ai_table is None
                            else ""
                        ),
                        "llm_units": int((business_llm.data or {}).get("units") or 0)
                        if business_llm
                        else 0,
                        "coverage": row_coverage(
                            original_text,
                            [
                                {"source_sheet": row.sheet, "source_row": row.row_number}
                                for row in ai_table.rows
                            ]
                            if ai_table is not None
                            else [],
                        ),
                    }
                    support._authorize_intake(request, (tenant, owner), target_type)
                    intake = get_auto_ingest_service()
                    knowledge = intake.knowledge_plan(
                        path=path,
                        file_name=name.strip(),
                        note=composer_note.strip(),
                        owner_user_id=owner,
                        owned_upload_user_id=source.owner_user_id,
                        source_text=original_text,
                    )
            finally:
                reset_etl_llm_owner(owner_token)
            preview_started = True
            business = service.create_preview(
                db,
                owner_user_id=owner,
                upload_id=upload["upload_id"],
                target_type=target_type,
                source_dataset=chosen_table,
            )
            plan = {
                "run_id": business["id"],
                "upload_id": upload["upload_id"],
                "selection_key": key,
                "source_sha256": review.file_sha256,
                "candidate_sha256": upload["sha256"],
                "target_type": target_type,
                "mod_id": mod_id,
                "name": name.strip(),
                "note": composer_note.strip(),
                "detection": detection,
                "knowledge": knowledge,
                "model_calls": state["intake_attempt"].get("model_calls", []),
            }
            support._recheck(request, (tenant, owner))
            app_gateway._review_source_version(db, review, tenant, owner)
            state["intake_preview"] = plan
            state.pop("intake_attempt", None)
            app_gateway._cas(
                db, review, old_draft, expected_status=expected_status, draft_json=app_gateway.dump_json(state)
            )
            attempt_id = ""
            return {"success": True, "intake": {**plan, "business": business}}
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 400), detail=app_gateway.public_excel_error(exc)
        ) from None
    finally:
        if staged_path is not None and not preview_started and not staged_committed:
            app_gateway.discard_stored_upload(staged_path)
        if attempt_id:
            try:
                with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                    review = app_gateway._run(db, review_id, tenant, owner)
                    current = app_gateway.load_json(review.draft_json, {})
                    attempt = current.get("intake_attempt") or {}
                    if attempt.get("id") == attempt_id:
                        old = review.draft_json
                        if model_started or preview_started:
                            attempt["status"] = "outcome_unknown"
                        else:
                            current.pop("intake_attempt", None)
                        app_gateway._cas(
                            db,
                            review,
                            old,
                            expected_status=review.status,
                            draft_json=app_gateway.dump_json(current),
                        )
            except app_gateway.BOUNDARY_ERRORS:
                logger.exception("Could not reconcile intake preview claim")
