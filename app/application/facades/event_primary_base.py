"""
Shared CommandGateway dispatch for event-primary application facades.

HTTP mutation paths publish NeuroEvents and await handler results via CommandGateway.
When the bus is unavailable, callers should fall back to the synchronous core service.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.neuro_async_bridge import run_coroutine_on_neuro_loop
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.command_gateway import get_command_gateway
from app.neuro_bus.events.base import EventPriority, NeuroEvent

logger = logging.getLogger(__name__)

_BUS_UNAVAILABLE_MARKERS = (
    "NeuroBus 未运行",
    "无法入队",
    "发货操作超时",
    "操作超时",
)


class EventPrimaryDispatcher:
    """Publish a command event and block until the domain handler resolves the future."""

    def __init__(self, *, default_timeout: float = 120.0) -> None:
        self._default_timeout = default_timeout

    async def dispatch_command(
        self, event_type: str, payload: dict, timeout: float | None = None
    ) -> Any:
        gw = get_command_gateway()
        bus = get_neuro_bus()
        evt = NeuroEvent(
            event_type=event_type, payload=dict(payload), priority=EventPriority.HIGH
        )
        rid = gw.prepare_command_event(evt)
        if not bus.publish(evt):
            gw.cancel_pending(rid)
            return {"success": False, "message": "NeuroBus 未运行或无法入队"}
        try:
            return await gw.wait_for_result(rid, timeout=timeout or self._default_timeout)
        except TimeoutError:
            return {"success": False, "message": "操作超时"}

    def run_command(self, coro) -> Any:
        try:
            return run_coroutine_on_neuro_loop(coro, timeout=self._default_timeout)
        except TimeoutError:
            return {"success": False, "message": "操作超时"}
        except Exception as e:
            logger.exception("event-primary command failed: %s", e)
            return {"success": False, "message": str(e)}

    @staticmethod
    def should_fallback_to_core(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("success") is True:
            return False
        msg = str(result.get("message") or "")
        return any(marker in msg for marker in _BUS_UNAVAILABLE_MARKERS)

    def run_command_with_fallback(
        self,
        coro,
        fallback: Callable[[], Any],
        *,
        log_label: str = "event-primary",
    ) -> Any:
        result = self.run_command(coro)
        if self.should_fallback_to_core(result):
            logger.warning("%s: NeuroBus unavailable, falling back to core", log_label)
            return fallback()
        return result
