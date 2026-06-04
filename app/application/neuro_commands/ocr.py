"""ocr neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.ocr_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_ocr_instance: OcrAppServiceV2 | None = None


class OcrAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "ocr"
    event_source = "ocrappservice_v2"


instrument_application_service_class(OcrAppServiceV2, service_name="OcrAppServiceV2")


def get_ocr_app_service_v2() -> OcrAppServiceV2:
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = OcrAppServiceV2()
    return _ocr_instance
