"""Compatibility shim — prefer ``app.domain.value_objects``.

Shipment domain no longer imports this module (phase-2 train D).
"""

from __future__ import annotations

from app.domain.value_objects import ContactInfo, Money, OrderNumber, Quantity

__all__ = ["Quantity", "Money", "ContactInfo", "OrderNumber"]
