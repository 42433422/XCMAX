"""Reviewed Excel template routes: classifications."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.get("/api/templates/reviewed-excel/classifications")
def reviewed_excel_recent_classifications(user=Depends(support._read)):
    tenant, owner = support._identity(user)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        runs = (
            db.query(app_gateway.EltRun)
            .filter(
                app_gateway.EltRun.tenant_id == tenant,
                app_gateway.EltRun.owner_user_id == owner,
                app_gateway.EltRun.target_type == "template_classification",
            )
            .order_by(app_gateway.EltRun.created_at.desc())
            .limit(200)
            .all()
        )
        result = []
        for run in runs:
            upload = db.get(app_gateway.EltUpload, run.upload_id)
            state = app_gateway.load_json(run.draft_json, {})
            versions = state.get("versions", [])
            result.append(
                {
                    "classification_id": run.id,
                    "name": upload.file_name if upload else "",
                    "sha256": run.file_sha256,
                    "latest": versions[-1] if versions else None,
                    "archive_version_id": app_gateway.load_json(run.summary_json, {}).get("archive_version_id"),
                    "conversion_receipt": app_gateway.load_json(run.summary_json, {}).get("conversion_receipt"),
                    "usage_restrictions": app_gateway._usage_restrictions(db, run, tenant, owner),
                    "template_write_state": "locked"
                    if run.status == app_gateway._CLASS_SAVING
                    else "available",
                    "checkpoint": support._checkpoint_view(state.get("analysis_checkpoint")),
                }
            )
        return {"files": result}


@router.get("/api/templates/reviewed-excel/classifications/{classification_id}")
def reviewed_excel_classification_history(classification_id: str, user=Depends(support._read)):
    tenant, owner = support._identity(user)
    with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
        run = app_gateway._classification_run(db, classification_id, tenant, owner)
        state = app_gateway.load_json(run.draft_json, {})
        return {
            "classification_id": run.id,
            "sha256": run.file_sha256,
            "usage_restrictions": app_gateway._usage_restrictions(db, run, tenant, owner),
            "conversion_receipt": app_gateway.load_json(run.summary_json, {}).get("conversion_receipt"),
            "template_write_state": "locked" if run.status == app_gateway._CLASS_SAVING else "available",
            "versions": state.get("versions", []),
            "checkpoint": support._checkpoint_view(state.get("analysis_checkpoint")),
            "unsettled_candidate_requests": [
                {
                    "candidate_key": key,
                    "state": claim.get("state"),
                    "attempts": claim.get("attempts", 1),
                }
                for key, claim in (state.get("template_candidate_requests") or {}).items()
                if claim.get("state") != "completed"
            ],
        }

@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/confirm")
def reviewed_excel_classification_confirm(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    labels_json: str = Form(..., max_length=200_000),
    links_json: str = Form("[]", max_length=100_000),
    independent_confirmed: bool = Form(False),
    user=Depends(support._manage),
):
    tenant, owner = support._identity(user)
    try:
        labels = json.loads(labels_json)
        selected_links = json.loads(links_json)
        if not isinstance(labels, list):
            raise app_gateway.ReviewedExcelError("分类修正无效")
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._classification_run(db, classification_id, tenant, owner)
            review = app_gateway.inspect_workbook(app_gateway._source(db, run, tenant, owner))
            old = run.draft_json
            state = app_gateway.load_json(old, {})
            versions = state.get("versions", [])
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            latest = json.loads(json.dumps(versions[-1], ensure_ascii=False))
            from app.application.reviewed_excel_plan import restore_completed_review

            review = restore_completed_review(review, latest.get("source_scope"))
            # Keep historical versions intact, but never copy legacy prompt bodies into a new version.
            latest.pop("input_messages", None)
            latest = app_gateway.apply_classification_corrections(review, latest, labels)
            before = [
                [(region["range"], region["labels"]) for region in sheet["regions"]]
                for sheet in versions[-1]["sheets"]
            ]
            after = [
                [(region["range"], region["labels"]) for region in sheet["regions"]]
                for sheet in latest["sheets"]
            ]
            partition_pending = latest["partition_pending"] or (
                versions[-1].get("partition_pending", False) and before != after
            )
            latest["partition_pending"] = partition_pending
            if before != after:
                latest["fragment_links"] = {"items": [], "omitted": 0}
                latest["suggested_documents"] = []
                latest["suggested_document_count"] = None
            if partition_pending:
                # New slices never inherit an approval or relationships from their old geometry.
                latest["fragment_links"] = app_gateway.observe_fragment_relationships(review, latest["sheets"])
            from app.application.reviewed_excel_classification_store import (
                _confirmed_document_count,
                _confirmed_documents,
            )

            latest["logical_documents"] = _confirmed_documents(
                run.file_sha256,
                version,
                latest["sheets"],
                latest.get("fragment_links", {}),
                [] if partition_pending else selected_links,
                review["cells"],
            )
            latest["confirmed_document_count"] = _confirmed_document_count(
                review,
                latest,
                latest["logical_documents"],
                independent_confirmed and not partition_pending,
            )
            latest["document_count_status"] = (
                "confirmed" if latest["confirmed_document_count"] is not None else "partial"
            )
            latest["independent_confirmed"] = independent_confirmed and not partition_pending
            selected_set = {
                (edge["sheet"], edge["first"], edge["second"])
                for edge in ([] if partition_pending else selected_links)
            }
            for link in latest.get("fragment_links", {}).get("items", []):
                link["selected"] = (link["sheet"], link["first"], link["second"]) in selected_set
            latest.update({"parent_version": version, "confirmed": not partition_pending})
            latest["version"] = app_gateway._classification_version(
                run.file_sha256,
                version,
                {
                    "sheets": latest["sheets"],
                    "logical_documents": latest["logical_documents"],
                    "confirmed_document_count": latest["confirmed_document_count"],
                    "independent_confirmed": latest["independent_confirmed"],
                    "confirmed": latest["confirmed"],
                },
            )
            versions.append(latest)
            if len(versions) > 50:
                raise app_gateway.ReviewedExcelError("分类版本已达上限")
            support._recheck(request, (tenant, owner))
            app_gateway._classification_cas(db, run, old, state)
        return {
            "classification_id": classification_id,
            "version": latest["version"],
            "confirmed": latest["confirmed"],
            "partition_pending": partition_pending,
            "message": "拆分已保存，核对新片段与续表关系后再次确认" if partition_pending else "",
            "sheets": latest["sheets"],
            "coverage": latest.get("coverage", []),
            "fragment_links": latest.get("fragment_links", {"items": [], "omitted": 0}),
            "logical_documents": latest["logical_documents"],
            "confirmed_document_count": latest["confirmed_document_count"],
            "document_count_status": latest["document_count_status"],
        }
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(status_code=400, detail=app_gateway.public_excel_error(exc)) from None
