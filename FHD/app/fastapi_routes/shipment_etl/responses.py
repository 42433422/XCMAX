"""Public ETL failures expose stable codes and counts, never backend exceptions."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastapi.responses import JSONResponse

from app.fastapi_routes.shipment_etl.ports import Payload

PUBLIC_ETL_ERRORS = {
    "unsafe_path": "非法文件路径",
    "missing_path": "缺少文件路径",
    "missing_file": "文件不存在",
    "not_ocr_source": "不支持的 OCR 文件类型",
    "ocr_empty": "OCR 未识别到有效内容",
    "ocr_grid_empty": "OCR 内容无法识别为表格",
    "ocr_failed": "OCR 处理失败，请稍后重试",
    "ledger_confirm_required": "检测到出货流水，请确认客户归属后再入库",
    "direct_execute_denied": "无预览直写未开启",
    "batch_disabled": "批量入库功能未开启",
    "batch_too_large": "批量文件过多，请缩小范围",
    "no_delivery_notes": "没有可导入的单据",
    "unsupported_profile_target": "识别到不支持直接入库的模板",
    "product_import_failed": "客户或产品导入失败，已中止发货单写入",
}


def safe_failed_result(
    result: Payload, fallback: str, *, errors: Mapping[str, str] = PUBLIC_ETL_ERRORS
) -> Payload:
    if result.get("success"):
        return result
    requested_code = str(result.get("error_code") or "").strip()
    error_code = requested_code if requested_code in errors else "operation_failed"
    payload: Payload = {
        "success": False,
        "message": errors.get(error_code, fallback),
        "error_code": error_code,
    }
    for key in (
        "note_count",
        "ledger_note_count",
        "shipment_created",
        "shipment_failed",
        "shipment_skipped",
        "would_create",
        "would_skip",
        "safe_to_retry",
        "closed_loop",
    ):
        value = result.get(key)
        if isinstance(value, (bool, int)):
            payload[key] = value
    return payload


@dataclass(frozen=True)
class EtlResponses:
    sanitize: Callable[[Payload, str], Payload]
    logger: logging.Logger

    def result(
        self, payload: Payload, fallback: str, *, error_status: dict[str, int] | None = None
    ) -> JSONResponse:
        status = 200 if payload.get("success") else 400
        if error_status:
            status = error_status.get(str(payload.get("error_code") or ""), status)
        return JSONResponse(self.sanitize(payload, fallback), status_code=status)

    def unavailable(self, event: str, message: str) -> JSONResponse:
        self.logger.exception(event)
        return JSONResponse({"success": False, "message": message}, status_code=500)
