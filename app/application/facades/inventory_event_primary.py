"""
Event-primary facade for inventory in/out/transfer mutations.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.facades.event_primary_base import EventPrimaryDispatcher
from app.contexts.flags import is_event_primary_enabled
from app.infrastructure.gateways.inventory import InventoryService

logger = logging.getLogger(__name__)


class InventoryApplicationServiceEventPrimary:
    """Wraps InventoryService for stock mutations via NeuroBus."""

    def __init__(self, core: InventoryService | None = None) -> None:
        self._core = core or InventoryService()
        self._dispatcher = EventPrimaryDispatcher()

    def inventory_in(self, **kwargs: Any) -> dict[str, Any]:
        if not is_event_primary_enabled("inventory"):
            return self._core.inventory_in(**kwargs)
        payload = dict(kwargs)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("inventory.stock_in", payload),
            lambda: self._core.inventory_in(**kwargs),
            log_label="inventory.in",
        )

    def inventory_out(self, **kwargs: Any) -> dict[str, Any]:
        if not is_event_primary_enabled("inventory"):
            return self._core.inventory_out(**kwargs)
        payload = dict(kwargs)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("inventory.stock_out", payload),
            lambda: self._core.inventory_out(**kwargs),
            log_label="inventory.out",
        )

    def inventory_transfer(self, **kwargs: Any) -> dict[str, Any]:
        if not is_event_primary_enabled("inventory"):
            return self._core.inventory_transfer(**kwargs)
        payload = dict(kwargs)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("inventory.transfer", payload),
            lambda: self._core.inventory_transfer(**kwargs),
            log_label="inventory.transfer",
        )
