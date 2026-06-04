"""template neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.print_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_template_instance: TemplateAppServiceV2 | None = None


class TemplateAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "print"
    event_source = "templateappservice_v2"


instrument_application_service_class(TemplateAppServiceV2, service_name="TemplateAppServiceV2")


def get_template_app_service_v2() -> TemplateAppServiceV2:
    global _template_instance
    if _template_instance is None:
        _template_instance = TemplateAppServiceV2()
    return _template_instance
