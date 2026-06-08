"""Payment read-model adapter (Python 侧只读镜像)."""

from __future__ import annotations

from modstore_server.domain.payment_gateway.types import OrderRef


class InMemoryPaymentReadRepository:
    def __init__(self, rows: dict[str, OrderRef] | None = None) -> None:
        self._rows = dict(rows or {})

    def get_order(self, order_no: str) -> OrderRef | None:
        return self._rows.get(order_no)


__all__ = ["InMemoryPaymentReadRepository"]
