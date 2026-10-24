"""Coordinate preview, import and template capture through the existing ETL application."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.shipment_etl.ports import (
    ShipmentApplication,
    TemplateCapture,
    TemplateIngest,
)
from app.fastapi_routes.shipment_etl.responses import EtlResponses
from app.fastapi_routes.shipment_etl.uploads import UploadStager
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentImports:
    def __init__(
        self,
        service: Callable[[], ShipmentApplication],
        capture: TemplateIngest,
        uploads: UploadStager,
        responses: EtlResponses,
    ) -> None:
        self._service = service
        self._capture = capture
        self._uploads = uploads
        self._responses = responses

    async def preview(
        self,
        file: UploadFile | None,
        file_path: str,
        workspace_root: str | None,
        include_ledger: bool | str,
        template: TemplateCapture,
    ) -> JSONResponse:
        try:
            async with self._uploads.open(file, file_path, prefix="etl") as staged:
                if not staged.path:
                    return JSONResponse(
                        {"success": False, "message": "请上传文件或提供 file_path"}, status_code=400
                    )
                result = self._service().preview(
                    staged.path, include_ledger=include_ledger, workspace_root=workspace_root
                )
                if staged.uploaded:
                    result["uploaded_temp_path"] = staged.path
                result = self._capture(
                    result,
                    file_path=staged.path,
                    save_as_template=template.enabled,
                    template_name=template.name,
                    template_scope=template.scope,
                    source="shipment_excel_etl_preview",
                )
                response = self._responses.result(result, "单据预览失败，请检查文件内容")
                staged.retained = bool(result.get("success"))
                return response
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl preview failed", "单据预览失败，请稍后重试"
            )

    async def execute(
        self,
        file: UploadFile | None,
        file_path: str,
        workspace_root: str | None,
        notes_json: str,
        *,
        import_products: bool,
        import_shipments: bool,
        idempotent: bool,
        include_ledger: bool | str,
        confirm_ledger: bool,
        dry_run: bool,
        direct: bool,
        force_shipment_target: bool,
        template: TemplateCapture,
    ) -> JSONResponse:
        try:
            async with self._uploads.open(file, file_path, prefix="etl_exec") as staged:
                notes = None
                raw_notes = str(notes_json or "").strip()
                if raw_notes:
                    try:
                        loaded = json.loads(raw_notes)
                        if isinstance(loaded, list):
                            notes = loaded
                        elif isinstance(loaded, dict) and isinstance(loaded.get("notes"), list):
                            notes = loaded["notes"]
                    except json.JSONDecodeError:
                        return JSONResponse(
                            {
                                "success": False,
                                "message": "notes_json 不是合法 JSON",
                                "error_code": "bad_notes",
                            },
                            status_code=400,
                        )
                if not staged.path and notes is None:
                    return JSONResponse(
                        {
                            "success": False,
                            "message": "请上传文件、提供 file_path，或提交 notes_json",
                        },
                        status_code=400,
                    )
                result = self._service().execute(
                    staged.path,
                    import_products=import_products,
                    import_shipments=import_shipments,
                    idempotent=idempotent,
                    include_ledger=include_ledger,
                    confirm_ledger=confirm_ledger,
                    dry_run=dry_run,
                    direct=direct,
                    force_shipment_target=force_shipment_target,
                    notes=notes,
                    workspace_root=workspace_root,
                )
                result = self._capture(
                    result,
                    file_path=staged.path,
                    save_as_template=template.enabled,
                    template_name=template.name,
                    template_scope=template.scope,
                    source="shipment_excel_etl_execute",
                )
                response = self._responses.result(
                    result,
                    "单据入库失败，请检查文件内容",
                    error_status={
                        "unsafe_path": 400,
                        "ledger_confirm_required": 409,
                        "direct_execute_denied": 403,
                    },
                )
                staged.retained = bool(result.get("success"))
                return response
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl execute failed", "单据入库失败，请稍后重试"
            )

    def batch_preview(
        self,
        directory: str,
        workspace_root: str | None,
        include_ledger: bool | str,
    ) -> JSONResponse:
        try:
            root = str(directory or "").strip()
            if not root:
                return JSONResponse(
                    {"success": False, "message": "缺少 directory"}, status_code=400
                )
            result = self._service().batch_preview(
                root, include_ledger=include_ledger, workspace_root=workspace_root
            )
            return self._responses.result(result, "批量预览失败，请检查目录内容")
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl batch preview failed", "批量预览失败，请稍后重试"
            )

    def batch_execute(
        self,
        directory: str,
        workspace_root: str | None,
        *,
        include_ledger: bool | str,
        confirm_ledger: bool,
        idempotent: bool,
        import_products: bool,
        import_shipments: bool,
        dry_run: bool,
    ) -> JSONResponse:
        try:
            root = str(directory or "").strip()
            if not root:
                return JSONResponse(
                    {"success": False, "message": "缺少 directory"}, status_code=400
                )
            result = self._service().batch_execute(
                root,
                include_ledger=include_ledger,
                confirm_ledger=confirm_ledger,
                idempotent=idempotent,
                import_products=import_products,
                import_shipments=import_shipments,
                dry_run=dry_run,
                workspace_root=workspace_root,
            )
            return self._responses.result(
                result, "批量入库失败，请检查目录内容", error_status={"batch_disabled": 403}
            )
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl batch execute failed", "批量入库失败，请稍后重试"
            )
