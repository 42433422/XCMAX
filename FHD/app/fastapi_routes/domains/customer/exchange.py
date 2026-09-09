"""Customer file exchange through existing export and preview/confirmation services."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_dependency
from app.fastapi_routes import etl
from app.infrastructure.auth.db_token import verify_db_read_token_header
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.persistence.compat_db.base import _customers_write_raise
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

router = APIRouter()


@router.post(
    "/customers/import",
    status_code=202,
    dependencies=[Depends(etl._feature_gate), Depends(etl._error_boundary)],
)
@router.post(
    "/customers/import/",
    status_code=202,
    include_in_schema=False,
    dependencies=[Depends(etl._feature_gate), Depends(etl._error_boundary)],
)
def customers_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(etl._execute),
):
    _customers_write_raise(request)
    service = etl.get_etl_service()
    owner = etl._user_id(user)
    upload = service.save_upload(
        db,
        owner_user_id=owner,
        file_name=file.filename or "customers.xlsx",
        content_type=file.content_type,
        stream=file.file,
    )
    run = service.create_preview(
        db, owner_user_id=owner, upload_id=upload["upload_id"], target_type="customers"
    )
    return {
        "success": True,
        "message": "客户文件已提交预演，请核对后确认写入",
        "data": {"run_id": run["id"], "requires_confirmation": True, "run": run},
    }


@router.get("/customers/export")
@router.get("/customers/export/", include_in_schema=False)
def customers_export(
    request: Request,
    keyword: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    _user: Any = Depends(get_logged_in_user),
):
    from app.bootstrap import get_customer_app_service
    from app.utils.path_io.path_utils import get_data_dir

    verify_db_read_token_header(request)
    result = get_customer_app_service().export_to_excel(keyword=keyword, template_id=template_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("message") or "客户导出失败"))
    try:
        path = resolve_under_allowed_dirs(
            str(result.get("file_path") or ""), [Path(get_data_dir())]
        )
    except UnsafeDownloadPathError as exc:
        raise HTTPException(status_code=500, detail="客户导出文件路径无效") from exc
    if not path.is_file():
        raise HTTPException(status_code=500, detail="客户导出文件不存在")
    return FileResponse(
        path,
        filename=str(result.get("filename") or "客户列表.xlsx"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
