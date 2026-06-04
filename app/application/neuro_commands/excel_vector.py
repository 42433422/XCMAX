"""excel_vector neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.ai_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_excel_vector_instance: ExcelVectorAppServiceV2 | None = None


class ExcelVectorAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "ai"
    event_source = "excelvectorappservice_v2"


instrument_application_service_class(
    ExcelVectorAppServiceV2, service_name="ExcelVectorAppServiceV2"
)


def get_excel_vector_app_service_v2() -> ExcelVectorAppServiceV2:
    global _excel_vector_instance
    if _excel_vector_instance is None:
        _excel_vector_instance = ExcelVectorAppServiceV2()
    return _excel_vector_instance
