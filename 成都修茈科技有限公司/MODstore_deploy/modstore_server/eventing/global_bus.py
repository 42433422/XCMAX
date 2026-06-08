"""Process-local NeuroBus instance (memory | rabbitmq) + optional shadow dual-write.

Bus backend is controlled by ``MODSTORE_BUS``:
  - ``memory`` (default): in-process, synchronous — suitable for single-instance dev/test.
  - ``rabbitmq`` / ``rmq`` / ``amqp``: durable async via RabbitMQ — recommended for production.

Shadow bus (for greyscale cutover):
  - Set ``MODSTORE_BUS_SHADOW=rabbitmq`` to dual-write events to a secondary RabbitMQ bus
    while keeping memory as the primary.

Dead-letter alerting:
  - The ``OutboxDeadLetter`` table receives rows when the outbox worker exhausts retries.
  - ``_alert_dead_letters()`` is called at startup and logs an error if the table is non-empty,
    enabling log-based alerts or health-check scrapers to surface stuck events.
"""

from __future__ import annotations

import logging
import os

from modstore_server.eventing.bus import InMemoryNeuroBus, NeuroBus
from modstore_server.eventing.events import DomainEvent

from .outbox import FileEventOutbox

logger = logging.getLogger(__name__)


def _build_primary_bus() -> NeuroBus:
    raw = (os.environ.get("MODSTORE_BUS") or "memory").strip().lower()
    if raw in ("rabbitmq", "rmq", "amqp"):
        try:
            from modstore_server.eventing.rabbitmq_bus import RabbitMqNeuroBus

            bus = RabbitMqNeuroBus()
            logger.info(
                "NeuroBus primary backend: RabbitMqNeuroBus (connected=%s)",
                getattr(bus, "_connected", False),
            )
            return bus
        except Exception:  # noqa: BLE001
            logger.exception("MODSTORE_BUS=%s but rabbitmq bus init failed; using memory", raw)
    logger.info("NeuroBus primary backend: InMemoryNeuroBus (MODSTORE_BUS=%s)", raw)
    return InMemoryNeuroBus()


class _ShadowNeuroBus(NeuroBus):
    """Writes to primary then best-effort secondary (for greyscale cutover)."""

    def __init__(self, primary: NeuroBus, secondary: NeuroBus) -> None:
        self._primary = primary
        self._secondary = secondary

    def subscribe(self, event_name: str, handler) -> None:
        self._primary.subscribe(event_name, handler)
        try:
            self._secondary.subscribe(event_name, handler)
        except Exception:  # noqa: BLE001
            logger.debug("shadow subscribe failed on secondary", exc_info=True)

    def publish(self, event: DomainEvent) -> None:
        self._primary.publish(event)
        try:
            self._secondary.publish(event)
        except Exception:  # noqa: BLE001
            logger.warning("shadow publish failed on secondary bus", exc_info=True)


def _build_bus() -> NeuroBus:
    primary = _build_primary_bus()
    shadow = (os.environ.get("MODSTORE_BUS_SHADOW") or "").strip().lower()
    if not shadow or shadow in ("0", "false", "no", "off"):
        return primary
    try:
        from modstore_server.eventing.rabbitmq_bus import RabbitMqNeuroBus

        secondary = RabbitMqNeuroBus()
    except Exception:  # noqa: BLE001
        secondary = InMemoryNeuroBus()
    return _ShadowNeuroBus(primary, secondary)


neuro_bus: NeuroBus = _build_bus()
event_outbox = FileEventOutbox()
neuro_bus.subscribe("*", event_outbox.append)


def _alert_dead_letters() -> None:
    """Log an error if OutboxDeadLetter contains unprocessed rows.

    Call this at application startup so log-based monitors or health-check
    scrapers surface stuck events without a dedicated polling job.
    """
    try:
        from modstore_server.models import OutboxDeadLetter, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            count = session.query(OutboxDeadLetter).count()
        if count > 0:
            logger.error(
                "DEAD_LETTER_ALERT: %d unprocessed dead-letter events in OutboxDeadLetter table. "
                "Investigate and replay or purge via admin API.",
                count,
            )
    except Exception:
        logger.debug("dead-letter check skipped (db not ready or table missing)", exc_info=True)


_alert_dead_letters()
