"""user neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.auth_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_user_instance: UserAppServiceV2 | None = None


class UserAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "auth"
    event_source = "userappservice_v2"


instrument_application_service_class(UserAppServiceV2, service_name="UserAppServiceV2")


def get_user_app_service_v2() -> UserAppServiceV2:
    global _user_instance
    if _user_instance is None:
        _user_instance = UserAppServiceV2()
    return _user_instance
