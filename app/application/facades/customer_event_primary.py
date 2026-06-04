"""
Event-primary facade for customer / purchase-unit mutations.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.customer_app_service import CustomerApplicationService
from app.application.facades.event_primary_base import EventPrimaryDispatcher
from app.contexts.flags import is_event_primary_enabled

logger = logging.getLogger(__name__)


class CustomerApplicationServiceEventPrimary:
    def __init__(self, core: CustomerApplicationService) -> None:
        self._core = core
        self._dispatcher = EventPrimaryDispatcher()

    def __getattr__(self, name: str):
        return getattr(self._core, name)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if not is_event_primary_enabled("customer"):
            return self._core.create(data)
        payload = {
            "customer_name": data.get("customer_name") or data.get("unit_name"),
            "contact_person": data.get("contact_person", ""),
            "contact_phone": data.get("contact_phone") or data.get("phone", ""),
            "contact_address": data.get("contact_address") or data.get("address", ""),
            **data,
        }
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("customer.registered", payload),
            lambda: self._core.create(data),
            log_label="customer.create",
        )

    def update(self, customer_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if not is_event_primary_enabled("customer"):
            return self._core.update(customer_id, data)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "customer.updated",
                {"customer_id": customer_id, "updates": data},
            ),
            lambda: self._core.update(customer_id, data),
            log_label="customer.update",
        )

    def delete(self, customer_id: int, force: bool = False) -> dict[str, Any]:
        if not is_event_primary_enabled("customer"):
            return self._core.delete(customer_id, force=force)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "customer.deactivated",
                {"customer_id": customer_id, "force": force},
            ),
            lambda: self._core.delete(customer_id, force=force),
            log_label="customer.delete",
        )

    def batch_delete(self, ids: list[int], force: bool = False) -> dict[str, Any]:
        if not is_event_primary_enabled("customer"):
            return self._core.batch_delete(ids, force=force)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "customer.batch_deactivated",
                {"customer_ids": ids, "force": force},
            ),
            lambda: self._core.batch_delete(ids, force=force),
            log_label="customer.batch_delete",
        )
