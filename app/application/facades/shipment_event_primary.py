"""
Event-primary facade: mutating shipment operations go through NeuroBus commands + handlers.
Read/query methods delegate to the core application service via __getattr__.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.application.facades.event_primary_base import EventPrimaryDispatcher
from app.application.shipment_app_service import ShipmentApplicationService
from app.contexts.flags import is_event_primary_enabled

logger = logging.getLogger(__name__)


class ShipmentApplicationServiceEventPrimary:
    def __init__(self, core: ShipmentApplicationService) -> None:
        self._core = core
        self._dispatcher = EventPrimaryDispatcher()

    def __getattr__(self, name: str):
        return getattr(self._core, name)

    def create_shipment(
        self,
        unit_name: str,
        items_data: list[dict[str, Any]],
        contact_person: str = "",
        contact_phone: str = "",
    ) -> dict[str, Any]:
        if not is_event_primary_enabled("shipment"):
            return self._core.create_shipment(unit_name, items_data, contact_person, contact_phone)
        payload = {
            "shipment_id": f"PENDING-{uuid.uuid4().hex[:12]}",
            "unit_name": unit_name,
            "items": items_data,
            "contact_person": contact_person,
            "contact_phone": contact_phone,
            "deduct_inventory": True,
        }
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("shipment.created", payload),
            lambda: self._core.create_shipment(
                unit_name, items_data, contact_person, contact_phone
            ),
            log_label="shipment.create",
        )

    def cancel_shipment(self, shipment_id: int) -> dict[str, Any]:
        if not is_event_primary_enabled("shipment"):
            return self._core.cancel_shipment(shipment_id)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "shipment.cancelled",
                {"shipment_id": shipment_id, "reason": "user", "restore_inventory": True},
            ),
            lambda: self._core.cancel_shipment(shipment_id),
            log_label="shipment.cancel",
        )

    def delete_shipment(self, shipment_id: int) -> dict[str, Any]:
        if not is_event_primary_enabled("shipment"):
            return self._core.delete_shipment(shipment_id)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "shipment.deleted", {"shipment_id": shipment_id}
            ),
            lambda: self._core.delete_shipment(shipment_id),
            log_label="shipment.delete",
        )

    def mark_as_printed(self, shipment_id: int, printer_name: str = "") -> dict[str, Any]:
        if not is_event_primary_enabled("shipment"):
            return self._core.mark_as_printed(shipment_id, printer_name)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "shipment.printed",
                {
                    "shipment_id": shipment_id,
                    "printer_name": printer_name,
                    "generate_record": True,
                },
            ),
            lambda: self._core.mark_as_printed(shipment_id, printer_name),
            log_label="shipment.printed",
        )
