"""product_import neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.product_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_product_import_instance: ProductImportAppServiceV2 | None = None


class ProductImportAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "product"
    event_source = "productimportappservice_v2"


instrument_application_service_class(
    ProductImportAppServiceV2, service_name="ProductImportAppServiceV2"
)


def get_product_import_app_service_v2() -> ProductImportAppServiceV2:
    global _product_import_instance
    if _product_import_instance is None:
        _product_import_instance = ProductImportAppServiceV2()
    return _product_import_instance
