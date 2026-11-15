"""Reviewed Excel template routes: analysis."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.fastapi_routes.reviewed_excel import analysis_body, app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/analyze")
async def reviewed_excel_classification_analyze(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    auto_group: bool = Form(False),
    user=Depends(support._manage),
):
    request.state.elt_stage = "analyze"
    tenant, owner = support._identity(user)
    model_session = app_gateway.require_model_session(request, tenant, owner)
    from app.application.reviewed_excel_audit import live_claims

    with support._docking_channel(), live_claims():
        return await analysis_body._reviewed_excel_classification_analyze_body(
            classification_id, request, version, auto_group, tenant, owner, model_session
        )

@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/recover-answer")
def reviewed_excel_recover_answer(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    user=Depends(support._manage),
):
    """Revalidate the saved failed reply once; never dispatch another model request."""
    from app.application.reviewed_excel_budget import validate_checkpoint_budget
    from app.application.reviewed_excel_plan import restore_checkpoint_review
    from app.application.reviewed_excel_saved_response import saved_classification_answer

    tenant, owner = support._identity(user)
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._classification_run(db, classification_id, tenant, owner)
            old = run.draft_json
            state = app_gateway.load_json(old, {})
            versions = state.get("versions") or []
            checkpoint = state.get("analysis_checkpoint") or {}
            if (
                not versions
                or versions[-1].get("version") != version
                or checkpoint.get("version") != version
            ):
                raise app_gateway.ReviewedExcelError("分类版本已改变，请刷新后核对")
            history = state.get("saved_response_revalidations") or []
            records = state.get("model_audit") or []
            latest = records[-1] if records else {}
            if (
                latest.get("request_sha256")
                and history
                and history[-1].get("request_sha256") == latest.get("request_sha256")
            ):
                return {
                    "phase": checkpoint.get("phase"),
                    "checkpoint": support._checkpoint_view(checkpoint),
                    "replayed": True,
                    "can_slice": history[-1].get("can_slice"),
                }
            if checkpoint.get("phase") != "failed" or not (checkpoint.get("repair") or {}).get(
                "exhausted"
            ):
                raise app_gateway.ReviewedExcelError("当前分类没有可恢复的已失败回答")
            if checkpoint.get("source_sha256") != run.file_sha256 or not checkpoint.get(
                "auto_group"
            ):
                raise app_gateway.ReviewedExcelError("原件或分类模式已改变，不能恢复")
            validate_checkpoint_budget(checkpoint)
            body = app_gateway._source(db, run, tenant, owner)
            if hashlib.sha256(body).hexdigest() != run.file_sha256:
                raise app_gateway.ReviewedExcelError("原件哈希不一致，不能恢复")
            review = app_gateway.inspect_workbook(body)
            review, batches = restore_checkpoint_review(review, checkpoint)
            index = len(checkpoint.get("results") or [])
            if index >= len(batches) or (checkpoint.get("repair") or {}).get("step") != index:
                raise app_gateway.ReviewedExcelError("已保存回答与当前批次不一致")
            answer, saved_request = saved_classification_answer(
                latest, classification_id, version, run.file_sha256
            )
            messages = saved_request.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                raise app_gateway.ReviewedExcelError("已保存请求不完整")
            result = app_gateway._classify_semantic_batch(
                {**review, "cells": batches[index], "full_cells": review["cells"]},
                reference_ids=True,
                repair=messages[2:],
                expected_request_sha256=latest["request_sha256"],
                archived_answer=answer,
            )
            support._recheck(request, (tenant, owner))
            app_gateway._source(db, run, tenant, owner)
            checkpoint["results"].append(result)
            checkpoint["phase"] = "paused"
            checkpoint.pop("repair", None)
            history.append(
                {
                    "request_sha256": latest["request_sha256"],
                    "response_sha256": latest["response_sha256"],
                    "step": index,
                    "owner_user_id": owner,
                    "can_slice": (result.get("input_summary", {}).get("source_coverage") or {}).get(
                        "can_slice"
                    ),
                    "revalidated_at": app_gateway.utcnow().isoformat(),
                }
            )
            state["saved_response_revalidations"] = history
            app_gateway._classification_cas(db, run, old, state)
            return {
                "phase": "paused",
                "checkpoint": support._checkpoint_view(checkpoint),
                "replayed": False,
                "can_slice": (result.get("input_summary", {}).get("source_coverage") or {}).get(
                    "can_slice"
                ),
            }
    except app_gateway.EltError as exc:
        raise HTTPException(status_code=409, detail=app_gateway.public_excel_error(exc)) from exc

@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/analyze/abandon")
def reviewed_excel_classification_abandon_call(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    request_sha256: str = Form("", max_length=64),
    candidate_key: str = Form("", max_length=64),
    confirm: str = Form(..., max_length=40),
    note: str = Form("", max_length=300),
    user=Depends(support._manage),
):
    """The user accepts a possible duplicate charge to unlock one unknown-outcome call."""
    from app.application.reviewed_excel_audit import abandon_call, normalize_audit

    if confirm != "abandon_unknown_call":
        raise HTTPException(status_code=400, detail="须明确确认放弃未知结果请求")
    tenant, owner = support._identity(user)
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._classification_run(db, classification_id, tenant, owner)
            old = run.draft_json
            state = app_gateway.load_json(old, {})
            versions = state.get("versions", [])
            checkpoint = state.get("analysis_checkpoint") or {}
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            if candidate_key:
                record = support._abandon_candidate_claim(state, candidate_key, owner, note)
            else:
                if checkpoint.get("phase") != "inflight":
                    raise HTTPException(status_code=409, detail="没有待处理的未知结果请求")
                normalize_audit(state)
                record = abandon_call(
                    state, request_sha256, authorized_by=f"user:{owner}", note=note or "user"
                )
            support._recheck(request, (tenant, owner))
            app_gateway._classification_cas(db, run, old, state)
        return {
            "classification_id": classification_id,
            "version": version,
            "abandoned_call_id": record.get("call_id"),
            "possible_duplicate_charge": True,
            "checkpoint": support._checkpoint_view(state.get("analysis_checkpoint")),
        }
    except app_gateway.ReviewedExcelError as exc:
        raise HTTPException(status_code=409, detail=app_gateway.public_excel_error(exc)) from None
