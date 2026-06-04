"""file_analysis neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.ai_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_file_analysis_instance: FileAnalysisAppServiceV2 | None = None


class FileAnalysisAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "ai"
    event_source = "fileanalysisappservice_v2"


instrument_application_service_class(
    FileAnalysisAppServiceV2, service_name="FileAnalysisAppServiceV2"
)


def get_file_analysis_app_service_v2() -> FileAnalysisAppServiceV2:
    global _file_analysis_instance
    if _file_analysis_instance is None:
        _file_analysis_instance = FileAnalysisAppServiceV2()
    return _file_analysis_instance
