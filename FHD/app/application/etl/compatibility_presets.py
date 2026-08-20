"""Validation for read-only legacy ETL compatibility presets."""

from __future__ import annotations

from app.application.etl.errors import EtlError
from app.utils.operational_errors import RECOVERABLE_ERRORS


def validate_compatibility_preset(
    preset_id: str,
    *,
    target_type: str,
    upload_suffix: str,
) -> None:
    if target_type not in {
        "customer_products",
        "customers",
        "products",
        "shipment_records",
    }:
        raise EtlError(
            "ETL_COMPATIBILITY_PRESET_TARGET_MISMATCH",
            "兼容预设仅适用于客户、产品、客户及产品或发货记录",
        )
    if upload_suffix not in {".xlsx", ".xlsm"}:
        raise EtlError(
            "ETL_COMPATIBILITY_PRESET_FILE_UNSUPPORTED",
            "兼容预设仅适用于 XLSX/XLSM 文件；其他文件请选择自动识别",
        )
    try:
        from app.application.shipment_etl_profile import list_profiles

        available = {
            str(item.get("id") or "").strip() for item in list_profiles() if isinstance(item, dict)
        }
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - fail closed if the registry is unavailable
        raise EtlError(
            "ETL_COMPATIBILITY_PRESET_UNAVAILABLE",
            "兼容预设暂时不可用，请选择自动识别",
            status_code=503,
        ) from exc
    if preset_id not in available:
        raise EtlError(
            "ETL_COMPATIBILITY_PRESET_NOT_FOUND",
            "兼容预设不存在或已失效，请刷新后重试",
            status_code=404,
        )
