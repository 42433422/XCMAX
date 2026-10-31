"""OCR preview selects spreadsheet parsing without exposing write operations."""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import JSONResponse

from app.application.shipment_etl.protocols import DocumentPreview
from app.fastapi_routes.shipment_etl.responses import EltResponses
from app.fastapi_routes.shipment_etl.uploads import OCR_SUFFIXES, SPREADSHEET_SUFFIXES, UploadStager
from app.utils.operational_errors import RECOVERABLE_ERRORS


class OcrPreview:
    def __init__(
        self,
        parse: DocumentPreview,
        preview: DocumentPreview,
        uploads: UploadStager,
        responses: EltResponses,
    ) -> None:
        self._parse = parse
        self._preview = preview
        self._uploads = uploads
        self._responses = responses

    async def run(
        self,
        file: UploadFile | None,
        file_path: str,
        workspace_root: str | None,
        include_ledger: bool | str,
    ) -> JSONResponse:
        try:
            async with self._uploads.open(
                file, file_path, prefix="etl_ocr", suffixes=OCR_SUFFIXES
            ) as staged:
                if not staged.path:
                    return JSONResponse(
                        {"success": False, "message": "请上传扫描件或提供 file_path"},
                        status_code=400,
                    )
                if Path(staged.path).suffix.lower() in SPREADSHEET_SUFFIXES:
                    result = self._preview(
                        staged.path, include_ledger=include_ledger, workspace_root=workspace_root
                    )
                else:
                    parsed = self._parse(
                        staged.path, include_ledger=include_ledger, workspace_root=workspace_root
                    )
                    if not parsed.get("success"):
                        return self._responses.result(parsed, "OCR 预览失败，请检查文件内容")
                    ocr_xlsx = (parsed.get("ocr") or {}).get("file_path") or ""
                    if ocr_xlsx:
                        preview = self._preview(
                            ocr_xlsx, include_ledger=include_ledger, workspace_root=workspace_root
                        )
                        result = {
                            **preview,
                            "ocr": parsed.get("ocr"),
                            "source_path": parsed.get("source_path"),
                        }
                    else:
                        result = parsed
                response = self._responses.result(result, "OCR 预览失败，请检查文件内容")
                staged.retained = bool(result.get("success"))
                return response
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl ocr-preview failed", "OCR 预览失败，请稍后重试"
            )
