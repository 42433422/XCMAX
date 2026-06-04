"""user_preference neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.auth_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_user_preference_instance: UserPreferenceAppServiceV2 | None = None


class UserPreferenceAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "auth"
    event_source = "userpreferenceappservice_v2"


instrument_application_service_class(
    UserPreferenceAppServiceV2, service_name="UserPreferenceAppServiceV2"
)


def get_user_preference_app_service_v2() -> UserPreferenceAppServiceV2:
    global _user_preference_instance
    if _user_preference_instance is None:
        _user_preference_instance = UserPreferenceAppServiceV2()
    return _user_preference_instance
