"""extract_log neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_extract_log_instance: ExtractLogAppServiceV2 | None = None


class ExtractLogAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "log"
    event_source = "extractlogappservice_v2"


instrument_application_service_class(ExtractLogAppServiceV2, service_name="ExtractLogAppServiceV2")


def get_extract_log_app_service_v2() -> ExtractLogAppServiceV2:
    global _extract_log_instance
    if _extract_log_instance is None:
        _extract_log_instance = ExtractLogAppServiceV2()
    return _extract_log_instance
