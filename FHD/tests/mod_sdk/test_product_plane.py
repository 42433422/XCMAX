from __future__ import annotations

from app.mod_sdk.product_plane import (
    automatic_employee_runtime_enabled,
    employee_execution_block_reason,
    employee_pack_allowed_in_runtime,
)


def test_enterprise_client_blocks_control_plane_employees(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    manifest = {
        "id": "daily-orchestrator",
        "employee_config_v2": {"identity": {"owner": "admin", "area": "platform-core"}},
    }

    assert automatic_employee_runtime_enabled() is False
    assert employee_pack_allowed_in_runtime("daily-orchestrator", manifest) is False
    assert employee_execution_block_reason("daily-orchestrator", manifest)


def test_non_enterprise_runtime_keeps_control_plane_available(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")

    assert automatic_employee_runtime_enabled() is True
    assert employee_pack_allowed_in_runtime("daily-orchestrator", {"id": "daily-orchestrator"})
