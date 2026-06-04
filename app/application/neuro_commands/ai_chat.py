"""ai_chat neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.ai_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_ai_chat_instance: AiChatAppServiceV2 | None = None


class AiChatAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "ai"
    event_source = "aichatappservice_v2"


instrument_application_service_class(AiChatAppServiceV2, service_name="AiChatAppServiceV2")


def get_ai_chat_app_service_v2() -> AiChatAppServiceV2:
    global _ai_chat_instance
    if _ai_chat_instance is None:
        _ai_chat_instance = AiChatAppServiceV2()
    return _ai_chat_instance
