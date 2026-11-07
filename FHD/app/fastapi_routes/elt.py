"""企业版数据对接中心 API。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.application.elt.errors import EltError
from app.application.elt.service import get_elt_service
from app.db.session import get_db_dependency
from app.infrastructure.auth.dependencies import require_permission
from app.mod_sdk.product_skus import resolve_product_sku


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
_execute = require_permission("etl.execute")


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
