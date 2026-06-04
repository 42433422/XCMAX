"""Shared NeuroBus command publishing for neuro_commands services."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.neuro_bus.bus import get_neuro_bus

logger = logging.getLogger(__name__)


class NeuroCommandServiceBase:
    """Publishes domain commands as NeuroBus events (ex-V2 ``execute_command`` pattern)."""

    correlation_prefix: str = "neuro"
    event_source: str = "neuro_command"

    def __init__(self) -> None:
        self._bus = get_neuro_bus()

    def _create_correlation_id(self) -> str:
        return f"{self.correlation_prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id(self)}"

    async def execute_command(self, command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.neuro_bus.events.base import NeuroEvent

            correlation_id = self._create_correlation_id()
            event_type = f"{self.correlation_prefix}.{command_type}"
            event = NeuroEvent(
                event_type=event_type,
                payload=payload,
                source=self.event_source,
                correlation_id=correlation_id,
            )
            self._bus.publish(event)
            logger.info(
                "[%s] command published: %s (event_id=%s)",
                self.__class__.__name__,
                command_type,
                event.metadata.event_id,
            )
            return {
                "success": True,
                "event_id": event.metadata.event_id,
                "correlation_id": correlation_id,
                "message": f"{command_type} 命令已提交",
            }
        except Exception as exc:
            logger.exception("[%s] execute_command failed: %s", self.__class__.__name__, exc)
            return {"success": False, "message": str(exc)}

    def _try_publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Best-effort publish for sync services that delegate to legacy layers."""
        try:
            from app.neuro_bus.events.base import EventPriority, NeuroEvent

            correlation_id = f"{self.correlation_prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            event = NeuroEvent(
                event_type=event_type,
                payload=payload,
                source=self.event_source,
                correlation_id=correlation_id,
                priority=EventPriority.NORMAL,
            )
            self._bus.publish(event)
        except Exception as exc:
            logger.warning("[%s] event publish skipped: %s", self.__class__.__name__, exc)

    def _publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        priority: Any = None,
        correlation_id: str | None = None,
    ):
        """Publish a typed domain event; returns the event or None on failure."""
        try:
            from app.neuro_bus.events.base import EventPriority, NeuroEvent

            prio = priority if priority is not None else EventPriority.NORMAL
            cid = correlation_id or self._create_correlation_id()
            event = NeuroEvent(
                event_type=event_type,
                payload=payload,
                source=self.event_source,
                correlation_id=cid,
                priority=prio,
            )
            self._bus.publish(event)
            return event
        except Exception as exc:
            logger.error("[%s] publish failed: %s", self.__class__.__name__, exc)
            return None
