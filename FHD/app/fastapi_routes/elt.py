"""Retained source originals and versions, independent of business imports."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.application.etl.service import get_etl_service
from app.db.session import get_db_dependency
from app.fastapi_routes.etl import _error_boundary, _execute, _feature_gate, _read, _user_id

router = APIRouter(
    prefix="/api/elt/sources",
    tags=["elt"],
    dependencies=[Depends(_feature_gate), Depends(_error_boundary)],
)


@router.post("", status_code=201)
def create_source(
    file: UploadFile = File(...),
    request_key: str = Form(..., min_length=1, max_length=80),
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_execute),
):
    data = get_etl_service().create_source(
        db,
        owner_user_id=_user_id(user),
        file_name=file.filename or "upload",
        content_type=file.content_type,
        stream=file.file,
        request_key=request_key,
    )
    return {"success": True, "data": data}


@router.get("/{asset_id}")
def get_source(
    asset_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_etl_service().get_source(db, asset_id=asset_id, owner_user_id=_user_id(user))
    return {"success": True, "data": data}


@router.post("/{asset_id}/revisions", status_code=201)
def append_source_revision(
    asset_id: str,
    expected_version: int = Form(..., ge=1),
    file: UploadFile = File(...),
    request_key: str = Form(..., min_length=1, max_length=80),
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_execute),
):
    data = get_etl_service().append_source_revision(
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


@router.get("/{asset_id}/revisions")
def list_source_revisions(
    asset_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_etl_service().list_source_revisions(
        db, asset_id=asset_id, owner_user_id=_user_id(user)
    )
    return {"success": True, "data": data}


@router.get("/{asset_id}/revisions/{revision_id}")
def get_source_revision(
    asset_id: str,
    revision_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    data = get_etl_service().get_source_revision(
        db, asset_id=asset_id, revision_id=revision_id, owner_user_id=_user_id(user)
    )
    return {"success": True, "data": data}


@router.get("/{asset_id}/revisions/{revision_id}/content")
def get_source_content(
    asset_id: str,
    revision_id: str,
    db: Session = Depends(get_db_dependency, scope="function"),
    user: Any = Depends(_read),
):
    content, file_name = get_etl_service().get_source_content(
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
