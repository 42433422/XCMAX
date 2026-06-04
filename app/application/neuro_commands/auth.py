"""
Auth neuro command service — NeuroBus event-driven sidecar.

HTTP / legacy auth flows remain on ``auth_app_service`` (V1).
"""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_auth_instance: AuthAppServiceV2 | None = None


class AuthAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "auth"
    event_source = "authappservice_v2"


instrument_application_service_class(AuthAppServiceV2, service_name="AuthAppServiceV2")


def get_auth_app_service_v2() -> AuthAppServiceV2:
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = AuthAppServiceV2()
    return _auth_instance
