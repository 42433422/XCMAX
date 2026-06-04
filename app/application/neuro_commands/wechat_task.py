"""wechat_task neuro command service — NeuroBus event-driven sidecar."""

from __future__ import annotations

from app.application.neuro_commands._base import NeuroCommandServiceBase
from app.neuro_bus.events.wechat_events import *
from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

_wechat_task_instance: WechatTaskAppServiceV2 | None = None


class WechatTaskAppServiceV2(NeuroCommandServiceBase):
    correlation_prefix = "wechat"
    event_source = "wechattaskappservice_v2"


instrument_application_service_class(WechatTaskAppServiceV2, service_name="WechatTaskAppServiceV2")


def get_wechat_task_app_service_v2() -> WechatTaskAppServiceV2:
    global _wechat_task_instance
    if _wechat_task_instance is None:
        _wechat_task_instance = WechatTaskAppServiceV2()
    return _wechat_task_instance
