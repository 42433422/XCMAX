"""Legacy shipment ETL routes backed by the universal preview/confirm engine."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.application.etl.service import get_etl_service
from app.db.session import get_db_dependency
from app.infrastructure.auth.dependencies import require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)
router = APIRouter()
TEMP_EXCEL_DIR = os.path.join(get_app_data_dir(), "temp_excel")


def _form_truthy(value: str, default: bool = True) -> bool:
    text = str(value if value is not None else "").strip().lower()
    return default if not text else text in {"1", "true", "yes", "on"}


def _form_include_ledger(value: str, default: str = "auto") -> bool | str:
    text = str(value if value is not None else "").strip().lower()
    if not text:
        text = str(default or "auto").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return "auto"


def _user_id(user: Any) -> int:
    value = getattr(user, "id", None)
    if value is None:
        value = getattr(user, "user_id", None)
    if value is None and isinstance(user, dict):
        value = user.get("id") or user.get("user_id")
    if value is None:
        raise EtlError("ETL_USER_REQUIRED", "请先登录", status_code=401)
    return int(value)


def _create_runs(
    db: Session,
    *,
    owner_user_id: int,
    upload_id: str,
    target_types: list[str],
) -> list[dict[str, Any]]:
    service = get_etl_service()
    return [
        service.create_preview(
            db,
            owner_user_id=owner_user_id,
            upload_id=upload_id,
            target_type=target_type,
        )
        for target_type in dict.fromkeys(target_types)
    ]


def _store_general_upload(db: Session, file: UploadFile, *, owner_user_id: int) -> dict[str, Any]:
    file.file.seek(0)
    upload = get_etl_service().save_upload(
        db,
        owner_user_id=owner_user_id,
        file_name=file.filename or "shipment.xlsx",
        content_type=file.content_type,
        stream=file.file,
    )
    db.commit()
    file.file.seek(0)
    return upload


def _safe_legacy_temp_copy(file: UploadFile) -> str:
    suffix = Path(file.filename or "shipment.xlsx").suffix[:16] or ".xlsx"
    os.makedirs(TEMP_EXCEL_DIR, exist_ok=True)
    file.file.seek(0)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="shipment_etl_",
        suffix=suffix,
        dir=TEMP_EXCEL_DIR,
        delete=False,
    ) as handle:
        shutil.copyfileobj(file.file, handle, length=1024 * 1024)
        return handle.name


def _shipment_write_permission_error(request: Request) -> JSONResponse | None:
    """Preserve the legacy production RBAC guard around shipment writes."""
    from app.application.facades.session_facade import get_auth_service
    from app.infrastructure.auth.dependencies import resolve_session_user
    from app.utils.deployment import deployment_is_production, deployment_is_staging

    configured = os.environ.get("FHD_SHIPMENT_ETL_REQUIRE_RBAC", "").strip().lower()
    required = (
        configured in {"1", "true", "yes", "on"}
        if configured
        else deployment_is_production() or deployment_is_staging()
    )
    if not required:
        return None
    session_user = resolve_session_user(request)
    if session_user is None:
        return JSONResponse(
            {"success": False, "message": "请先登录", "error_code": "unauthorized"},
            status_code=401,
        )
    if not get_auth_service().has_permission(session_user, "shipment.create"):
        return JSONResponse(
            {
                "success": False,
                "message": "缺少 shipment.create 权限",
                "error_code": "forbidden",
            },
            status_code=403,
        )
    return None


@router.post("/shipment-etl/preview")
async def shipment_etl_preview(
    file: UploadFile | None = File(default=None),
    file_path: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("auto"),
    save_as_template: str = Form("0"),
    template_name: str = Form(""),
    template_scope: str = Form(""),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(require_identified_user),
):
    """Return a legacy shipment preview plus universal ETL preview runs."""
    try:
        from app.application.office_template_ingest_app_service import (
            attach_template_ingest_to_etl_result,
        )
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        owner_user_id = _user_id(user)
        path = str(file_path or "").strip()
        upload = None
        temp_path = ""
        if file is not None and (file.filename or "").strip():
            upload = _store_general_upload(db, file, owner_user_id=owner_user_id)
            temp_path = _safe_legacy_temp_copy(file)
            path = temp_path
        if not path:
            return JSONResponse(
                {"success": False, "message": "请上传文件或提供 file_path"},
                status_code=400,
            )
        result = get_shipment_excel_etl_app_service().preview(
            path,
            include_ledger=_form_include_ledger(include_ledger),
            workspace_root=str(workspace_root or "").strip() or None,
        )
        if temp_path:
            result["uploaded_temp_path"] = temp_path
        result = attach_template_ingest_to_etl_result(
            result,
            file_path=path,
            save_as_template=_form_truthy(save_as_template, False),
            template_name=str(template_name or "").strip(),
            template_scope=str(template_scope or "").strip(),
            source="shipment_excel_etl_preview",
        )
        if result.get("success") and upload:
            result["general_etl"] = {
                "preview_required": True,
                "confirmation_required": True,
                "runs": _create_runs(
                    db,
                    owner_user_id=owner_user_id,
                    upload_id=upload["upload_id"],
                    target_types=["customers", "products", "shipment_records"],
                ),
            }
        elif result.get("success"):
            result["general_etl"] = {
                "preview_required": True,
                "confirmation_required": True,
                "runs": [],
                "upload_required": True,
                "message": "本地路径仅保留旧预览；进入数据对接中心前请重新上传文件",
            }
        return JSONResponse(result, status_code=200 if result.get("success") else 400)
    except EtlError as exc:
        return JSONResponse(
            {"success": False, "error_code": exc.code, "message": exc.message},
            status_code=exc.status_code,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("shipment etl preview failed")
        return JSONResponse(
            {"success": False, "message": "单据预览失败，请稍后重试"},
            status_code=500,
        )


@router.post("/shipment-etl/execute")
async def shipment_etl_execute(
    request: Request,
    file: UploadFile | None = File(default=None),
    file_path: str = Form(""),
    workspace_root: str = Form(""),
    notes_json: str = Form(""),
    import_products: str = Form("1"),
    import_shipments: str = Form("1"),
    idempotent: str = Form("1"),
    include_ledger: str = Form("0"),
    confirm_ledger: str = Form("0"),
    dry_run: str = Form("0"),
    direct: str = Form("0"),
    force_shipment_target: str = Form("0"),
    save_as_template: str = Form("0"),
    template_name: str = Form(""),
    template_scope: str = Form(""),
    etl_run_id: str = Form(""),
    confirmed: str = Form("0"),
    valid_rows_only: str = Form("0"),
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(require_identified_user),
):
    """Require a universal preview and an explicit confirmation before writes."""
    _ = (
        workspace_root,
        notes_json,
        idempotent,
        include_ledger,
        confirm_ledger,
        force_shipment_target,
        save_as_template,
        template_name,
        template_scope,
    )
    try:
        permission_error = _shipment_write_permission_error(request)
        if permission_error is not None:
            return permission_error
        owner_user_id = _user_id(user)
        run_id = str(etl_run_id or "").strip()
        if run_id:
            try:
                run = get_etl_service().execute(
                    db,
                    run_id=run_id,
                    owner_user_id=owner_user_id,
                    confirmed=_form_truthy(confirmed, False),
                    valid_rows_only=_form_truthy(valid_rows_only, False),
                )
            except EtlError as exc:
                return JSONResponse(
                    {
                        "success": False,
                        "error_code": exc.code,
                        "message": exc.message,
                    },
                    status_code=exc.status_code,
                )
            return JSONResponse(
                {
                    "success": True,
                    "general_etl": True,
                    "run": run,
                    "message": "已确认，通用 ETL 正在后台执行",
                },
                status_code=202,
            )
        if file is None or not (file.filename or "").strip():
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "ETL_UPLOAD_REQUIRED",
                    "message": "为防止读取任意本地路径，请重新上传源文件后预演",
                    "file_path_ignored": bool(str(file_path or "").strip()),
                },
                status_code=409,
            )
        upload = _store_general_upload(db, file, owner_user_id=owner_user_id)
        targets: list[str] = []
        if _form_truthy(import_products, True):
            targets.extend(["customers", "products"])
        if _form_truthy(import_shipments, True):
            targets.append("shipment_records")
        runs = _create_runs(
            db,
            owner_user_id=owner_user_id,
            upload_id=upload["upload_id"],
            target_types=targets or ["shipment_records"],
        )
        return JSONResponse(
            {
                "success": False,
                "error_code": "ETL_PREVIEW_CONFIRMATION_REQUIRED",
                "message": "旧接口已升级为通用 ETL：请先检查预演，再逐个确认执行",
                "general_etl": {
                    "preview_required": True,
                    "confirmation_required": True,
                    "runs": runs,
                },
                "dry_run": _form_truthy(dry_run, False),
                "direct_ignored": _form_truthy(direct, False),
            },
            status_code=409,
        )
    except EtlError as exc:
        return JSONResponse(
            {"success": False, "error_code": exc.code, "message": exc.message},
            status_code=exc.status_code,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("shipment etl execute failed")
        return JSONResponse(
            {"success": False, "message": "单据处理失败，请稍后重试"},
            status_code=500,
        )
