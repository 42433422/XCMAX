"""Reviewed Excel template routes: classify."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.fastapi_routes.reviewed_excel import app_gateway, support
from app.middleware.error_handler import ReviewedExcelRoute

router = APIRouter(route_class=ReviewedExcelRoute)
logger = logging.getLogger(__name__)


@router.get("/api/templates/reviewed-excel/identity")
def reviewed_excel_identity(request: Request, user=Depends(support._manage)):
    tenant, owner = support._identity(user)
    return app_gateway.model_session_identity(request, tenant, owner)

@router.post("/api/templates/reviewed-excel/classify")
async def reviewed_excel_classify(
    request: Request,
    files: list[UploadFile] = File(...),
    expected_actor: str = Form(..., max_length=80),
    user=Depends(support._manage),
):
    support._expected_actor(expected_actor, user)
    identity = support._identity(user)
    if not files or len(files) > 200:
        raise HTTPException(status_code=400, detail="请选择 1 至 200 个文件；更多文件请分批上传")
    results = []
    prepared = []
    total = 0
    for file in files:
        try:
            body = await support._body(file)
            total += len(body)
            if total > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="本批文件超过 50 MB")
            review = await run_in_threadpool(app_gateway.inspect_workbook, body)
            result = {
                "name": file.filename,
                "sha256": review["sha256"],
                "status": "classified",
                "sheets": app_gateway.classify_review_workbook(review),
                "model_status": "not_called",
                "read_only_print_areas": review["read_only_print_areas"],
                "usage_restrictions": list(review.get("usage_restrictions", [])),
            }
            result["fragment_links"] = app_gateway.observe_fragment_relationships(review, result["sheets"])
            results.append(result)
            prepared.append((file, body, result))
        except HTTPException as exc:
            if exc.status_code == 413 and total > 50 * 1024 * 1024:
                raise
            results.append(
                {
                    "name": file.filename,
                    "status": "unsupported",
                    "message": str(exc.detail),
                    "sheets": [],
                }
            )
        except (ValueError, TypeError) as exc:
            results.append(
                {
                    "name": file.filename,
                    "status": "unsupported",
                    "message": app_gateway.public_excel_error(exc),
                    "sheets": [],
                }
            )
    support._recheck(request, identity)
    tenant, owner = identity

    created_paths = []
    commit_attempted = False
    try:
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as db:
            for file, body, result in prepared:
                upload = app_gateway.UploadServiceMixin().save_upload(
                    db,
                    owner_user_id=owner,
                    file_name=file.filename or "review.xlsx",
                    content_type=file.content_type,
                    stream=BytesIO(body),
                )
                record = db.get(app_gateway.EltUpload, upload["upload_id"])
                created_paths.append(Path(record.storage_path))
                version = app_gateway._classification_version(
                    result["sha256"],
                    "",
                    {
                        "sheets": result["sheets"],
                        "fragment_links": result["fragment_links"],
                    },
                )
                result.update(
                    {"classification_id": app_gateway.new_id(), "version": version, "confirmed": False}
                )
                db.add(
                    app_gateway.EltRun(
                        id=result["classification_id"],
                        tenant_id=tenant,
                        owner_user_id=owner,
                        upload_id=upload["upload_id"],
                        target_type="template_classification",
                        status=app_gateway._CLASS_READY,
                        stage=app_gateway._CLASS_READY,
                        file_sha256=result["sha256"],
                        draft_json=app_gateway.dump_json(
                            support._draft_with_structural_index(
                                {
                                    "versions": [
                                        {
                                            "version": version,
                                            "sheets": result["sheets"],
                                            "fragment_links": result["fragment_links"],
                                            "model_status": "not_called",
                                            "confirmed": False,
                                            "read_only_print_areas": result[
                                                "read_only_print_areas"
                                            ],
                                            "usage_restrictions": result["usage_restrictions"],
                                        }
                                    ]
                                },
                                body,
                            )
                        ),
                        summary_json=app_gateway.dump_json(
                            {
                                "kind": "classification",
                                "usage_restrictions": result["usage_restrictions"],
                            }
                        ),
                    )
                )
            commit_attempted = True
            db.commit()
    except app_gateway.BOUNDARY_ERRORS:
        if not commit_attempted:
            for path in created_paths:
                app_gateway.discard_stored_upload(path)
        raise
    return {"files": results, "scope": "仅检查工作表非空单元格和公式表达式；不表示语义完整理解"}
