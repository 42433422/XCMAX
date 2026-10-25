from __future__ import annotations

from typing import Protocol

from modstore_server.domain.payment_gateway.payment_gateway_types import OrderRef


class PaymentReadRepository(Protocol):
    def get_order(self, order_no: str) -> OrderRef | None: ...


__all__ = ["PaymentReadRepository"]
