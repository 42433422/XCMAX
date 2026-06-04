"""print neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.print_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_print_instance: PrintAppServiceV2 | None = None


class PrintAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "print"
    event_source = "printappservice_v2"


instrument_application_service_class(PrintAppServiceV2, service_name="PrintAppServiceV2")


def get_print_app_service_v2() -> PrintAppServiceV2:
    global _print_instance
    if _print_instance is None:
        _print_instance = PrintAppServiceV2()
    return _print_instance
