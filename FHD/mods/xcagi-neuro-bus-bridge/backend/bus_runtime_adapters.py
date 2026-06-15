# -*- coding: utf-8 -*-
"""里程碑 S：NeuroBus 运行时委托（生命周期 + 同步发布）。"""

from __future__ import annotations

from typing import Any

PROVIDER_ID = "mod:xcagi-neuro-bus-bridge"
RUNTIME_KIND = "mod_bus_runtime"
DELEGATE = "host.app.neuro_bus"


class ModNeuroBusRuntimeAdapter:
    provider_id = PROVIDER_ID
    runtime_kind = RUNTIME_KIND
    delegate = DELEGATE

    def meta(self) -> dict[str, str]:
        return {
            "provider_id": PROVIDER_ID,
            "runtime_kind": RUNTIME_KIND,
            "adapter_class": type(self).__name__,
            "delegate": DELEGATE,
        }

    async def setup(self) -> None:
        from app.neuro_bus.bus_setup import setup_neuro_bus
        from app.neuro_bus.domains.base import get_domain_registry
        from app.domain.neuro.processors.coordinator import get_processor_coordinator

        await setup_neuro_bus()
        domain_registry = get_domain_registry()
        await domain_registry.initialize_all()
        get_processor_coordinator()

    async def teardown(self) -> None:
        from app.neuro_bus.bus_setup import teardown_neuro_bus
        from app.neuro_bus.domains.base import get_domain_registry

        try:
            domain_registry = get_domain_registry()
            await domain_registry.shutdown_all()
        finally:
            await teardown_neuro_bus()

    def publish(self, event_type: str, payload: dict[str, Any], domain: str = "global") -> bool:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.events.base import EventPriority, NeuroEvent

        bus = get_neuro_bus()
        if not bus.is_running:
            return False
        ev = NeuroEvent(
            event_type=event_type,
            payload=payload,
            priority=EventPriority.NORMAL,
        )
        ev.with_domain(domain)
        return bool(bus.publish(ev))

    def health(self) -> dict[str, Any]:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.bus_setup import get_neuro_bus_manager
        from app.neuro_bus.domains.base import get_domain_registry

        manager = get_neuro_bus_manager()
        bus = get_neuro_bus()
        health = manager.get_health() if manager else {}
        if not isinstance(health, dict):
            health = {}
        health["components"] = {
            "bus_running": bool(bus and bus.is_running),
            "queue_size": bus.get_stats().get("queue_size", 0) if bus else 0,
            "domains": get_domain_registry().list_domains(),
        }
        if bus:
            health["reliability"] = bus.get_reliability_status()
        return health


__all__ = ["ModNeuroBusRuntimeAdapter", "PROVIDER_ID", "RUNTIME_KIND"]
