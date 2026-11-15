"""Reviewed Excel template routes: save."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import update

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.post("/api/templates/reviewed-excel/save")
async def reviewed_excel_save(
    request: Request,
    review_id: str = Form(..., max_length=36),
    proposal_version: str = Form(..., max_length=64),
    candidate_id: str = Form(..., max_length=64),
    selections: str = Form(..., max_length=500_000),
    name: str = Form(..., max_length=160),
    publish_to_tenant: bool = Form(False),
    private_intake: bool = Form(False),
    template_only: bool = Form(False),
    intake_run_id: str = Form("", max_length=36),
    preview_revision: str = Form("", max_length=64),
    valid_rows_only: bool = Form(False),
    composer_note: str = Form("", max_length=4000),
    user=Depends(support._manage),
):
    tenant, owner = support._identity(user)
    # Enterprise shared-library path still requires explicit publish consent.
    # User intake (archiveOnSelect) uses private_intake: save + auto-ingest without
    # enterprise-library publish checkbox; approval withdraw remains available.
    if publish_to_tenant and private_intake:
        raise HTTPException(status_code=400, detail="不能同时选择企业发布与私有入库")
    if not publish_to_tenant and not private_intake:
        raise HTTPException(status_code=400, detail="请确认将清理后的模板发布到企业模板库")
    if not name.strip() or len(name.strip()) > 160:
        raise HTTPException(status_code=400, detail="模板名称不能为空或超过 160 字")
    try:
        selected = json.loads(selections)
        if not isinstance(selected, list):
            raise app_gateway.ReviewedExcelError("清理范围无效")
        summary_for_ingest: dict = {}
        confirmed_plan: dict | None = None
        saved_template = False
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            run = app_gateway._run(db, review_id, tenant, owner)
            app_gateway._review_source_version(db, run, tenant, owner)
            # Print/layout restrictions block enterprise publish only; private intake may proceed.
            if publish_to_tenant and app_gateway._usage_restrictions(db, run, tenant, owner):
                raise HTTPException(
                    status_code=409,
                    detail="此来源仅供数据/模板测试，打印版式未验证；可预览和下载测试候选，不得发布到企业模板库",
                )
            state, versions = app_gateway._proposals(run)
            if private_intake:
                app_gateway._require_private_model(request, versions[-1], tenant, owner)
            request_key = hashlib.sha256(
                app_gateway.dump_json(
                    {
                        "version": proposal_version,
                        "candidate": candidate_id,
                        "selections": selected,
                        "name": name.strip(),
                        **({"template_only": True} if template_only else {}),
                        **(
                            {
                                "intake_run_id": intake_run_id,
                                "preview_revision": preview_revision,
                                "valid_rows_only": valid_rows_only,
                                "note": composer_note.strip(),
                            }
                            if intake_run_id
                            else {}
                        ),
                    }
                ).encode()
            ).hexdigest()
            if run.status == app_gateway._SAVED:
                receipt = app_gateway.load_json(run.receipt_json, {})
                if request_key in (receipt.get("request_key"), receipt.get("intake_request_key")):
                    return {
                        "success": True,
                        "template_id": receipt["template_id"],
                        "replayed": True,
                        "reused": bool(receipt.get("reused")),
                        "auto_ingest": receipt.get("auto_ingest")
                        or {
                            "success": False,
                            "error": "outcome_unknown"
                            if intake_run_id
                            else "confirmation_required",
                        },
                    }
                template_request_key = hashlib.sha256(
                    app_gateway.dump_json(
                        {
                            "version": proposal_version,
                            "candidate": candidate_id,
                            "selections": selected,
                            "name": name.strip(),
                            "template_only": True,
                        }
                    ).encode()
                ).hexdigest()
                confirmation = state.get("confirmation") or {}
                if (
                    receipt.get("request_key") != template_request_key
                    or not private_intake
                    or template_only
                    or not intake_run_id
                    or receipt.get("intake_request_key")
                    or confirmation.get("version") != proposal_version
                    or confirmation.get("candidate") != candidate_id
                    or confirmation.get("selected") != selected
                ):
                    raise HTTPException(
                        status_code=409, detail="此审阅已保存；新的清理范围请新建审阅"
                    )
                saved_template = True
            if (run.status != app_gateway._READY and not saved_template) or versions[-1][
                "version"
            ] != proposal_version:
                raise HTTPException(status_code=409, detail="审阅版本已过期或保存结果待核对")
            candidate = next(
                (item for item in versions[-1]["candidates"] if item["id"] == candidate_id), None
            )
            if candidate is None:
                raise HTTPException(status_code=409, detail="候选不属于该审阅版本")
            body = app_gateway._source(db, run, tenant, owner)
            if private_intake and not intake_run_id and not template_only:
                raise HTTPException(
                    status_code=409, detail="请先核对入库目标和记录数量，再确认入库"
                )
            if intake_run_id:
                from app.application.elt.auto_ingest_service import get_auto_ingest_service
                from app.application.elt.service import get_elt_service

                plan = state.get("intake_preview") or {}
                expected_key = app_gateway._intake_selection_key(
                    run, proposal_version, candidate_id, selected, name, composer_note
                )
                mod_id = support._authorize_intake(
                    request, (tenant, owner), str(plan.get("target_type") or "")
                )
                if (
                    plan.get("run_id") != intake_run_id
                    or plan.get("selection_key") != expected_key
                    or plan.get("source_sha256") != run.file_sha256
                    or plan.get("mod_id") != mod_id
                ):
                    raise HTTPException(
                        status_code=409, detail="候选、整理要求或业务空间已变化，请重新预演"
                    )
                upload = get_elt_service()._owned_upload(db, plan["upload_id"], owner)
                if upload.tenant_id != tenant:
                    raise HTTPException(status_code=403, detail="无权使用该入库预演")
                prepared_path = Path(upload.storage_path)
                business = get_auto_ingest_service().validate_prepared(
                    db,
                    plan=plan,
                    path=prepared_path,
                    owner_user_id=owner,
                    tenant_id=tenant,
                    preview_revision=preview_revision,
                    owned_upload_user_id=upload.owner_user_id,
                )
                error_rows = int((business.get("summary") or {}).get("error") or 0)
                if error_rows:
                    valid_rows_only = True
                confirmed_plan = {
                    **plan,
                    "preview_revision": preview_revision,
                    "valid_rows_only": valid_rows_only,
                }
                if error_rows:
                    from app.application.elt.auto_ingest_service import (
                        knowledge_document_keeps_unwritten_rows,
                    )

                    held = confirmed_plan.get("knowledge")
                    held = held if isinstance(held, dict) else {}
                    kept = knowledge_document_keeps_unwritten_rows(
                        str(held.get("content") or ""),
                        str(held.get("source_text") or ""),
                    )
                    if kept:
                        # The archived source hash stays so the preview is still the same file.
                        # The stored document is the summary plus that source, including unwritten rows.
                        refreshed = get_auto_ingest_service().knowledge_plan(
                            path=prepared_path,
                            file_name=str(confirmed_plan.get("name") or ""),
                            note=str(confirmed_plan.get("note") or ""),
                            owner_user_id=owner,
                            owned_upload_user_id=upload.owner_user_id,
                            source_text=kept,
                            allow_model=False,
                        )
                        refreshed["used_llm"] = True
                        refreshed["source_hash"] = held.get("source_hash")
                        refreshed["source_text"] = held.get("source_text")
                        confirmed_plan["knowledge"] = refreshed
                # The staged upload is the candidate chosen at preview. The template
                # file is that same cleanup of the review workbook, not the full original.
                cleaned = app_gateway.clean_workbook(body, run.file_sha256, selected)
            else:
                # Old template-library clients authorize one template only, never implicit business writes.
                cleaned = app_gateway.clean_workbook(body, run.file_sha256, selected)
            if saved_template:
                if confirmed_plan is None:
                    raise HTTPException(status_code=409, detail="入库预演缺失，不能提交")
                # Claim this continuation before external approval creation. A lost result
                # is read back, never blindly submitted twice; the template is not recreated.
                support._recheck(request, (tenant, owner))
                db.expire_all()
                classification_lock = app_gateway._lock_review_classification(db, run, tenant, owner)
                app_gateway._review_source_version(db, run, tenant, owner)
                if (
                    support._authorize_intake(request, (tenant, owner), confirmed_plan["target_type"])
                    != confirmed_plan["mod_id"]
                ):
                    raise HTTPException(status_code=409, detail="业务空间已变化，请重新预演")
                from app.application.elt.auto_ingest_service import workbook_text

                get_auto_ingest_service().validate_prepared(
                    db,
                    plan=confirmed_plan,
                    path=prepared_path,
                    owner_user_id=owner,
                    tenant_id=tenant,
                    preview_revision=preview_revision,
                    owned_upload_user_id=upload.owner_user_id,
                    source_text=workbook_text(app_gateway._archived_original(db, run, tenant, owner)),
                )
                old_receipt = run.receipt_json
                receipt = app_gateway.load_json(old_receipt, {})
                template_id = receipt["template_id"]
                reused = bool(receipt.get("reused"))
                receipt["intake_request_key"] = request_key
                receipt["auto_ingest"] = {"success": False, "error": "outcome_unknown"}
                claimed = db.execute(
                    update(app_gateway.EltRun)
                    .where(
                        app_gateway.EltRun.id == run.id,
                        app_gateway.EltRun.tenant_id == tenant,
                        app_gateway.EltRun.owner_user_id == owner,
                        app_gateway.EltRun.status == app_gateway._SAVED,
                        app_gateway.EltRun.receipt_json == old_receipt,
                    )
                    .values(receipt_json=app_gateway.dump_json(receipt))
                )
                if claimed.rowcount != 1:
                    db.rollback()
                    raise HTTPException(status_code=409, detail="入库提交正在处理中，请读取原结果")
                summary_for_ingest = app_gateway.load_json(run.summary_json, {})
                app_gateway._unlock_review_classification(db, classification_lock, tenant, owner)
                db.commit()
            else:
                before = {(i["sheet"], i["cell"]) for i in candidate["clear"]}
                after = {(i["sheet"], i["cell"]) for i in selected}
                state["confirmation"] = {
                    "version": proposal_version,
                    "candidate": candidate_id,
                    "selected": selected,
                    "added": [{"sheet": s, "cell": c} for s, c in sorted(after - before)],
                    "removed": [{"sheet": s, "cell": c} for s, c in sorted(before - after)],
                }
                old_draft = run.draft_json
                saving_draft = app_gateway.dump_json(state)
                classification_lock = app_gateway._lock_review_classification(db, run, tenant, owner)
                app_gateway._cas(db, run, old_draft, status=app_gateway._SAVING, stage=app_gateway._SAVING, draft_json=saving_draft)
                try:
                    support._recheck(request, (tenant, owner))
                    db.expire_all()
                    app_gateway._review_source_version(db, run, tenant, owner)
                    if confirmed_plan:
                        if (
                            support._authorize_intake(
                                request, (tenant, owner), confirmed_plan["target_type"]
                            )
                            != confirmed_plan["mod_id"]
                        ):
                            raise HTTPException(
                                status_code=409, detail="业务空间已变化，请重新预演"
                            )
                        from app.application.elt.auto_ingest_service import workbook_text

                        get_auto_ingest_service().validate_prepared(
                            db,
                            plan=confirmed_plan,
                            path=prepared_path,
                            owner_user_id=owner,
                            tenant_id=tenant,
                            preview_revision=preview_revision,
                            owned_upload_user_id=upload.owner_user_id,
                            source_text=workbook_text(app_gateway._archived_original(db, run, tenant, owner)),
                        )
                except (HTTPException, app_gateway.EltError):
                    app_gateway._release_failed_review(
                        db, run.id, tenant, owner, saving_draft, old_draft, classification_lock
                    )
                    raise
                root = Path(app_gateway.get_app_data_dir()) / "templates" / "reviewed_excel" / str(tenant)
                path = root / f"{uuid4().hex}.xlsx"
                created = False
                fd = None
                try:
                    root.mkdir(parents=True, exist_ok=True)
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    created = True
                    stream = os.fdopen(fd, "wb")
                    fd = None
                    with stream:
                        stream.write(cleaned)
                except OSError:
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    cleanup_failed = False
                    if created:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            cleanup_failed = True
                    app_gateway._release_failed_review(
                        db, run.id, tenant, owner, saving_draft, old_draft, classification_lock
                    )
                    detail = "临时文件写入失败，模板未提交，可以重试"
                    if cleanup_failed:
                        detail = "临时文件写入失败，模板未提交；临时副本需管理员清理"
                    raise HTTPException(status_code=503, detail=detail) from None
                try:
                    from app.legacy.routes.document_templates_compat import (
                        run_archive_template_create,
                    )

                    result, code = run_archive_template_create(
                        {
                            "name": name.strip(),
                            "template_type": "Excel",
                            "category": "excel",
                            "business_scope": "custom",
                            "source": "reviewed_excel_cleanup",
                            "file_path": str(path),
                            "fields": [],
                            "preview_data": {
                                "reviewed_excel": True,
                                "source_sha256": (
                                    app_gateway.load_json(run.summary_json, {}).get("selected_region") or {}
                                ).get("source_sha256", run.file_sha256),
                                "derived_sha256": run.file_sha256,
                                "selected_region": app_gateway.load_json(run.summary_json, {}).get(
                                    "selected_region"
                                ),
                                "review_id": review_id,
                                **(
                                    {
                                        "revision_parent": app_gateway.load_json(run.summary_json, {})[
                                            "revision_parent"
                                        ]
                                    }
                                    if app_gateway.load_json(run.summary_json, {}).get("revision_parent")
                                    else {}
                                ),
                            },
                        }
                    )
                    if code >= 400 or not result.get("success"):
                        raise HTTPException(
                            status_code=code if code >= 400 else 500,
                            detail=result.get("message", "保存失败"),
                        )
                    template_id = result["template"]["id"]
                    reused = bool(result.get("reused"))
                    if reused:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            logger.warning("duplicate template file was left on disk")
                    persisted = db.execute(
                        update(app_gateway.EltRun)
                        .where(
                            app_gateway.EltRun.id == run.id,
                            app_gateway.EltRun.tenant_id == tenant,
                            app_gateway.EltRun.owner_user_id == owner,
                            app_gateway.EltRun.status == app_gateway._SAVING,
                        )
                        .values(
                            status=app_gateway._SAVED,
                            stage=app_gateway._SAVED,
                            receipt_json=app_gateway.dump_json(
                                {
                                    "request_key": request_key,
                                    "template_id": template_id,
                                    "reused": reused,
                                    **(
                                        {
                                            "revision_parent": app_gateway.load_json(run.summary_json, {})[
                                                "revision_parent"
                                            ]
                                        }
                                        if app_gateway.load_json(run.summary_json, {}).get("revision_parent")
                                        else {}
                                    ),
                                }
                            ),
                        )
                    )
                    if persisted.rowcount != 1:
                        db.rollback()
                        raise HTTPException(
                            status_code=409, detail="模板已写入但审阅回执未确认，请人工核对"
                        )
                    app_gateway._unlock_review_classification(db, classification_lock, tenant, owner)
                    # Snapshot before session closes: EltRun detaches when get_db() exits,
                    # and post-save auto-ingest must not touch ORM attributes afterward.
                    summary_for_ingest = app_gateway.load_json(run.summary_json, {})
                    db.commit()
                except app_gateway.BOUNDARY_ERRORS:
                    # The legacy library commits in a separate transaction; do not retry or remove
                    # files when its outcome may have succeeded but its receipt was lost.
                    raise
        auto_ingest = {"success": False, "error": "confirmation_required"}
        if confirmed_plan:
            try:
                from app.application.elt.docking_approval import submit_docking_write

                auto_ingest = submit_docking_write(
                    owner_user_id=owner,
                    tenant_id=tenant,
                    # Staged candidate workbook chosen at preview. The path stays
                    # in the server ledger; the approval request only carries the batch id.
                    source_path=str(prepared_path),
                    file_name=name.strip(),
                    template_id=str(template_id),
                    review_id=review_id,
                    classification_id=str(summary_for_ingest.get("classification_id") or ""),
                    composer_note=composer_note.strip(),
                    prepared_plan=confirmed_plan,
                    owned_upload_user_id=owner,
                )
            except app_gateway.BOUNDARY_ERRORS as exc:
                context = app_gateway._reviewed_excel_context(request)
                logger.error(
                    "ELT auto-ingest failed stage=save request_id=%s error_type=%s",
                    context["request_id"],
                    type(exc).__name__,
                )
                auto_ingest = {"success": False, "error": "auto_ingest_failed", **context}
            with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
                persisted_run = app_gateway._run(db, review_id, tenant, owner)
                receipt = app_gateway.load_json(persisted_run.receipt_json, {})
                receipt["auto_ingest"] = auto_ingest
                persisted_run.receipt_json = app_gateway.dump_json(receipt)
                db.commit()
        return {
            "success": True,
            "template_id": template_id,
            "replayed": False,
            "reused": reused,
            "auto_ingest": auto_ingest,
        }
    except (ValueError, TypeError, app_gateway.EltError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 400), detail=app_gateway.public_excel_error(exc)
        ) from None
