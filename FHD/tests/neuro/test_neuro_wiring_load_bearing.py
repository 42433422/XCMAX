"""Load-bearing guard: the NeuroBus write spine must stay wired.

The bus is only "insurance" while its handlers are actually subscribed. These
assertions fail CI if the shipment command handlers or the durable
application-event consumers are silently un-registered — the failure mode that
let production loops stall unnoticed. Pairs with the event-primary fail-safe in
``shipment_event_primary.py`` (degrade to core when the bus is down).
"""

from __future__ import annotations

from app.neuro_bus.bus import NeuroBus


def _fresh_bus_with_core_wiring() -> NeuroBus:
    from app.neuro_bus.domains.application_event_consumers import (
        register_application_event_consumers,
    )
    from app.neuro_bus.domains.shipment_domain_handlers import (
        register_shipment_domain_handlers,
    )

    bus = NeuroBus()
    register_shipment_domain_handlers(bus)
    register_application_event_consumers(bus)
    return bus


def test_shipment_command_handlers_subscribed() -> None:
    """The four event-primary command paths must each have a live subscriber."""
    bus = _fresh_bus_with_core_wiring()
    for event_type in (
        "shipment.created",
        "shipment.cancelled",
        "shipment.deleted",
        "shipment.printed",
    ):
        assert bus._handlers.get(event_type), f"no handler subscribed for {event_type}"


def test_application_event_consumers_subscribed() -> None:
    """The three real landing consumers (NeuroBus adoption gate) must stay registered."""
    bus = _fresh_bus_with_core_wiring()
    for event_type in (
        "application.products.imported",
        "application.conversation.message_saved",
        "application.customer.changed",
    ):
        assert bus._handlers.get(event_type), f"no consumer subscribed for {event_type}"
