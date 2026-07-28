from __future__ import annotations

from typing import Any

_EXPORTS = {
    "InventoryService": ("app.services.inventory_service", "InventoryService"),
    "PurchaseService": ("app.services.purchase_service", "PurchaseService"),
    "ReportService": ("app.services.report_service", "ReportService"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc

    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
