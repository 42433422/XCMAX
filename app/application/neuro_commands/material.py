"""material neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.material_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_material_instance: MaterialAppServiceV2 | None = None


class MaterialAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "material"
    event_source = "materialappservice_v2"


instrument_application_service_class(MaterialAppServiceV2, service_name="MaterialAppServiceV2")


def get_material_app_service_v2() -> MaterialAppServiceV2:
    global _material_instance
    if _material_instance is None:
        _material_instance = MaterialAppServiceV2()
    return _material_instance
