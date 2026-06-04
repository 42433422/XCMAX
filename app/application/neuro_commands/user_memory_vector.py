"""user_memory_vector neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.auth_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_user_memory_vector_instance: UserMemoryVectorAppServiceV2 | None = None


class UserMemoryVectorAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "auth"
    event_source = "usermemoryvectorappservice_v2"


instrument_application_service_class(
    UserMemoryVectorAppServiceV2, service_name="UserMemoryVectorAppServiceV2"
)


def get_user_memory_vector_app_service_v2() -> UserMemoryVectorAppServiceV2:
    global _user_memory_vector_instance
    if _user_memory_vector_instance is None:
        _user_memory_vector_instance = UserMemoryVectorAppServiceV2()
    return _user_memory_vector_instance
