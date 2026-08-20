# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.excel_extract_shipment")


@_facade().router.post("/shipment-etl/preview")
async def shipment_etl_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
):
    """预览：按内容指纹识别送货单/出货流水并抽取抬头+明细（不写业务库）。

    ``save_as_template=1`` 时额外把源办公文件解析入库模版库。
    """
    try:
        from app.application.office_template_ingest_app_service import (
            attach_template_ingest_to_etl_result,
        )
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        path = str(file_path or "").strip()
        tmp_path = ""
        if file is not None and (file.filename or "").strip():
            raw = await file.read()
            tmp_path = _facade()._temporary_upload_path(
                "etl",
                str(file.filename or "shipment.xlsx"),
                {".xls", ".xlsm", ".xlsx"},
            )
            with open(tmp_path, "wb") as fh:
                fh.write(raw)
            path = tmp_path
        if not path:
            return _facade().JSONResponse(
                {"success": False, "message": "请上传文件或提供 file_path"}, status_code=400
            )
        result = get_shipment_excel_etl_app_service().preview(
            path,
            include_ledger=_facade()._form_include_ledger(include_ledger),
            workspace_root=str(workspace_root or "").strip() or None,
        )
        if tmp_path:
            result["uploaded_temp_path"] = tmp_path
        result = attach_template_ingest_to_etl_result(
            result,
            file_path=path,
            save_as_template=_facade()._form_truthy(save_as_template, False),
            template_name=str(template_name or "").strip(),
            template_scope=str(template_scope or "").strip(),
            source="shipment_excel_etl_preview",
        )
        result = _facade()._safe_failed_etl_result(result, "单据预览失败，请检查文件内容")
        return _facade().JSONResponse(result, status_code=200 if result.get("success") else 400)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl preview failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "单据预览失败，请稍后重试"}, status_code=500
        )


@_facade().router.post("/shipment-etl/execute")
async def shipment_etl_execute(
    request: _facade().Request,
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    notes_json: str = _facade().Form(""),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    idempotent: str = _facade().Form("1"),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    dry_run: str = _facade().Form("0"),
    direct: str = _facade().Form("0"),
    force_shipment_target: str = _facade().Form("0"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """执行闭环：单据 → 客户/产品/发货单（默认幂等；流水需 confirm_ledger）。

    direct=1：无预览直写（需环境开关 FHD_EXCEL_ETL_ALLOW_DIRECT=1）。
    save_as_template=1：额外把源办公文件解析入库模版库。
    """
    try:
        import json

        from app.application.office_template_ingest_app_service import (
            attach_template_ingest_to_etl_result,
        )
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        try:
            from app.application.facades.session_facade import get_auth_service
            from app.infrastructure.auth.dependencies import resolve_session_user
            from app.utils.deployment import deployment_is_production, deployment_is_staging

            require_rbac = (
                _facade().os.environ.get("FHD_SHIPMENT_ETL_REQUIRE_RBAC", "").strip().lower()
            )
            if require_rbac == "":
                require_rbac_flag = deployment_is_production() or deployment_is_staging()
            else:
                require_rbac_flag = require_rbac in {"1", "true", "yes", "on"}
            sess_user = resolve_session_user(request)
            if require_rbac_flag:
                if sess_user is None:
                    return _facade().JSONResponse(
                        {"success": False, "message": "请先登录", "error_code": "unauthorized"},
                        status_code=401,
                    )
                if not get_auth_service().has_permission(sess_user, "shipment.create"):
                    return _facade().JSONResponse(
                        {
                            "success": False,
                            "message": "缺少 shipment.create 权限",
                            "error_code": "forbidden",
                        },
                        status_code=403,
                    )
            elif sess_user is not None and hasattr(get_auth_service(), "has_permission"):
                if not get_auth_service().has_permission(sess_user, "shipment.create"):
                    if _facade().os.environ.get(
                        "FHD_SHIPMENT_ETL_REQUIRE_RBAC", ""
                    ).strip().lower() in {"1", "true", "yes", "on"}:
                        return _facade().JSONResponse(
                            {
                                "success": False,
                                "message": "缺少 shipment.create 权限",
                                "error_code": "forbidden",
                            },
                            status_code=403,
                        )
        except _facade().RECOVERABLE_ERRORS:
            pass
        path = str(file_path or "").strip()
        if file is not None and (file.filename or "").strip():
            raw = await file.read()
            path = _facade()._temporary_upload_path(
                "etl_exec",
                str(file.filename or "shipment.xlsx"),
                {".xls", ".xlsm", ".xlsx"},
            )
            with open(path, "wb") as fh:
                fh.write(raw)
        notes = None
        raw_notes = str(notes_json or "").strip()
        if raw_notes:
            try:
                loaded = json.loads(raw_notes)
                if isinstance(loaded, list):
                    notes = loaded
                elif isinstance(loaded, dict) and isinstance(loaded.get("notes"), list):
                    notes = loaded.get("notes")
            except json.JSONDecodeError:
                return _facade().JSONResponse(
                    {
                        "success": False,
                        "message": "notes_json 不是合法 JSON",
                        "error_code": "bad_notes",
                    },
                    status_code=400,
                )
        if not path and notes is None:
            return _facade().JSONResponse(
                {"success": False, "message": "请上传文件、提供 file_path，或提交 notes_json"},
                status_code=400,
            )
        result = get_shipment_excel_etl_app_service().execute(
            path or "",
            import_products=_facade()._form_truthy(import_products, True),
            import_shipments=_facade()._form_truthy(import_shipments, True),
            idempotent=_facade()._form_truthy(idempotent, True),
            include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
            confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
            dry_run=_facade()._form_truthy(dry_run, False),
            direct=_facade()._form_truthy(direct, False),
            force_shipment_target=_facade()._form_truthy(force_shipment_target, False),
            notes=notes,
            workspace_root=str(workspace_root or "").strip() or None,
        )
        result = attach_template_ingest_to_etl_result(
            result,
            file_path=path,
            save_as_template=_facade()._form_truthy(save_as_template, False),
            template_name=str(template_name or "").strip(),
            template_scope=str(template_scope or "").strip(),
            source="shipment_excel_etl_execute",
        )
        status = 200 if result.get("success") or result.get("dry_run") else 400
        if result.get("error_code") == "unsafe_path":
            status = 400
        if result.get("error_code") == "ledger_confirm_required":
            status = 409
        if result.get("error_code") == "direct_execute_denied":
            status = 403
        result = _facade()._safe_failed_etl_result(result, "单据入库失败，请检查文件内容")
        return _facade().JSONResponse(result, status_code=status)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl execute failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "单据入库失败，请稍后重试"}, status_code=500
        )


@_facade().router.post("/shipment-etl/ocr-preview")
async def shipment_etl_ocr_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """扫描件/图片/PDF OCR → 表格 → 单据预览。"""
    try:
        from app.application.shipment_excel_etl_app_service import preview_shipment_excel_etl
        from app.application.shipment_excel_etl_ocr import parse_ocr_document

        path = str(file_path or "").strip()
        if file is not None and (file.filename or "").strip():
            raw = await file.read()
            path = _facade()._temporary_upload_path(
                "etl_ocr",
                str(file.filename or "scan.png"),
                {
                    ".bmp",
                    ".jpeg",
                    ".jpg",
                    ".pdf",
                    ".png",
                    ".tif",
                    ".tiff",
                    ".xls",
                    ".xlsm",
                    ".xlsx",
                },
            )
            with open(path, "wb") as fh:
                fh.write(raw)
        if not path:
            return _facade().JSONResponse(
                {"success": False, "message": "请上传扫描件或提供 file_path"}, status_code=400
            )
        suffix = _facade().Path(path).suffix.lower()
        if suffix in {".xlsx", ".xlsm", ".xls"}:
            result = preview_shipment_excel_etl(
                path,
                include_ledger=_facade()._form_include_ledger(include_ledger, default="auto"),
                workspace_root=str(workspace_root or "").strip() or None,
            )
        else:
            parsed = parse_ocr_document(
                path,
                include_ledger=_facade()._form_include_ledger(include_ledger, default="auto"),
                workspace_root=str(workspace_root or "").strip() or None,
            )
            if not parsed.get("success"):
                return _facade().JSONResponse(
                    _facade()._safe_failed_etl_result(parsed, "OCR 预览失败，请检查文件内容"),
                    status_code=400,
                )
            ocr_xlsx = (parsed.get("ocr") or {}).get("file_path") or ""
            if ocr_xlsx:
                preview = preview_shipment_excel_etl(
                    ocr_xlsx,
                    include_ledger=_facade()._form_include_ledger(include_ledger, default="auto"),
                    workspace_root=str(workspace_root or "").strip() or None,
                )
                result = {
                    **preview,
                    "ocr": parsed.get("ocr"),
                    "source_path": parsed.get("source_path"),
                }
            else:
                result = parsed
        status = 200 if result.get("success") else 400
        result = _facade()._safe_failed_etl_result(result, "OCR 预览失败，请检查文件内容")
        return _facade().JSONResponse(result, status_code=status)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl ocr-preview failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "OCR 预览失败，请稍后重试"}, status_code=500
        )


@_facade().router.post("/shipment-etl/batch-preview")
async def shipment_etl_batch_preview(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """批量预览目录内 xlsx 送货单/出货流水。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        root = str(directory or "").strip()
        if not root:
            return _facade().JSONResponse(
                {"success": False, "message": "缺少 directory"}, status_code=400
            )
        result = get_shipment_excel_etl_app_service().batch_preview(
            root,
            include_ledger=_facade()._form_include_ledger(include_ledger),
            workspace_root=str(workspace_root or "").strip() or None,
        )
        result = _facade()._safe_failed_etl_result(result, "批量预览失败，请检查目录内容")
        return _facade().JSONResponse(result, status_code=200 if result.get("success") else 400)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl batch preview failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "批量预览失败，请稍后重试"}, status_code=500
        )


@_facade().router.post("/shipment-etl/batch-execute")
async def shipment_etl_batch_execute(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    idempotent: str = _facade().Form("1"),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    dry_run: str = _facade().Form("0"),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """批量执行目录内 xlsx 闭环入库（默认关闭，需 FHD_SHIPMENT_ETL_ALLOW_BATCH=1）。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )

        root = str(directory or "").strip()
        if not root:
            return _facade().JSONResponse(
                {"success": False, "message": "缺少 directory"}, status_code=400
            )
        result = get_shipment_excel_etl_app_service().batch_execute(
            root,
            include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
            confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
            idempotent=_facade()._form_truthy(idempotent, True),
            import_products=_facade()._form_truthy(import_products, True),
            import_shipments=_facade()._form_truthy(import_shipments, True),
            dry_run=_facade()._form_truthy(dry_run, False),
            workspace_root=str(workspace_root or "").strip() or None,
        )
        status = 200 if result.get("success") or result.get("dry_run") else 400
        if result.get("error_code") == "batch_disabled":
            status = 403
        result = _facade()._safe_failed_etl_result(result, "批量入库失败，请检查目录内容")
        return _facade().JSONResponse(result, status_code=status)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl batch execute failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "批量入库失败，请稍后重试"}, status_code=500
        )
