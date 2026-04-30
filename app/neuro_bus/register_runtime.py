"""
Single startup path: NeuroBus start + NeuroDomain registry + *_domain_handlers.
"""

from __future__ import annotations

import logging

from app.neuro_bus.bus import NeuroBus, get_neuro_bus
from app.neuro_bus.bus_setup import setup_neuro_bus
from app.neuro_bus.register_all_domains_complete import register_domain_handlers_only
from app.neuro_bus.register_all_neuro_domains import register_all_neuro_domains
from app.neuro_bus.runtime_diagnostics import log_subscription_snapshot

logger = logging.getLogger(__name__)

_runtime_registered = False


async def register_neuro_runtime() -> NeuroBus:
    global _runtime_registered
    if _runtime_registered:
        return get_neuro_bus()
    await setup_neuro_bus()
    register_all_neuro_domains()
    bus = get_neuro_bus()
    await register_domain_handlers_only(bus)
    log_subscription_snapshot(bus)
    logger.info("Neuro runtime registered; DomainRegistry=%s", bus.registered_domains)
    _runtime_registered = True
    return bus
