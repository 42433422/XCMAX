from __future__ import annotations

from pathlib import Path

from app.fastapi_routes import excel_extract as _excel_extract  # noqa: F401
from app.fastapi_routes.excel_extract_shipment import (
    _safe_failed_etl_result,
    _temporary_upload_path,
)


def test_etl_failure_boundary_drops_internal_exception_text() -> None:
    result = _safe_failed_etl_result(
        {
            "success": False,
            "message": "Traceback: password=secret",
            "error": "private/internal.py:42",
            "error_code": "unknown_internal_error",
            "shipment_failed": 2,
        },
        "单据处理失败",
    )

    assert result == {
        "success": False,
        "message": "单据处理失败",
        "error_code": "operation_failed",
        "shipment_failed": 2,
    }


def test_temporary_upload_path_ignores_untrusted_filename() -> None:
    path = Path(
        _temporary_upload_path("etl", "../../private/customer-secret.xlsx", {".xls", ".xlsx"})
    )

    assert path.parent.name == "temp_excel"
    assert path.name.startswith("etl_")
    assert path.suffix == ".xlsx"
    assert "customer-secret" not in path.name
