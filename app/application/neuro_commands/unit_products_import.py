"""unit_products_import neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.product_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_unit_products_import_instance: UnitProductsImportAppServiceV2 | None = None


class UnitProductsImportAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "product"
    event_source = "unitproductsimportappservice_v2"


instrument_application_service_class(
    UnitProductsImportAppServiceV2, service_name="UnitProductsImportAppServiceV2"
)


def get_unit_products_import_app_service_v2() -> UnitProductsImportAppServiceV2:
    global _unit_products_import_instance
    if _unit_products_import_instance is None:
        _unit_products_import_instance = UnitProductsImportAppServiceV2()
    return _unit_products_import_instance
