"""conversation neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.conversation_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_conversation_instance: ConversationAppServiceV2 | None = None


class ConversationAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "conversation"
    event_source = "conversationappservice_v2"


instrument_application_service_class(
    ConversationAppServiceV2, service_name="ConversationAppServiceV2"
)


def get_conversation_app_service_v2() -> ConversationAppServiceV2:
    global _conversation_instance
    if _conversation_instance is None:
        _conversation_instance = ConversationAppServiceV2()
    return _conversation_instance
