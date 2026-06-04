"""wechat_contact neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.wechat_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_wechat_contact_instance: WechatContactAppServiceV2 | None = None


class WechatContactAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "wechat"
    event_source = "wechatcontactappservice_v2"


instrument_application_service_class(
    WechatContactAppServiceV2, service_name="WechatContactAppServiceV2"
)


def get_wechat_contact_app_service_v2() -> WechatContactAppServiceV2:
    global _wechat_contact_instance
    if _wechat_contact_instance is None:
        _wechat_contact_instance = WechatContactAppServiceV2()
    return _wechat_contact_instance
