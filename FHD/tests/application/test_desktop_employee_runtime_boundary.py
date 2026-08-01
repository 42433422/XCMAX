from __future__ import annotations

from fastapi import FastAPI

from app.application.employee_runtime import triggers
from app.application.employee_runtime.runtime_policy import (
    desktop_admin_employee_runtime_disabled,
)
from app.application.employee_runtime.scheduler import start_employee_scheduler
from app.fastapi_app.lifespan import _init_employee_runtime_async
from app.mod_sdk import employee_runtime


def _desktop_enterprise(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")


def test_desktop_product_boundary_disables_management_employee_scans(monkeypatch) -> None:
    _desktop_enterprise(monkeypatch)
    monkeypatch.setattr(
        triggers,
        "list_installed_pack_records",
        lambda: (_ for _ in ()).throw(AssertionError("desktop must not scan management employees")),
    )

    assert desktop_admin_employee_runtime_disabled() is True
    assert triggers.refresh_employee_triggers()["disabled_reason"] == "desktop_product_boundary"
    assert employee_runtime.warm_employee_tool_registry()["registered_tool_count"] == 0
    assert start_employee_scheduler()["disabled_reason"] == "desktop_product_boundary"


async def test_desktop_lifespan_does_not_start_management_employee_runtime(monkeypatch) -> None:
    _desktop_enterprise(monkeypatch)
    app = FastAPI()

    await _init_employee_runtime_async(app)

    assert app.state.employee_triggers["registered"] == []
    assert app.state.employee_scheduler["running"] is False
    assert app.state.employee_scheduler["disabled_reason"] == "desktop_product_boundary"
