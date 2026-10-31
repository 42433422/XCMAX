"""企业版数据对接中心 API。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.application.elt.errors import EltError
from app.application.elt.service import get_elt_service
from app.db.session import get_db_dependency
from app.infrastructure.auth.dependencies import require_permission
from app.mod_sdk.product_skus import resolve_product_sku
from app.schemas.elt_schema import (
    EltDraftPatch,
    EltExecuteRequest,
    EltPreviewRequest,
    EltShipmentTemplateRequest,
    EltTemplateRequest,
    EltTemplateUpdateRequest,
)


def _feature_gate() -> None:
    flag = str(os.environ.get("FHD_ETL_CENTER_ENABLED") or "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "ELT_CENTER_DISABLED", "message": "数据对接中心尚未启用"},
        )
    if resolve_product_sku() != "enterprise":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ELT_ENTERPRISE_REQUIRED",
                "message": "数据对接中心仅在企业版中提供",
            },
        )


def _error_boundary() -> Iterator[None]:
    try:
        yield
    except EltError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


router = APIRouter(
    prefix="/api/elt",
    tags=["elt"],
    dependencies=[Depends(_feature_gate), Depends(_error_boundary)],
)

_read = require_permission("etl.read")
_template_manage = require_permission("etl.template.manage")
_execute = require_permission("etl.execute")
_rollback = require_permission("etl.rollback")
_target_manage = require_permission("etl.target.manage")


def _user_id(user: Any) -> int:
    value = getattr(user, "id", None)
    if value is None:
        value = getattr(user, "user_id", None)
    if value is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "ELT_USER_REQUIRED", "message": "请先登录"},
        )
    return int(value)


@router.get("/capabilities")
def capabilities(_user: Any = Depends(_read)):
    return {"success": True, "data": get_elt_service().capabilities()}


@router.post("/uploads", status_code=201)
def upload_file(
    file: UploadFile = File(...),
    batch_id: str | None = Form(default=None),
    relative_path: str | None = Form(default=None),
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_execute),
):
    data = get_elt_service().save_upload(
        db,
        owner_user_id=_user_id(user),
        file_name=file.filename or "upload",
        content_type=file.content_type,
        stream=file.file,
        batch_id=batch_id,
        relative_path=relative_path,
    )
    return {"success": True, "data": data}


@router.post("/runs/preview", status_code=202)
def create_preview(
    body: EltPreviewRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    data = get_elt_service().create_preview(
        db,
        owner_user_id=_user_id(user),
        upload_id=body.upload_id,
        target_type=body.target_type,
        template_id=body.template_id,
        compatibility_preset_id=body.compatibility_preset_id,
        target_config_id=body.target_config_id,
    )
    return {"success": True, "data": data}


@router.get("/runs")
def list_runs(
    limit: int = Query(default=50, ge=1, le=500),
    batch_id: str | None = Query(default=None),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().list_runs(
            db,
            owner_user_id=_user_id(user),
            limit=limit,
            batch_id=batch_id,
        ),
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().get_run(db, run_id=run_id, owner_user_id=_user_id(user)),
    }


@router.get("/runs/{run_id}/rows")
def get_run_rows(
    run_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None),
    source_sheet: str | None = Query(default=None, max_length=255),
    source_row: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().get_rows(
            db,
            run_id=run_id,
            owner_user_id=_user_id(user),
            page=page,
            page_size=page_size,
            action=action,
            source_sheet=source_sheet,
            source_row=source_row,
        ),
    }


@router.patch("/runs/{run_id}/draft")
def patch_run_draft(
    run_id: str,
    body: EltDraftPatch,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    patch = body.model_dump(exclude_none=True)
    if patch.get("field_mappings") is not None:
        patch["field_mappings"] = [
            mapping.model_dump() if hasattr(mapping, "model_dump") else mapping
            for mapping in body.field_mappings or []
        ]
    return {
        "success": True,
        "data": get_elt_service().update_draft(
            db,
            run_id=run_id,
            owner_user_id=_user_id(user),
            patch=patch,
        ),
    }


@router.post("/runs/{run_id}/execute", status_code=202)
def execute_run(
    run_id: str,
    body: EltExecuteRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    return {
        "success": True,
        "data": get_elt_service().execute(
            db,
            run_id=run_id,
            owner_user_id=_user_id(user),
            confirmed=body.confirmed,
            valid_rows_only=body.valid_rows_only,
            preview_revision=body.preview_revision,
        ),
    }


@router.post("/runs/{run_id}/shipment-template")
def save_shipment_template(
    run_id: str,
    body: EltShipmentTemplateRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_template_manage),
):
    return {
        "success": True,
        "data": get_elt_service().save_run_shipment_template(
            db,
            run_id=run_id,
            owner_user_id=_user_id(user),
            name=body.name,
            source_region_id=body.source_region_id,
        ),
    }


@router.post("/runs/{run_id}/retry")
def retry_run(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    return {
        "success": True,
        "data": get_elt_service().retry(db, run_id=run_id, owner_user_id=_user_id(user)),
    }


@router.post("/runs/{run_id}/replay", status_code=202)
def replay_run(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_execute),
):
    return {
        "success": True,
        "data": get_elt_service().replay(db, run_id=run_id, owner_user_id=_user_id(user)),
    }


@router.post("/runs/{run_id}/rollback")
def rollback_run(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_rollback),
):
    return {
        "success": True,
        "data": get_elt_service().rollback(db, run_id=run_id, owner_user_id=_user_id(user)),
    }


@router.get("/runs/{run_id}/download")
def download_run_export(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    path = get_elt_service().download_path(db, run_id=run_id, owner_user_id=_user_id(user))
    return FileResponse(path, filename=path.name)


@router.get("/runs/{run_id}/errors/export")
def download_error_rows(
    run_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    path = get_elt_service().export_error_rows(db, run_id=run_id, owner_user_id=_user_id(user))
    return FileResponse(path, filename=path.name, media_type="text/csv")


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().list_templates(db, owner_user_id=_user_id(user)),
    }


@router.post("/templates", status_code=201)
def create_template(
    body: EltTemplateRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_template_manage),
):
    return {
        "success": True,
        "data": get_elt_service().create_template(
            db,
            owner_user_id=_user_id(user),
            name=body.name,
            target_type=body.target_type,
            draft=body.draft,
            source_features=body.source_features,
            description=body.description,
        ),
    }


@router.put("/templates/{template_id}")
def update_template(
    template_id: str,
    body: EltTemplateUpdateRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_template_manage),
):
    return {
        "success": True,
        "data": get_elt_service().update_template(
            db,
            template_id=template_id,
            owner_user_id=_user_id(user),
            draft=body.draft,
            source_features=body.source_features,
            name=body.name,
            description=body.description,
        ),
    }


@router.get("/templates/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().get_template(
            db, template_id=template_id, owner_user_id=_user_id(user)
        ),
    }


@router.get("/templates/{template_id}/versions")
def list_template_versions(
    template_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_elt_service().template_versions(
            db, template_id=template_id, owner_user_id=_user_id(user)
        ),
    }


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_template_manage),
):
    get_elt_service().delete_template(db, template_id=template_id, owner_user_id=_user_id(user))
    return JSONResponse(status_code=204, content=None)


sources_router = APIRouter(
    prefix="/api/elt/sources",
    tags=["elt"],
    dependencies=[Depends(_feature_gate), Depends(_error_boundary)],
)


@sources_router.post("", status_code=201)
def create_source(
    file: UploadFile = File(...),
    request_key: str = Form(..., min_length=1, max_length=80),
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_execute),
):
    data = get_elt_service().create_source(
        db,
        owner_user_id=_user_id(user),
        file_name=file.filename or "upload",
        content_type=file.content_type,
        stream=file.file,
        request_key=request_key,
    )
    return {"success": True, "data": data}


@sources_router.get("/{asset_id}")
def get_source(
    asset_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_elt_service().get_source(db, asset_id=asset_id, owner_user_id=_user_id(user))
    return {"success": True, "data": data}


@sources_router.post("/{asset_id}/revisions", status_code=201)
def append_source_revision(
    asset_id: str,
    expected_version: int = Form(..., ge=1),
    file: UploadFile = File(...),
    request_key: str = Form(..., min_length=1, max_length=80),
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_execute),
):
    data = get_elt_service().append_source_revision(
        db,
        asset_id=asset_id,
        expected_version=expected_version,
        owner_user_id=_user_id(user),
        file_name=file.filename or "upload",
        content_type=file.content_type,
        stream=file.file,
        request_key=request_key,
    )
    return {"success": True, "data": data}


@sources_router.get("/{asset_id}/revisions")
def list_source_revisions(
    asset_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_elt_service().list_source_revisions(
        db, asset_id=asset_id, owner_user_id=_user_id(user)
    )
    return {"success": True, "data": data}


@sources_router.get("/{asset_id}/revisions/{revision_id}")
def get_source_revision(
    asset_id: str,
    revision_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_elt_service().get_source_revision(
        db, asset_id=asset_id, revision_id=revision_id, owner_user_id=_user_id(user)
    )
    return {"success": True, "data": data}


@sources_router.get("/{asset_id}/revisions/{revision_id}/content")
def get_source_content(
    asset_id: str,
    revision_id: str,
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_read),
):
    content, file_name = get_elt_service().get_source_content(
        db, asset_id=asset_id, revision_id=revision_id, owner_user_id=_user_id(user)
    )

    def chunks() -> Iterator[bytes]:
        try:
            yield from iter(lambda: content.read(64 * 1024), b"")
        finally:
            content.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(file_name, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
        background=BackgroundTask(content.close),
    )
