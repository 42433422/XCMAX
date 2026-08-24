from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.fastapi_routes.etl import _feature_gate


def _assert_gate_error(code: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _feature_gate()
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == code


def test_etl_feature_gate_rejects_disabled_center(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "0")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")

    _assert_gate_error("ETL_CENTER_DISABLED")


def test_etl_feature_gate_allows_enterprise_sku(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")

    _feature_gate()


def test_etl_feature_gate_allows_deliberate_generic_platform_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "true")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "generic")
    monkeypatch.setenv("XCAGI_GENERIC_EDITION", "yes")
    monkeypatch.setenv("XCAGI_PLATFORM_SHELL", "on")

    _feature_gate()


@pytest.mark.parametrize(
    ("sku", "generic", "shell"),
    [
        ("personal", "0", "1"),
        ("generic", "0", "1"),
        ("generic", "1", "0"),
        ("", "1", "1"),
    ],
)
def test_etl_feature_gate_keeps_non_enterprise_editions_blocked(
    monkeypatch: pytest.MonkeyPatch,
    sku: str,
    generic: str,
    shell: str,
) -> None:
    monkeypatch.setenv("FHD_ETL_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    monkeypatch.setenv("XCAGI_GENERIC_EDITION", generic)
    monkeypatch.setenv("XCAGI_PLATFORM_SHELL", shell)

    _assert_gate_error("ETL_ENTERPRISE_REQUIRED")
